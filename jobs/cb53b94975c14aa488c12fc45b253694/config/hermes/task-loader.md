# AthenaOS Task Loader Protocol

Because AthenaOS is too large to fit in a single context window, you must load files into Hermes **only when they are needed for a specific stage of production**.

Use this guide to know what files to attach or paste into Hermes for each phase of your book.

---

### PHASE 1: Project Initialization & Outlining
**Goal:** Generate the core concept and architectural blueprint.
**Acting Service:** SRV-002 (Story Architect)
**Files to upload/paste into Hermes:**
1. `06_Services/SRV-002.md` (The rules for the Architect)
2. `08_Memory/schemas/project.schema.json` (Blank or partially filled out by you)
**Your Prompt to Hermes:** *"Acting as SRV-002, use the provided schema to help me design the structural blueprint for a [Genre] novel about [brief idea]. Generate the Story Blueprint and Chapter Roadmap."*

---

### PHASE 2: Character Psychology & Worldbuilding
**Goal:** Create deep psychological profiles and world rules before writing.
**Acting Services:** SRV-003 (Psychologist) & SRV-004 (World Builder)
**Files to upload/paste into Hermes:**
1. `06_Services/SRV-003.md` AND/OR `06_Services/SRV-004.md`
2. The output from Phase 1 (The Outline/Blueprint)
**Your Prompt to Hermes:** *"Acting as SRV-003, take the attached outline and generate deep psychological profiles for the protagonist and antagonist based on the Complete Character Excavation Protocol."*

---

### PHASE 3: Prose Generation (Drafting)
**Goal:** Write actual chapters of the book.
**Acting Service:** SRV-005 (Literary Author)
**Files to upload/paste into Hermes:**
1. `06_Services/SRV-005.md` (The Author's rules: show don't tell, sensory protocol, etc.)
2. The current Chapter Roadmap / Beat Sheet from Phase 1
3. The specific Character Profile from Phase 2
4. `08_Memory/schemas/chapter.schema.json`
**Your Prompt to Hermes:** *"Acting as SRV-005, draft Chapter 1. Use the attached character profile and beat sheet. Ensure you follow the Sensory Writing Protocol."*

---

### PHASE 4: Review and Quality Assurance
**Goal:** Audit the drafted chapter for story quality, continuity, and grammar.
**Acting Services:** SRV-007 (Dev Editor), SRV-016 (Continuity), SRV-008 (Copy Editor)
**Files to upload/paste into Hermes:**
1. The relevant SRV file for the edit you want (e.g., `SRV-007.md`)
2. The drafted chapter from Phase 3
3. `08_Memory/story_bible.json` (If doing a continuity check)
**Your Prompt to Hermes:** *"Acting as SRV-007, perform a developmental edit on the attached draft chapter according to your Evaluation Framework. Provide a Priority Revision List."*

---

### PHASE 5: Publishing & Metadata
**Goal:** Generate title, blurb, keywords, and formatting.
**Acting Service:** SRV-019 (Publishing Consultant)
**Files to upload/paste into Hermes:**
1. `06_Services/SRV-019.md`
2. The finished Outline and/or Drafts
**Your Prompt to Hermes:** *"Acting as SRV-019, generate the title options, commercial blurb, and 7 BISAC keywords for this completed manuscript."*
