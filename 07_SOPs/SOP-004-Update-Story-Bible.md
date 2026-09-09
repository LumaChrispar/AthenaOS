# SOP-004: Update Story Bible

**Document ID:** SOP-004  
**Version:** 1.0  
**Status:** Locked  
**Trigger:** `ChapterApproved` event (automatic)  
**Schema Required:** `story_bible.json`  
**Rule:** This SOP is MANDATORY after every approved chapter. It may never be skipped.

---

## Purpose
To harvest all new canonical facts from an approved chapter and permanently write them into `story_bible.json` — the single source of truth. This prevents continuity drift across the lifetime of the project.

---

## Steps

| Step | Action | Owner | Output |
|---|---|---|---|
| 1 | Receive `ChapterApproved` event with `chapter.schema.json` payload | Story Bible Manager Service | Event received |
| 2 | Parse `continuity_notes[]` from approved chapter | Story Bible Manager | New fact list |
| 3 | Update `story_bible.json > timeline[]` with any new `timeline_event.schema.json` objects from this chapter | Timeline Manager Service | Timeline updated |
| 4 | Update `story_bible.json > characters[]` for any characters whose `arc_progress`, `status`, `inventory`, or location changed | Character Memory Manager Service | Character records updated |
| 5 | Update `story_bible.json > unresolved_threads[]` — add any new open questions, remove any that were resolved | Story Bible Manager | Thread list updated |
| 6 | Update `story_bible.json > locations[]` if any new location was introduced | Location Manager Service | Locations updated |
| 7 | Increment chapter count and update project `progress` percentage in `project.schema.json` | Runtime | Project record updated |
| 8 | Publish `StoryBibleUpdated` event | Runtime | Event logged |

---

## Validation
The Memory Auditor Service verifies after every update:
- [ ] No two `timeline_event` objects share the same `date` string with different `participants[]`
- [ ] No character's `status` was silently changed without a corresponding `timeline_event`
- [ ] `unresolved_threads[]` does not contain duplicate entries

Failure triggers a `StoryBibleCorruption` alert — the highest-priority event in the system, requiring immediate human review.
