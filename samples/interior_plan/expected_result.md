# Expected Results — Interior Plan

## Files

```text
Reference:
reference_clean.dxf

Translated student:
whole_plan_translated.dxf

Moved-arc student:
student_two_moved_arcs.dxf
```

## Whole-plan translation

### Strict placement

```text
Compatibility: Compatible
Score: 50 / 100
Geometric accuracy: 15 / 65
Completion: 25 / 25
File quality: 10 / 10
Primary issues: 1
Supporting findings: 0
Issue: Global Drawing Displacement
Detected displacement: X = 100, Y = -50
Displacement magnitude: 111.803
Consensus support: 103 / 103 entities
Applied deduction: 50 points
PDF report: Available
```

### Translation-tolerant placement

```text
Compatibility: Compatible
Score: 100 / 100
Accepted translation: Displayed
Global placement deduction: None
PDF report: Available
```

This pair demonstrates that DraftLens distinguishes geometric correctness from assignment-origin policy.

## Two moved arcs

```text
Compatibility: Compatible
Score: 97 / 100
Geometric accuracy: 62 / 65
Completion: 25 / 25
File quality: 10 / 10
Primary issues: 1
Supporting findings: 2
Applied deduction: 3 points
PDF report: Available
```

Primary finding:

```text
Issue type: Incorrect Position
Actual position shift: 20
Rule: RULE-POSITION-01
Applied deduction: 3 points
Correction command: MOVE
Precision aid: OSNAP
```

The two endpoint-gap findings are supporting topology evidence and receive no separate deduction.
