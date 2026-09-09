# State Machine Rules

**Document ID:** WF-003  
**Version:** 1.0  
**Status:** Locked  

---

## 1. Purpose
This document defines the strict, non-bypassable state machine for narrative objects (Chapters, Scenes, Characters) within Athena OS. 

## 2. The Core State Engine
Every major artifact in Athena transitions through the following mandatory states.

### State 1: `PLANNED`
- The object exists only as a requirement in the Story Bible or Outline.
- **Valid Transition:** Moves to `DRAFTING` when a `WriteX` command is accepted by a Service.

### State 2: `DRAFTING`
- The Service is actively generating the payload.
- **Valid Transition:** Moves to `IN_REVIEW` when a `DraftCompleted` event is published to the Event Bus.

### State 3: `IN_REVIEW` (Mandatory QA Gate)
- The object is locked. Generating services cannot modify it.
- The QA Service runs logical, continuity, and prose checks (enforcing `quality.yaml`).
- **Valid Transition (Pass):** Moves to `APPROVED` if the score meets the global threshold (85+).
- **Valid Transition (Fail):** Moves to `REVISION_REQUIRED` if the score is below threshold.

### State 4: `REVISION_REQUIRED`
- The object is sent back to the generating Service along with a Defect Report.
- **Valid Transition:** Moves back to `IN_REVIEW` once the `RevisionCompleted` event is published.
- *Note: If a document hits this state 3 times, it triggers an `Escalation` event (per `workflow.yaml`).*

### State 5: `APPROVED`
- The object is finalized and locked. It is merged into the Golden Master (`PUB-001`).
- The Story Bible is permanently updated with any new continuity facts from this object.

## 3. The Golden Rule
**NO AGENT MAY SKIP A STATE.** 
A `PLANNED` document can never become `APPROVED` without passing through `IN_REVIEW`. The Athena Runtime will reject any state transition event that violates this sequential logic.
