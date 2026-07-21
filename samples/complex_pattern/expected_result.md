# Expected Results — Complex Pattern

## Files

```text
Reference:
reference_complex_pattern.dxf

Exact-copy student:
student_complex_pattern_score_100.dxf

Advanced multi-error student:
student_complex_pattern_multi_error.dxf

Translated student:
student_complex_pattern_translated.dxf
```

## Exact-copy result

```text
Compatibility: Compatible
Score: 100 / 100
Geometric accuracy: 65 / 65
Completion: 25 / 25
File quality: 10 / 10
Primary issues: 0
Supporting findings: 0
Reference notes: 0
Unsupported entities: 0
PDF report: Available
```

This validates dense-reference performance and confirms that the 1,942-entity reference does not produce false open-polyline warnings.

## Advanced multi-error result

```text
Compatibility: Compatible
Score: 74 / 100
Geometric accuracy: 44 / 65
Completion: 20 / 25
File quality: 10 / 10
Primary findings: 60
Supporting findings: 20
Reference notes: 0
Unsupported entities: 0
Total applied deduction: 26 points
PDF report: Available
PDF length: 8 pages
```

Verified finding profile:

```text
Incorrect Position findings: 57
Missing Geometry findings: present
Incorrect Length findings: present
Rule-repeat caps: applied
Compact finding summary: enabled
Supporting endpoint-gap evidence: informational, not scored again
```

This is intentionally an advanced multi-error sample. It is not intended to represent one isolated student mistake.

## Translated result

Under Strict placement:

```text
Compatibility: Compatible
Score: 50 / 100
Primary issues: 1
Issue: Global Drawing Displacement
Detected displacement: X = 75, Y = -40
Displacement magnitude: 85
Consensus support: 1872 / 1884 entities
PDF report: Available
```

Under Translation-tolerant placement, the accepted translation should remove the global-placement deduction when the complete drawing remains coherent.

## Recommended judge use

Use the exact-copy file to demonstrate scalability. Use the multi-error file only when demonstrating repeated-geometry handling, score caps, compact summaries, multiple issue types, and supporting topology evidence.
