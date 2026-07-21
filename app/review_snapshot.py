from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
import unicodedata
from typing import Any, Callable

from .reviewed_dxf import ReviewedDrawing


DEFAULT_TTL_SECONDS = 30 * 60
DEFAULT_MAX_SNAPSHOTS = 8
DEFAULT_MAX_RAW_BYTES = 160 * 1024 * 1024
_EXPIRED_TOMBSTONES = 64


class SnapshotNotFound(KeyError):
    """The opaque review ID was never created or was capacity-evicted."""


class SnapshotExpired(KeyError):
    """The review ID existed but its short-lived snapshot has expired."""


class SnapshotCapacityError(ValueError):
    """A single upload pair cannot fit inside the configured memory budget."""


class StudentMetadataError(ValueError):
    """Optional student metadata failed its display-only validation contract."""


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_field(value: str | None, label: str, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFC", str(value)).strip()
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise StudentMetadataError(f"{label} must be {maximum} characters or fewer.")
    if any(
        unicodedata.category(character) == "Cc" or character in {"\u2028", "\u2029"}
        for character in normalized
    ):
        raise StudentMetadataError(f"{label} contains unsupported control or line-break characters.")
    return normalized


@dataclass(frozen=True, slots=True)
class StudentMetadata:
    student_name: str | None = None
    student_id: str | None = None
    course_section: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "student_name": self.student_name,
            "student_id": self.student_id,
            "course_section": self.course_section,
        }


def normalize_student_metadata(
    student_name: str | None = None,
    student_id: str | None = None,
    course_section: str | None = None,
) -> StudentMetadata:
    return StudentMetadata(
        student_name=_normalize_field(student_name, "Student name", 120),
        student_id=_normalize_field(student_id, "Student ID", 64),
        course_section=_normalize_field(course_section, "Course / section", 120),
    )


@dataclass(frozen=True, slots=True)
class ReviewSnapshot:
    review_id: str
    report_timestamp: str
    expires_at: datetime
    reference_filename: str
    reference_sha256: str
    raw_reference_bytes: bytes
    student_filename: str
    student_sha256: str
    raw_student_bytes: bytes
    student_metadata: StudentMetadata
    approved_rubric_id: str | None
    approved_rubric_json: str
    assignment_title: str
    assignment_type: str | None
    suggested_assignment_type: str
    detected_features: tuple[str, ...]
    reviewed_drawing: ReviewedDrawing
    review_response_json: str
    reviewed_svg: str
    score_breakdown_json: str
    normalization_decision_json: str

    @property
    def raw_byte_size(self) -> int:
        return len(self.raw_reference_bytes) + len(self.raw_student_bytes)

    @property
    def approved_rubric(self) -> dict[str, Any]:
        return json.loads(self.approved_rubric_json)

    @property
    def review_response(self) -> dict[str, Any]:
        return json.loads(self.review_response_json)

    @property
    def score_breakdown(self) -> dict[str, Any]:
        return json.loads(self.score_breakdown_json)

    @property
    def normalization_decision(self) -> dict[str, Any]:
        return json.loads(self.normalization_decision_json)


