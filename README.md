# DraftLens EDU

**Explainable 2D CAD assessment that turns drawing errors into visible, evidence-based feedback.**

DraftLens EDU is an education-first grading and review system for 2D CAD assignments. It compares a student's DXF submission with an instructor-approved reference, applies a transparent rubric, identifies and localizes drawing errors, explains every deduction, recommends relevant AutoCAD correction commands, and exports an authoritative visual PDF report.

The project was created during **OpenAI Build Week** by **Moukid Badie**, a CAD, CG, visualization, and interior-design educator, in close collaboration with **GPT-5.6 and Codex**.

> DraftLens EDU does not replace the instructor. It makes grading evidence visible, consistent, reviewable, and easier to explain.

---

## The problem

Students need frequent practice to become accurate and confident in CAD, but grading many drawing submissions is slow. A careful instructor may need to inspect lengths, angles, positions, missing entities, duplicate geometry, topology, file organization, and drawing completeness for every student file.

Manual grading can also be affected by workload, fatigue, different grading sessions, and differences between instructors.

DraftLens EDU addresses this by linking every score decision to explicit evidence:

- reference and student entities;
- expected and actual measurements;
- approved tolerances;
- rubric rules;
- raw and applied deductions;
- category and rule caps;
- suppression or supporting-evidence reasons;
- correction explanations;
- relevant CAD commands.

---

## What DraftLens EDU does

DraftLens EDU provides a complete instructor-controlled review workflow:

1. Upload an instructor reference DXF.
2. Review reference validation findings.
3. Confirm the assignment title and assignment type.
4. Review and approve the editable **DraftLens Baseline Rubric**.
5. Select placement and completion policies.
6. Upload a student DXF.
7. Check whether the submission is compatible with the selected reference.
8. Generate a deterministic score and reviewed drawing.
9. Inspect primary issues, supporting topology evidence, measurements, deductions, and correction guidance.
10. Switch between comparison view and the original student-only view.
11. Export an authoritative multi-page PDF grading report.

---

## Final Build Week feature set

### Reference and assignment control

- instructor reference-DXF upload;
- deterministic reference validation;
- instructor-confirmed assignment title;
- instructor-confirmed assignment type;
- neutral assignment suggestions without automatic cultural classification;
- editable DraftLens Baseline Rubric;
- rubric approval and reapproval lifecycle;
- clear rubric source and instructor-modified status.

### Geometry and comparison

- deterministic DXF parsing and canonical geometry construction;
- exact and approximate entity matching;
- strict-placement grading;
- translation-tolerant grading;
- accepted-transform evidence;
- robust global-displacement diagnosis in Strict mode;
- uniform-scale mismatch diagnosis without automatically changing student geometry;
- reference-aware topology and endpoint-gap analysis;
- deterministic repeated-geometry matching;
- causal issue classification to reduce double deductions.

### Grading integrity

- compatibility states:
  - `compatible`
  - `suspicious`
  - `incompatible`
  - `empty_or_ungradable`
- coherent-correspondence checks so generic geometric similarities do not establish assignment compatibility;
- wrong-assignment submissions are withheld as **Not graded**;
- likely global scale or unit mismatches are withheld for instructor review;
- explicit, submission-specific **Grade anyway** override;
- PDF export remains unavailable for withheld submissions until an instructor override;
- compatibility warnings and overrides are recorded in the authoritative report.

### Transparent scoring

DraftLens EDU separates the score into:

- **Geometric accuracy** — matched geometry, dimensions, placement, shape, and topology;
- **Completion** — missing required reference geometry;
- **File quality** — extra, duplicate, unsupported, invalid, or technically defective student geometry.

The default baseline weights are:

| Category | Available points |
|---|---:|
| Geometric accuracy | 65 |
| Completion | 25 |
| File quality | 10 |
| **Total** | **100** |

The rubric is editable by the instructor. Any modification requires reapproval before grading.

