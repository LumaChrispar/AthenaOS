# SOP-005: QA Review

**Document ID:** SOP-005  
**Version:** 1.0  
**Status:** Locked  
**Trigger:** `DraftCompleted` event (automatic)  
**Config:** `config/quality.yaml` (thresholds), `QA-001.md` (rubric)  
**Rule:** QA is a mandatory gate. No chapter may advance to `APPROVED` without passing this SOP.

---

## Purpose
To execute an objective, mathematically precise review of a drafted chapter against established quality thresholds. Eliminates subjectivity from the acceptance criteria.

---

## Steps

| Step | Action | Owner | Output |
|---|---|---|---|
| 1 | Receive `DraftCompleted` event with `chapter.schema.json` payload | QA Director Service | Review initiated |
| 2 | Set chapter state to `IN_REVIEW` | Runtime (State Machine) | State locked |
| 3 | Load `config/quality.yaml` thresholds and `QA-001.md` rubric into context | Runtime | Scoring criteria active |
| 4 | Run **Consistency Check** — cross-reference all facts in chapter against `story_bible.json` | Continuity QA Service | Consistency score (0–10) |
| 5 | Run **Originality Check** — flag recycled phrases or plot devices from prior chapters | Originality Auditor Service | Originality score (0–10) |
| 6 | Run **Readability Check** — analyse sentence variety, passive voice rate, paragraph length | Readability Auditor Service | Readability score (0–10) |
| 7 | Run **Structural Check** — verify each scene has `goal`, `conflict`, and `disaster` populated | Narrative QA Service | Structural pass/fail |
| 8 | Run **Continuity Check** — verify cliffhanger connects to outline's stated chapter objective | Narrative QA Service | Continuity pass/fail |
| 9 | Calculate weighted composite score using weights from `config/quality.yaml` | QA Director Service | Composite score (0–100) |

---

## Decision Logic

```
IF composite_score >= 85 AND all hard_checks pass:
    → publish ChapterApproved event
    → trigger SOP-004 (Update Story Bible)

IF composite_score < 85 OR any hard_check fails:
    → publish ChapterRejected event
    → generate Defect Report (cite exact scores + reasons)
    → set chapter state to REVISION_REQUIRED
    → send Defect Report to Literary Architect Service
    → increment revision_count for this chapter

IF revision_count >= max_revision_loops (from config/workflow.yaml):
    → publish EscalationRequired event
    → pause pipeline, alert human reviewer
```

---

## Defect Report Format

Every rejection must include:

```
Chapter: [ID]
Revision Attempt: [N of max]
Scores:
  - Consistency: X/10 (threshold: 9)
  - Originality: X/10 (threshold: 9)
  - Readability: X/10 (threshold: 8)
Failed Checks:
  - [Check name]: [Specific reason]
Required Actions:
  - [Precise action the Literary Author must take to address each failure]
```

The QA agent may not rewrite prose. It may only identify failures precisely.