class ReviewSnapshotStore:
    """Bounded single-process LRU store for authoritative review exports."""

    def __init__(
        self,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_snapshots: int = DEFAULT_MAX_SNAPSHOTS,
        max_raw_bytes: int = DEFAULT_MAX_RAW_BYTES,
        clock: Callable[[], datetime] = _utc_now,
        token_factory: Callable[[], str] | None = None,
    ):
        if ttl_seconds <= 0 or max_snapshots <= 0 or max_raw_bytes <= 0:
            raise ValueError("Snapshot limits must be positive.")
        self.ttl_seconds = int(ttl_seconds)
        self.max_snapshots = int(max_snapshots)
        self.max_raw_bytes = int(max_raw_bytes)
        self._clock = clock
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(24))
        self._snapshots: OrderedDict[str, ReviewSnapshot] = OrderedDict()
        self._expired: OrderedDict[str, None] = OrderedDict()
        self._raw_bytes = 0

    def clear(self) -> None:
        self._snapshots.clear()
        self._expired.clear()
        self._raw_bytes = 0

    def __len__(self) -> int:
        return len(self._snapshots)

    @property
    def total_raw_bytes(self) -> int:
        return self._raw_bytes

    def _remember_expired(self, review_id: str) -> None:
        self._expired[review_id] = None
        self._expired.move_to_end(review_id)
        while len(self._expired) > _EXPIRED_TOMBSTONES:
            self._expired.popitem(last=False)

    def _remove(self, review_id: str) -> ReviewSnapshot:
        snapshot = self._snapshots.pop(review_id)
        self._raw_bytes -= snapshot.raw_byte_size
        return snapshot

    def _expire(self, now: datetime) -> None:
        for review_id, snapshot in tuple(self._snapshots.items()):
            if now >= snapshot.expires_at:
                self._remove(review_id)
                self._remember_expired(review_id)

    def _new_id(self) -> str:
        for _ in range(8):
            candidate = str(self._token_factory())
            if candidate and candidate not in self._snapshots and candidate not in self._expired:
                return candidate
        raise RuntimeError("Could not allocate a unique review ID.")

    def create(
        self,
        *,
        reference_filename: str,
        reference_bytes: bytes,
        student_filename: str,
        student_bytes: bytes,
        student_metadata: StudentMetadata,
        approved_rubric_id: str | None,
        approved_rubric: dict[str, Any],
        assignment_title: str,
        assignment_type: str | None,
        suggested_assignment_type: str,
        detected_features: list[str] | tuple[str, ...],
        reviewed_drawing: ReviewedDrawing,
        review_response: dict[str, Any],
    ) -> ReviewSnapshot:
        now = _utc(self._clock())
        self._expire(now)
        raw_size = len(reference_bytes) + len(student_bytes)
        if raw_size > self.max_raw_bytes:
            raise SnapshotCapacityError("The review uploads exceed the snapshot memory limit.")
        while self._snapshots and (
            len(self._snapshots) >= self.max_snapshots
            or self._raw_bytes + raw_size > self.max_raw_bytes
        ):
            oldest_id = next(iter(self._snapshots))
            self._remove(oldest_id)

        review_id = self._new_id()
        timestamp = _iso(now)
        final_response = json.loads(_json(review_response))
        final_response.update(
            {
                "review_id": review_id,
                "report_timestamp": timestamp,
                "report_available": True,
                "student_metadata": student_metadata.to_dict(),
            }
        )
        snapshot = ReviewSnapshot(
            review_id=review_id,
            report_timestamp=timestamp,
            expires_at=now + timedelta(seconds=self.ttl_seconds),
            reference_filename=str(reference_filename),
            reference_sha256=hashlib.sha256(reference_bytes).hexdigest(),
            raw_reference_bytes=bytes(reference_bytes),
            student_filename=str(student_filename),
            student_sha256=hashlib.sha256(student_bytes).hexdigest(),
            raw_student_bytes=bytes(student_bytes),
            student_metadata=student_metadata,
            approved_rubric_id=approved_rubric_id,
            approved_rubric_json=_json(approved_rubric),
            assignment_title=str(assignment_title),
            assignment_type=assignment_type,
            suggested_assignment_type=str(suggested_assignment_type),
            detected_features=tuple(str(item) for item in detected_features),
            reviewed_drawing=reviewed_drawing,
            review_response_json=_json(final_response),
            reviewed_svg=str(final_response["svg"]),
            score_breakdown_json=_json(final_response["score_breakdown"]),
            normalization_decision_json=_json(final_response["normalization_decision"]),
        )
        self._snapshots[review_id] = snapshot
        self._raw_bytes += raw_size
        return snapshot

    def get(self, review_id: str) -> ReviewSnapshot:
        now = _utc(self._clock())
        self._expire(now)
        if review_id in self._expired:
            raise SnapshotExpired(review_id)
        snapshot = self._snapshots.get(review_id)
        if snapshot is None:
            raise SnapshotNotFound(review_id)
        self._snapshots.move_to_end(review_id)
        return snapshot
