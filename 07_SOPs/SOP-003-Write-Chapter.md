# SOP-003: Write Chapter

**Document ID:** SOP-003  
**Version:** 1.0  
**Status:** Locked  
**Trigger:** `WriteChapter` command  
**Schema Required:** `chapter.schema.json`, `scene.schema.json`  
**Prerequisite:** `story_bible.json` populated, previous chapter in `APPROVED` state

---

## Purpose
To draft a single chapter as a collection of validated `scene.schema.json` objects, anchored to the Beat Sheet from the approved Outline.

---

## Pre-Flight Checks (Mandatory)

Before any prose is generated, the Runtime validates:
- [ ] `story_bible.json` exists and is not empty
- [ ] Previous chapter is in `APPROVED` state (blocks drafting if not)
- [ ] Chapter Beat Sheet from `outline.json` is loaded into context
- [ ] All character UUIDs referenced in the Beat Sheet exist in `story_bible.json > characters[]`

Failure on any check → `WriteChapter` command rejected with error detail.

---

## Steps

| Step | Action | Owner | Output |
|---|---|---|---|
| 1 | Load context: Beat Sheet + last chapter summary (Tier 2 memory) + world rules (Tier 1 memory) | Runtime / Memory | Context window loaded |
| 2 | Decompose chapter Beat Sheet into individual scenes | SRV-002 (Literary Architect) | Scene list |
| 3 | For each scene: populate `scene.schema.json` fields — `goal`, `conflict`, `disaster`, `pov_character`, `characters_present` | Literary Architect | Scene objects (no prose yet) |
| 4 | Validate all scene objects pass structural logic (does each scene's `disaster` logically lead to the next scene's `goal`?) | QA Service (Structural check) | Structure approved |
| 5 | Issue `WriteSceneProse` command for each scene | Literary Author Service | Prose generated per scene |
| 6 | Populate `prose_content` field in each `scene.schema.json` | Literary Author | Scenes complete |
| 7 | Assemble all scenes into `chapter.schema.json` — populate `summary`, `cliffhanger`, `continuity_notes[]` | Literary Architect | `chapter.schema.json` complete |
| 8 | Publish `DraftCompleted` event | Runtime | QA pipeline triggered (SOP-005) |