Every scored finding can expose:

- score category;
- raw rule deduction;
- deduction after rule cap;
- deduction after category cap;
- final applied contribution;
- deduction status;
- cap or suppression reason.

### Feedback and reviewed drawing

- reviewed SVG with stable issue IDs;
- visual roles for Reference, Student, Missing, Extra, Inaccurate, Connectivity, Warning, and Critical;
- selectable issue highlights;
- localized measurement regions;
- expected and actual values;
- deviation and tolerance evidence;
- primary, supporting, derived, suppressed, informational, and reference findings;
- **Student only** mode showing the submitted drawing without DraftLens overlays;
- deterministic “How to correct” guidance;
- safe command recommendations such as `MOVE`, `LENGTHEN`, `ROTATE`, `LINE`, `ERASE`, `OVERKILL`, and `OSNAP`.

DraftLens recommends useful correction commands. It does **not** claim to know which commands the student originally used.

### Authoritative PDF reports

- immutable review snapshots;
- opaque review identifiers;
- deterministic multi-page A4 reports;
- vector reviewed drawing;
- drawing-overlay legend;
- prominent earned/available category scores;
- compatibility and normalization evidence;
- correction-guidance callouts;
- compact presentation for large finding sets;
- safe deterministic download filenames;
- repeated exports from one snapshot are byte-identical;
- generated reports reopen successfully with `pypdf`;
- zero raster image XObjects in the reviewed drawing.

---

## Supported DXF entities

The competition build supports these DXF entity types:

- `LINE`
- `LWPOLYLINE`
- `POLYLINE`
- `CIRCLE`
- `ARC`
- `ELLIPSE`
- `SPLINE`
- `TEXT`
- `MTEXT`
- `DIMENSION`

Unsupported or ungradable entities are reported rather than silently treated as correct.

Native DWG parsing is not included in this release.

---

## Controlled behavior examples

The regression suite preserves these baseline results:

| Controlled case | Expected result |
|---|---:|
| Basic geometry exact copy | 100 |
| Basic geometry missing required line | 95 |
| Incorrect length | 97 |
| Incorrect angle | 97 |
| Incorrect position | 97 |
| Incorrect radius | 97 |
| Extra entity | 98 |
| Exact duplicate entity | 99 |
| Complex pattern exact copy | 100 |
| Complex pattern multi-error sample | 74 |
| Partial recognizable interior-plan work | 20 |
| Two moved arcs in interior plan | 97 |
| Complete translated plan — Strict | 50 |
| Complete translated plan — Translation-tolerant | 100 |
| Unrelated assignment file | Not graded |
| Uniformly scaled complete plan | Suspicious / Not graded |

Supporting topology findings explain consequences such as endpoint gaps but do not receive a separate deduction when they are linked to a scored primary cause.

---

## Architecture

```text
Reference DXF + Student DXF
            │
            ▼
Parsing and reference validation
            │
            ▼
Instructor-confirmed assignment and rubric
            │
            ▼
Compatibility and scale diagnostics
            │
            ▼
Normalization and deterministic matching
            │
            ▼
Topology and causal issue analysis
            │
            ▼
Transparent scoring and reconciliation
            │
            ▼
Reviewed SVG + authoritative vector PDF
```

Core production modules include:

- DXF parsing and canonical geometry;
- validation;
- normalization;
- deterministic matching;
- topology analysis;
- causal issue analysis;
- compatibility and scale diagnostics;
- scoring and reconciliation;
- correction guidance;
- reviewed SVG generation;
- immutable review snapshots;
- PDF generation;
- FastAPI endpoints;
- browser UI.

---

## Deterministic grading boundary

GPT-5.6 is **not** asked to measure geometry or calculate grades at runtime.

Geometry is measured by deterministic code. Scores are calculated from approved rules. Compatibility decisions use deterministic evidence. The instructor retains final authority through approval and explicit override controls.

