# SOP-001: Create Novel

**Document ID:** SOP-001  
**Version:** 1.0  
**Status:** Locked  
**Trigger:** `InitiateProject` command received by SRV-001 (CEO)  
**Estimated Runtime:** Full pipeline execution

---

## Purpose
This SOP defines the exact, step-by-step sequence for taking a novel from raw idea to published file. Every step is mandatory. No step may be skipped.

---

## Phase 1 — Inception

| Step | Action | Owner | Output |
|---|---|---|---|
| 1.1 | Receive project brief (genre, premise, target length) | SRV-001 (CEO) | Populated `project.schema.json` |
| 1.2 | Validate `project.schema.json` against required fields | Runtime | Error if invalid |
| 1.3 | Load matching genre plugin from `config/plugins/` | Runtime | Plugin manifest active |
| 1.4 | Publish `StoryCreated` event to Event Bus | Runtime | Event logged |

---

## Phase 2 — Architecture

| Step | Action | Owner | Output |
|---|---|---|---|
| 2.1 | Issue `BuildOutline` command | SRV-001 (CEO) | Command dispatched |
| 2.2 | Generate Master Outline + Beat Sheets | SRV-002 (Literary Architect) | `outline.json` |
| 2.3 | Publish `OutlineCompleted` event | SRV-002 | Event logged |
| 2.4 | CEO reviews and approves Outline | SRV-001 | `OutlineApproved` event |

---

## Phase 3 — Character & World Build

| Step | Action | Owner | Output |
|---|---|---|---|
| 3.1 | Issue `BuildCharacterProfiles` command for all major characters | SRV-001 | Command dispatched |
| 3.2 | Generate `character.schema.json` objects | Character Psychologist Service | Character profiles |
| 3.3 | Generate `relationship.schema.json` objects | Relationship Designer Service | Relationship map |
| 3.4 | Issue `BuildWorld` command | SRV-001 | Command dispatched |
| 3.5 | Populate world locations, rules, and lore in `story_bible.json` | World Architect Service | Updated Story Bible |
| 3.6 | Publish `CharacterPlanningCompleted` + `WorldPlanningCompleted` | Runtime | Events logged |

---

## Phase 4 — Research

| Step | Action | Owner | Output |
|---|---|---|---|
| 4.1 | Identify knowledge gaps from outline and world build | Research Director Service | Gap list |
| 4.2 | Load required Contract Specialist researchers (see `SRV-000`) | Runtime | Specialists active |
| 4.3 | Execute research tasks and add findings to `07_Domains/` | Research Specialists | Domain knowledge |
| 4.4 | Publish `ResearchCompleted` event | Research Director | Event logged |

---

## Phase 5 — Drafting

*Repeat for each chapter defined in the outline.*

| Step | Action | Owner | Output |
|---|---|---|---|
| 5.1 | Issue `WriteChapter` command with chapter Beat Sheet | SRV-001 | Command dispatched |
| 5.2 | Load Tier 1 (Constraints) + Tier 2 (Previous chapter) context | Runtime / Memory | Context window loaded |
| 5.3 | Draft chapter prose | Literary Author Service | `scene.schema.json` objects |
| 5.4 | Publish `DraftCompleted` event | Literary Author | Event logged |
| 5.5 | QA automatically triggers on `DraftCompleted` (see SOP-005) | QA Service | QA started |
| 5.6 | If approved → update Story Bible (see SOP-004). If rejected → loop back to 5.1 | Runtime | Chapter state: `APPROVED` |

---

## Phase 6 — Production & Publishing

| Step | Action | Owner | Output |
|---|---|---|---|
| 6.1 | Compile all `APPROVED` chapters into Golden Master markdown | Book Formatter Service | `manuscript.md` |
| 6.2 | Compile EPUB, PDF, DOCX from Golden Master | Publishing Division | Final files |
| 6.3 | Run EPUB validation against IDPF EpubCheck (see PUB-001) | Publishing QA | Validation report |
| 6.4 | Generate metadata, ISBN record, and marketing copy | Metadata + Marketing Services | Market-ready package |
| 6.5 | Publish `ProjectCompleted` event | Runtime | Pipeline closed |
