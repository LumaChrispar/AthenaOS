# SOP-002: Create Character

**Document ID:** SOP-002  
**Version:** 1.0  
**Status:** Locked  
**Trigger:** `BuildCharacterProfiles` command  
**Schema Required:** `character.schema.json`, `character/psychology.schema.json`, `character/appearance.schema.json`

---

## Purpose
To generate a complete, psychologically rigorous character object that populates the Story Bible and can be validated by any downstream service. All output must conform strictly to the character schema.

---

## Steps

| Step | Action | Owner | Output |
|---|---|---|---|
| 1 | Receive character brief (role in story, archetype) from Outline | Character Director Service | Brief confirmed |
| 2 | Assign UUID: `char_xxxxxxxx` | Runtime | `character_id` set |
| 3 | Generate `psychology.schema.json` — define `core_belief`, `fatal_flaw`, `fears`, `trauma`, `moral_alignment` | Character Psychologist Service | Psychology object |
| 4 | Generate `appearance.schema.json` — define physical and vocal traits | Character Biographer Service | Appearance object |
| 5 | Define `goals[]` — one internal goal, one external goal (must be in tension with each other) | Character Psychologist Service | Goals array |
| 6 | Set `arc_progress: 0` and `status: "active"` | Runtime | Fields set |
| 7 | Write character `history` — backstory prior to Chapter 1 | Character Biographer Service | History string |
| 8 | Assign `abilities[]` and `inventory[]` relevant to genre plugin rules | World Architect / Character Service | Arrays populated |
| 9 | Publish `CharacterCreated` event + write object to `story_bible.json > characters[]` | Runtime | Story Bible updated |

---

## Quality Gate

Before `CharacterCreated` is published, the Character Consistency Auditor Service validates:
- [ ] Does the character's `core_belief` create a logical reason for their `goals[]`?
- [ ] Does their `fatal_flaw` conflict with at least one goal (internal tension)?
- [ ] Are `fears[]` psychologically consistent with their `trauma[]`?

Failure to pass any check returns a `CharacterRejected` event and loops back to Step 3.