This boundary is intentional: AI supported the design and development process, while the released grading engine remains inspectable, reproducible, and testable.

---

## How GPT-5.6 contributed

GPT-5.6 helped:

- convert classroom experience into explicit product requirements;
- challenge an early architecture that was too specific to walls, doors, and windows;
- define grading categories, tolerances, completion, partial credit, and instructor authority;
- identify double-deduction risks;
- separate primary causes from secondary geometric consequences;
- design compatibility safeguards for wrong files and global scale mismatches;
- evaluate manual test results and question scores that were mathematically valid but educationally illogical;
- define acceptance tests and release criteria;
- separate the competition MVP from the longer roadmap;
- prepare implementation instructions, documentation, and demonstration structure.

The collaboration changed the assessment model from a final mark into an evidence-and-feedback workflow.

---

## How Codex contributed

Codex helped:

- inspect and restructure the repository;
- implement DXF parsing and canonical geometry;
- build normalization and deterministic matching;
- implement reference-aware topology;
- implement causal issue classification and score reconciliation;
- create compatibility and scale-diagnostic safeguards;
- implement correction guidance;
- build the reviewed SVG interface;
- build authoritative vector PDF reports;
- optimize a dense 1,942-entity reference from a non-terminating calculation to approximately one second of analysis;
- create controlled DXF fixtures;
- diagnose regressions and false-positive matching;
- implement and run the automated test suite;
- preserve release checkpoints through Git branches and tags.

The educator remained responsible for the educational problem, assignment design, grading philosophy, manual validation, product decisions, and final scope.

> GPT-5.6 helped decide what should be built and why. Codex helped build, test, diagnose, and correct it.

---

## Key Build Week decisions

1. **Rejected the first architecture.**  
   DraftLens needed to become a general 2D geometric-assessment engine rather than a hard-coded wall, door, and window detector.

2. **Kept grading deterministic.**  
   AI does not calculate the runtime grade.

3. **Removed command-history surveillance.**  
   DraftLens recommends efficient commands but does not claim to reconstruct the student’s workflow.

4. **Added causal scoring.**  
   Secondary consequences do not automatically become repeated deductions.

5. **Made compatibility a grading precondition.**  
   The system does not blindly produce a plausible score for every DXF.

6. **Separated scale diagnosis from automatic correction.**  
   A likely unit or scale mismatch is identified and withheld for instructor review.

7. **Kept the instructor in control.**  
   Assignment confirmation, rubric approval, placement policy, and explicit override remain instructor decisions.

8. **Prioritized explainability over feature count.**  
   The competition release includes PDF reporting but defers reviewed-DXF export, authentication, persistence, and batch analytics.

---

## Prior art and positioning

Automated CAD grading has academic prior art. DraftLens EDU does not claim to be the first CAD autograder.

Its focus is the complete educational workflow:

```text
Instructor intent
→ approved assignment and rubric
→ compatibility protection
→ deterministic evidence
→ transparent scoring
→ exact spatial feedback
→ correction guidance
→ improved next attempt
```

---

## Technology stack

- Python 3.12
- FastAPI 0.116.1
- Uvicorn 0.35.0
- ezdxf 1.4.2
- Shapely 2.1.1
- ReportLab 4.5.1
- Pillow 12.3.0 — required transitively by ReportLab; not imported by DraftLens production modules
- pypdf 6.14.2 — report verification
- pytest 8.4.1
- JavaScript
- HTML
- CSS
- SVG
- OpenAI Codex
- GPT-5.6

---

## Installation

### Supported environment

The competition build was developed and tested on:

- Windows 10/11
- Python 3.12

### Clone

Use the green **Code** button on the GitHub repository page, copy the HTTPS URL, and clone the repository.

After cloning:

```powershell
cd DraftLens-EDU
```

### Create a virtual environment

PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Command Prompt:

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate.bat
```

### Install runtime dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

For development and test dependencies:

```powershell
pip install -r requirements-dev.txt
```

### Run

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

---

## Test files and repository policy

No sample DXF files are included. DXF and DWG files must not be added,
tracked, committed, or uploaded to this repository.

Testers must provide their own reference and student files, stored locally
outside the repository. Test files should not contain confidential or personal
information. Use the existing DXF upload workflow; this policy does not change
upload functionality or add DWG support.

Automated tests generate synthetic geometry in external temporary directories;
no personal or historical DXF fixture files are required.

After cloning, install the commit guard:

```powershell
python scripts/install_git_hooks.py
python scripts/check_cad_policy.py
```

Ignore rules cover both extensions in every letter case. The commit guard also
rejects force-staged CAD files. CI checks the index and full reachable history.
Hooks must be installed in every clone; the owner should require the CI policy
job in branch protection. See [the permanent policy](docs/fixture_privacy_verification.md)
for setup, manual synthetic-data generation, privacy checks, and history verification.

### Manual workflow

1. Start the application.
2. Upload the reference DXF.
3. Confirm the assignment title and assignment type.
4. Review and approve the rubric.
5. Select placement and completion policies.
6. Upload the student DXF.
7. Run the review.
8. Inspect the compatibility result and score.
9. Select an issue card.
10. Review measurements, deductions, and “How to correct” guidance.
11. Switch between **Review comparison** and **Student only**.
12. Download the PDF report.
13. Confirm that browser and PDF scores match.

---

## Automated tests

```powershell
pip install -r requirements-dev.txt
python -B -m pytest -q -p no:cacheprovider
python scripts/check_cad_policy.py --history
```

The full suite runs with generated synthetic data outside the repository.
It covers grading, compatibility, topology, uploads, reports, UI contracts,
privacy detection and CAD-file commit enforcement. A full clone is required
only for the separate history-policy command, not for pytest.


## Release information

```text
Release branch:
release/competition-v2

Verified code commit:
1f57c6f0cd06816ff072504b0099fa8e0e5a6d96

Verified code tag:
draftlens-edu-code-final-v2
```

The final documentation and sample-data commit may have a later commit hash. The code tag above identifies the exact production checkpoint that passed the 304-test verification gate.

---

## Current limitations

The competition release does not include:

- native DWG parsing;
- automatic drawing-time extraction;
- command-history tracking;
- plagiarism detection;
- LMS or Excel synchronization;
- batch grading or class analytics;
- a database;
- authentication;
- persistent rubric or review storage;
- multi-user or multi-worker synchronization;
- automatic global rotation alignment;
- automatic scale correction;
- native reviewed-DXF export;
- complete support for every DXF entity;
- production Arabic right-to-left shaping in PDF reports;
- fully autonomous AI grading.

Additional notes:

- rubric and review state are held in memory;
- review snapshots expire and are bounded by time, count, and memory;
- scale mismatch is diagnosed but the submitted geometry is not automatically changed;
- unsupported entities are reported rather than silently graded;
- instructor review remains mandatory.

---

## Roadmap

- reviewed DXF with dedicated feedback layers;
- native DWG support and drawing-time metadata;
- persistent database and authenticated instructor accounts;
- batch grading and class analytics;
- LMS and Excel integration;
- plagiarism and similarity analysis;
- rubric library and assignment-specific templates;
- English and Arabic feedback;
- learning-outcome and next-assignment guidance;
- Autodesk Platform Services integration;
- expansion to 3D modelling, rendering, visualization, and other CG disciplines.

---

## Privacy and academic responsibility

- use anonymized student identifiers;
- do not publish real student work without permission;
- treat DraftLens EDU as instructor decision support;
- preserve instructor approval and override records;
- validate the reference assignment before grading;
- verify high-stakes grades manually before official publication.

---

## License

This repository is licensed under the MIT License. See [`LICENSE`](LICENSE).

---

## Creator

**Moukid Badie**  
CAD, CG, visualization, interior-design, and AI educator  
Egypt
