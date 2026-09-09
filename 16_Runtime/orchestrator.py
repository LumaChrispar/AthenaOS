import os
import json
import asyncio
from llm_client import AthenaLLMClient
from service_loader import load_service, format_system_prompt
from memory_manager import MemoryManager
from context_builder import ContextBuilder, build_scene_brief
from job_runner import atomic_json
import yaml


def parse_json(response):
    text = response.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0]
    return json.loads(text)

class Orchestrator:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.llm = AthenaLLMClient(os.path.join(base_dir, "config", "models.yaml"))
        self.memory = MemoryManager(base_dir)
        self.context_builder = ContextBuilder(base_dir)
        self.active_critique_notes = []
        with open(os.path.join(base_dir, 'config', 'quality.yaml'), encoding='utf-8') as stream:
            self.quality_config = yaml.safe_load(stream)
        self.max_revision_attempts = self.quality_config['revision_limits']['max_revision_attempts']
        self.quality_threshold = self.quality_config['quality_thresholds']['prose_quality_minimum']
        
        # Pipeline state persistence
        self.state_file = os.path.join(base_dir, "08_Memory", "pipeline_state.json")
        self.load_pipeline_state()
    
    def load_pipeline_state(self):
        """Load pipeline state from disk for crash recovery."""
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r', encoding='utf-8') as f:
                self.pipeline_state = json.load(f)
        else:
            self.pipeline_state = {
                "last_completed_phase": None,
                "last_completed_chapter": 0,
                "concept": None,
                "total_chapters": 0,
                "timestamp": None
            }
    
    def save_pipeline_state(self):
        """Save pipeline state to disk."""
        import datetime
        self.pipeline_state["timestamp"] = datetime.datetime.now().isoformat()
        atomic_json(self.state_file, self.pipeline_state)

    async def run_ceo_intake(self, concept: str) -> dict:
        """Resolve a draft brief autonomously; reserve blocking for real obstacles."""
        print("\n--- STAGE 1: CONCEPT & INTAKE (SRV-001) ---")
        service_data = load_service("SRV-001", self.base_dir)
        system_prompt = format_system_prompt(service_data)
        system_prompt += """
        AUTONOMOUS DRAFT MODE — overrides commercial release requirements above:
        The user has authorized a local manuscript draft, not a publishing investment.
        Infer unspecified format, audience, subgenre, length, and creative details.
        The requested chapter count is intentional. A short story or novella is valid;
        do not require a novel-length word count or ask the user to confirm the format.
        Marketing, cover, pricing, and commercial positioning are advisory, not gates.
        The outline and originality differentiators are downstream planning work:
        assign them to the architect, never require an outline before intake approval.
        Do not invent missing-input dependencies for things this pipeline can create.
        Resolve routine creative conditions yourself and record your assumptions.
        Return APPROVED if the concept is actionable with those decisions. Only return
        CONDITIONAL or REJECTED for an actual unresolved obstacle to writing the draft.
        Output one JSON object with decision (APPROVED, CONDITIONAL, or REJECTED),
        rationale, assumptions (array), and planning_instructions (array).
        """
        job_path = os.path.join(self.base_dir, 'job.json')
        requested_chapters = None
        if os.path.exists(job_path):
            with open(job_path, encoding='utf-8') as stream:
                requested_chapters = json.load(stream).get('chapters')
        target = self.quality_config.get('chapter_targets', {}).get('word_count_target', 3000)
        brief = {'deliverable': 'local manuscript draft', 'requested_chapters': requested_chapters,
                 'default_words_per_chapter': target,
                 'suggested_total_words': requested_chapters * target if requested_chapters else None,
                 'length_policy': 'Use these defaults only where the user has not specified a length.'}
        self.memory.save_artifact('intake_brief.json', json.dumps(brief))

        user_prompt = f"""
        Execute an Intake Gate decision.
        gate_type: "intake"

        CONCEPT:
        {concept}

        RUNTIME BRIEF:
        {json.dumps(brief)}

        Decide whether this is actionable for autonomous draft generation.
        Make and record reasonable planning decisions instead of requesting permission.
        """
        # A resumed conditional intake should address the saved concerns directly.
        try:
            prior = parse_json(self.memory.load_artifact('ceo_intake_decision.json'))
        except (ValueError, TypeError):
            prior = {}
        if isinstance(prior, dict) and prior.get('decision') == 'CONDITIONAL':
            user_prompt += '\nResolve these previous conditions within draft mode:\n' + json.dumps(prior)
        for attempt in range(3):
            response = self.llm.execute_prompt('SRV-001', system_prompt, user_prompt)
            decision = parse_json(response)
            if not isinstance(decision, dict) or decision.get('decision') not in ('APPROVED', 'CONDITIONAL', 'REJECTED'):
                raise ValueError('Intake must return an explicit APPROVED, CONDITIONAL, or REJECTED decision.')
            self.memory.save_artifact('ceo_intake_decision.json', response)
            self.pipeline_state['ceo_intake_decision'] = decision['decision']
            self.save_pipeline_state()
            if decision['decision'] != 'CONDITIONAL':
                break
            print(f'Intake has conditions; resolving creative decisions ({attempt + 1}/3).')
            user_prompt += ('\nYour previous decision:\n' + json.dumps(decision) +
                            '\nResolve routine conditions yourself. Assign outline and differentiation work '
                            'to planning_instructions; these artifacts are produced after intake. '
                            'Return an updated decision with concrete assumptions, not another request for confirmation.')
        print(f"Intake decision: {decision['decision']}")
        return decision

    async def run_phase_1_architecture(self, concept: str):
        """SRV-002: Story Architect"""
        print("\n--- PHASE 1: STORY ARCHITECTURE (SRV-002) ---")
        service_data = load_service("SRV-002", self.base_dir)
        system_prompt = format_system_prompt(service_data)
        
        # Load the project schema to give the model the required format
        project_schema = self.memory.load_schema("project.schema.json")
        intake_brief = self.memory.load_artifact('intake_brief.json')
        intake_decision = self.memory.load_artifact('ceo_intake_decision.json')
        
        user_prompt = f"""
        Execute the Story Architecture capability for the following concept:
        CONCEPT: {concept}

        AGREED DRAFT BRIEF AND INTAKE PLANNING DECISIONS:
        {intake_brief}
        {intake_decision}

        Infer missing genre, audience, and target length from this concept.
        This is initial planning; create missing story assumptions yourself.
        Include beat_sheets: an array of acts, each with act, name, and beats.
        Each beat is exactly one chapter, with beat_id, goal, conflict, outcome.
        Include all chapters through the resolution, and a title.
        
        OUTPUT FORMAT:
        You must output the exact JSON structure defined in your Interface Contract.
        Use this schema as a guideline if needed:
        {project_schema}
        """
        
        response = self.llm.execute_prompt("SRV-002", system_prompt, user_prompt)
        self.memory.save_artifact("outline.json", response)
        
        # Extract total chapters from outline
        try:
            outline = parse_json(response)
            total_chapters = sum(len(act['beats']) for act in outline['beat_sheets'])
            if total_chapters < 1:
                raise ValueError('No chapter beats in outline.')
            self.pipeline_state["total_chapters"] = total_chapters
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError('Outline must contain beat_sheets with chapter beats.') from error
        
        self.pipeline_state["last_completed_phase"] = "phase_1"
        self.pipeline_state["concept"] = concept
        self.save_pipeline_state()
        print("Phase 1 Complete. Triggered event: OutlineCompleted")

    async def run_phase_2_psychology(self):
        """SRV-003: Character Psychologist"""
        print("\n--- PHASE 2: CHARACTER PSYCHOLOGY (SRV-003) ---")
        service_data = load_service("SRV-003", self.base_dir)
        system_prompt = format_system_prompt(service_data)
        
        outline = self.memory.load_artifact("outline.json")
        character_schema = self.memory.load_schema("character.schema.json")
        
        user_prompt = f"""
        Execute the Character Psychology Profiling capability.
        
        INPUT DEPENDENCY (outline.json):
        {outline}
        
        OUTPUT FORMAT:
        Output the full character profiles in JSON format based on:
        {character_schema}
        """
        
        response = self.llm.execute_prompt("SRV-003", system_prompt, user_prompt)
        self.memory.save_artifact("psychology.json", response)
        
        self.pipeline_state["last_completed_phase"] = "phase_2"
        self.save_pipeline_state()
        print("Phase 2 Complete. Triggered event: CharacterPsychologyComplete")

    async def run_phase_3_world(self):
        """SRV-004: World Builder"""
        print("\n--- PHASE 3: WORLD BUILDING (SRV-004) ---")
        service_data = load_service("SRV-004", self.base_dir)
        system_prompt = format_system_prompt(service_data)
        
        outline = self.memory.load_artifact("outline.json")
        
        user_prompt = f"""
        Execute the World Architecture capability.
        
        INPUT DEPENDENCY (outline.json):
        {outline}
        
        OUTPUT FORMAT:
        Output the story_bible.json containing locations and rules.
        """
        
        response = self.llm.execute_prompt("SRV-004", system_prompt, user_prompt)
        self.memory.save_artifact("story_bible.json", response)
        
        self.pipeline_state["last_completed_phase"] = "phase_3"
        self.save_pipeline_state()
        print("Phase 3 Complete. Triggered event: WorldPlanningCompleted")

    async def run_planning_phase(self, concept: str):
        """Run phases 1-3 with parallelism where possible."""
        # Phase 1 must complete first
        await self.run_phase_1_architecture(concept)
        # Then run 2 and 3 in parallel
        await asyncio.gather(
            self.run_phase_2_psychology(),
            self.run_phase_3_world()
        )

    def run_voice_calibration(self):
        """SRV-028: Voice Calibrator - run after planning, before drafting."""
        print("\n--- PHASE: VOICE CALIBRATION (SRV-028) ---")
        service_data = load_service("SRV-028", self.base_dir)
        system_prompt = format_system_prompt(service_data)
        
        outline = self.memory.load_artifact("outline.json")
        project_schema = self.memory.load_schema("project.schema.json")
        
        user_prompt = f"""
        Generate a 500-word prose sample that locks the book's voice fingerprint.
        This is a calibration document, NOT part of the manuscript.
        
        The sample must establish:
        - Sentence length profile (short/punchy, long/accumulative, varied)
        - Relationship between interiority and action
        - Adjective density and type
        - Characteristic metaphor domain
        - Narrative distance
        - Tonal register
        
        OUTLINE:
        {outline}
        
        PROJECT SCHEMA:
        {project_schema}
        """
        
        response = self.llm.execute_prompt("SRV-028", system_prompt, user_prompt)
        
        # Save voice sample
        voice_file = os.path.join(self.base_dir, "08_Memory", "voice_sample.md")
        with open(voice_file, 'w', encoding='utf-8') as f:
            f.write(response)
        
        print("Voice Calibration Complete. Saved to 08_Memory/voice_sample.md")

    async def run_chapter_draft(self, chapter_number: int):
        """SRV-005: Literary Author - draft a single chapter with full context."""
        print(f"\n--- CHAPTER {chapter_number}: PROSE DRAFTING (SRV-005) ---")
        service_data = load_service("SRV-005", self.base_dir)
        system_prompt = format_system_prompt(service_data)
        
        # Build full context window
        context = self.context_builder.build(chapter_number)
        
        # Get chapter-specific data from outline
        chapter_roadmap = context.get("current_chapter_roadmap", {})
        
        # Build scene brief
        scene_brief = build_scene_brief(chapter_roadmap, context)
        
        outline = self.memory.load_artifact("outline.json")
        psychology = self.memory.load_artifact("psychology.json")
        story_bible = self.memory.load_artifact("story_bible.json")
        chapter_schema = self.memory.load_schema("chapter.schema.json")
        
        user_prompt = f"""
        SCENE BRIEF (mandatory pre-write context):
        {json.dumps(scene_brief, indent=2)}
        
        Your first task: confirm you have absorbed this brief by stating in one sentence what changes in this scene and why it matters to the larger story.
        Your second task: write the scene.
        
        FULL CONTEXT:
        Outline: {outline}
        Characters: {psychology}
        World Rules: {json.dumps(context.get('context_fragment', {}), indent=2)}
        Previous Chapter Tail (500 words): {context.get('previous_chapter_tail', '')}
        Next Chapter Roadmap: {json.dumps(context.get('next_chapter_roadmap', {}), indent=2)}
        Voice Sample: {context.get('voice_sample', '')}
        Continuity Flags: {json.dumps(context.get('continuity_flags', []), indent=2)}
        Active Critique Notes: {json.dumps(context.get('active_critique_notes', []), indent=2)}
        Required Payoffs: {json.dumps(context.get('required_payoffs', []), indent=2)}
        
        TASK:
        Write the prose for Chapter {chapter_number}. Follow the Sensory Writing Protocol.
        Output ONLY the JSON representation of the chapter according to:
        {chapter_schema}
        """
        
        response = self.llm.execute_prompt("SRV-005", system_prompt, user_prompt)
        self.memory.save_artifact(f"chapter_{chapter_number:02d}.json", response)
        
        # Canon is extracted only after the chapter passes review and copy editing.
        
        print(f"Chapter {chapter_number} Draft Complete. Triggered event: DraftCompleted")
        return response

    async def run_voice_variation(self, chapter_number: int):
        """SRV-027: Voice Variation Engine - mandatory post-draft pass."""
        print(f"\n--- CHAPTER {chapter_number}: VOICE VARIATION (SRV-027) ---")
        service_data = load_service("SRV-027", self.base_dir)
        system_prompt = format_system_prompt(service_data)
        
        raw_chapter = self.memory.load_artifact(f"chapter_{chapter_number:02d}.json")
        voice_sample = self.memory.load_artifact("voice_sample.md")
        
        # Override temperature for SRV-027 (0.9)
        user_prompt = f"""
        Execute all five phases of the Variation Protocol on the following prose.
        
        VOICE REFERENCE SAMPLE (maintain this fingerprint):
        {voice_sample}
        
        CHAPTER PROSE TO PROCESS:
        {raw_chapter}
        
        Apply in sequence:
        Phase 1: Rhythmic Audit — flag homogeneous sentence sequences
        Phase 2: Variation Injection — apply transformations to flagged sequences
        Phase 3: Adjective Chain Surgery — cut to single most specific adjective
        Phase 4: Atmospheric Budget Enforcement — max 1 descriptor per 500 words
        Phase 5: Specificity Injection — replace generic descriptors with character-grounded details
        
        Output one chapter JSON object, preserving all fields and containing
        the complete revised prose in prose_content; add change_log as a field.
        """
        
        # Note: Temperature 0.9 for SRV-027 would need model routing fix (H4)
        response = self.llm.execute_prompt("SRV-027", system_prompt, user_prompt)
        self.memory.save_artifact(f"chapter_{chapter_number:02d}_varied.json", response)
        print(f"Phase 4b Complete. Voice variation applied to Chapter {chapter_number}.")
        return response

    async def run_continuity_check(self, chapter_number: int):
        """SRV-016: Continuity Editor - check chapter for consistency."""
        print(f"\n--- CHAPTER {chapter_number}: CONTINUITY CHECK (SRV-016) ---")
        service_data = load_service("SRV-016", self.base_dir)
        system_prompt = format_system_prompt(service_data)
        
        chapter_data = self.memory.load_artifact(f"chapter_{chapter_number:02d}_varied.json")
        story_bible = self.memory.load_artifact("story_bible.json")
        
        user_prompt = f"""
        Check the following chapter for continuity against the Story Bible.
        
        CHAPTER:
        {chapter_data}
        
        STORY BIBLE:
        {story_bible}
        
        Output JSON with:
        - score (0-10)
        - violations: array of {{type, location, established_fact, contradiction, severity, resolution_options}}
        - open_flags: array of flags for future chapters
        - updated_bible_fragment: new facts to merge into story bible
        """
        
        response = self.llm.execute_prompt("SRV-016", system_prompt, user_prompt)
        
        try:
            report = parse_json(response)
            self.memory.save_artifact(f"continuity_report_chapter_{chapter_number:02d}.json", response)
            
            # Do not commit facts from an unapproved draft to canon.
            
            return report
        except:
            print("Warning: Continuity check returned invalid JSON")
            return {"score": 0, "violations": [], "open_flags": []}

    async def run_developmental_edit(self, chapter_number: int) -> dict:
        """SRV-007: Developmental Editor — Stage 4 blind review (WF-001).
        Runs as an isolated subagent: sees only the chapter + outline/story bible,
        never SRV-016's continuity notes and never its own prior verdicts, so its
        read is independent signal rather than an echo of the drafting pass."""
        print(f"\n--- CHAPTER {chapter_number}: DEVELOPMENTAL EDIT (SRV-007) ---")
        service_data = load_service("SRV-007", self.base_dir)
        system_prompt = format_system_prompt(service_data)

        chapter_data = self.memory.load_artifact(f"chapter_{chapter_number:02d}_varied.json")
        outline = self.memory.load_artifact("outline.json")
        story_bible = self.memory.load_artifact("story_bible.json")

        user_prompt = f"""
        Perform a developmental edit on this chapter per your Evaluation Framework.

        CHAPTER:
        {chapter_data}

        APPROVED OUTLINE (comparison baseline — did the author follow the beat sheet?):
        {outline}

        STORY BIBLE (character arcs, world rules):
        {story_bible}

        Output JSON with:
        - score (0-10)
        - editorial_letter (summary assessment)
        - scene_level_notes: array of {{location, issue, severity}}
        - priority_revision_list: array of strings, each with a concrete direction for revision
        """

        response = self.llm.execute_prompt("SRV-007", system_prompt, user_prompt)

        try:
            report = parse_json(response)
            self.memory.save_artifact(f"dev_edit_report_chapter_{chapter_number:02d}.json", response)
            return report
        except Exception:
            print("Warning: Developmental edit returned invalid JSON")
            self.memory.save_text_artifact(f"dev_edit_report_chapter_{chapter_number:02d}.raw.md", response)
            return {"score": 0, "priority_revision_list": []}

    async def run_copy_edit(self, chapter_number: int) -> str:
        """SRV-008: Copy Editor — Stage 5 (WF-001). Only runs once a chapter is
        APPROVED (dev edit + continuity + QA all passed). Precision only —
        per its own Interface Contract it must not change meaning, only correct it."""
        print(f"\n--- CHAPTER {chapter_number}: COPY EDIT (SRV-008) ---")
        service_data = load_service("SRV-008", self.base_dir)
        system_prompt = format_system_prompt(service_data)

        chapter_data = self.memory.load_artifact(f"chapter_{chapter_number:02d}_varied.json")

        user_prompt = f"""
        Copy edit this APPROVED chapter. Grammar, mechanics, consistency, and
        voice-preserving polish only — do not alter plot, dialogue meaning, or
        structure. Flag anything you're uncertain about instead of guessing.

        CHAPTER:
        {chapter_data}

        Output a single corrected chapter JSON object with prose_content.
        Include corrections_log and query_list as additional JSON fields.
        """

        response = self.llm.execute_prompt("SRV-008", system_prompt, user_prompt)
        # Copy-edited prose plus logs — this is mixed content (JSON + logs), so
        # store as text rather than forcing strict JSON validation.
        self.memory.save_artifact(f"chapter_{chapter_number:02d}.json", response)
        print(f"Copy edit complete for Chapter {chapter_number}.")
        return response

    async def update_story_bible(self, bible_fragment: dict):
        """Route story bible updates through SRV-009."""
        print("\n--- STORY BIBLE UPDATE (SRV-009) ---")
        service_data = load_service("SRV-009", self.base_dir)
        system_prompt = format_system_prompt(service_data)
        
        current_bible = self.memory.load_artifact("story_bible.json")
        
        user_prompt = f"""
        Merge the following updates into the Story Bible.
        
        CURRENT BIBLE:
        {current_bible}
        
        UPDATES:
        {json.dumps(bible_fragment, indent=2)}
        
        Output the complete updated story_bible.json
        """
        
        response = self.llm.execute_prompt("SRV-009", system_prompt, user_prompt)
        self.memory.save_artifact("story_bible.json", response)
        print("Story Bible Updated.")

    async def run_qa_check(self, chapter_number: int):
        """SRV-010: QA Director - quality check with programmatic metrics."""
        print(f"\n--- CHAPTER {chapter_number}: QA CHECK (SRV-010) ---")
        
        # First run ProseAnalyzer for objective metrics
        from prose_analyzer import ProseAnalyzer
        analyzer = ProseAnalyzer()
        
        chapter_text = self.memory.load_artifact(f"chapter_{chapter_number:02d}_varied.json")
        previous_chapters = []
        for i in range(1, chapter_number):
            prev = self.memory.load_artifact(f"chapter_{i:02d}_varied.json")
            previous_chapters.append(prev)
        
        chapter_prose = parse_json(chapter_text)['prose_content']
        previous_prose = [parse_json(chapter)['prose_content'] for chapter in previous_chapters]
        metrics = analyzer.run_full_analysis(chapter_prose, previous_prose)
        
        # Then run SRV-010 with the metrics
        service_data = load_service("SRV-010", self.base_dir)
        system_prompt = format_system_prompt(service_data)
        
        quality_yaml = yaml.safe_dump(self.quality_config)
        
        user_prompt = f"""
        QA Review for Chapter {chapter_number}.

        CHAPTER:
        {chapter_prose}
        
        PROGRAMMATIC METRICS:
        {json.dumps(metrics, indent=2)}
        
        QUALITY THRESHOLDS:
        {quality_yaml}
        
        Return JSON with score (number 0-10), decision (APPROVED or REJECTED),
        and defects (array of specific revision instructions).
        """
        
        response = self.llm.execute_prompt("SRV-010", system_prompt, user_prompt)
        self.memory.save_artifact(f'qa_chapter_{chapter_number:02d}.json', response)
        return response

    async def write_and_validate_chapter(self, chapter_number: int):
        """Write chapter with revision loop (C2 Part B)."""
        for attempt in range(self.max_revision_attempts):
            print(f"\n=== Chapter {chapter_number}, Attempt {attempt + 1}/{self.max_revision_attempts} ===")
            
            # Draft
            if attempt == 0:
                await self.run_chapter_draft(chapter_number)
            
            # Voice variation (C4)
            if attempt == 0:
                await self.run_voice_variation(chapter_number)
            
            # Dialogue audit and rewrite (A2)
            # First run SRV-013 Dialogue Master audit
            await self.run_dialogue_audit(chapter_number)
            # Then rewrite based on audit
            await self.run_dialogue_rewrite(chapter_number)
            
            # Stage 4 blind fan-out (WF-001): Developmental Edit + Continuity Check
            # run as independent, isolated subagent calls, concurrently. Neither
            # sees the other's notes — that's what makes this two signals instead
            # of one agent agreeing with itself twice.
            dev_edit_report, continuity_report = await asyncio.gather(
                self.run_developmental_edit(chapter_number),
                self.run_continuity_check(chapter_number)
            )
            
            # QA check (programmatic metrics + SRV-010)
            qa_result = parse_json(await self.run_qa_check(chapter_number))
            
            # Check scores — ALL gates must pass, per system-prompt.md Directive 5
            continuity_score = continuity_report.get("score", 0)
            dev_edit_score = dev_edit_report.get("score", 0)
            
            if (continuity_score >= self.quality_config['quality_thresholds']['continuity_score_minimum']
                    and dev_edit_score >= self.quality_threshold
                    and qa_result.get('decision') == 'APPROVED'
                    and qa_result.get('score', 0) >= self.quality_threshold):
                print(f"Chapter {chapter_number} PASSED (continuity: {continuity_score}, dev_edit: {dev_edit_score})")
                
                # Run Reader Proxy (A5) after QA passes
                await self.run_reader_proxy(chapter_number)
                
                # Stage 5 (WF-001): Copy Edit — only runs on an APPROVED chapter
                await self.run_copy_edit(chapter_number)
                
                return True
            
            print(f"Chapter {chapter_number} FAILED (continuity: {continuity_score}, dev_edit: {dev_edit_score}, threshold: {self.quality_threshold})")
            
            if attempt < self.max_revision_attempts - 1:
                # Revision with BOTH reports merged — the author needs to see everything
                # that's wrong at once, not fix continuity and re-break structure
                merged_report = dict(continuity_report)
                merged_report["developmental_notes"] = dev_edit_report.get("priority_revision_list", [])
                merged_report['qa_notes'] = qa_result
                await self.run_chapter_revision(chapter_number, merged_report)
        
        # Escalation after max attempts
        print(f"ESCALATION: Chapter {chapter_number} failed {self.max_revision_attempts} times")
        self.emit_event("EscalationRequired", {"chapter": chapter_number})
        return False

    async def run_dialogue_audit(self, chapter_number: int):
        """Run SRV-013 Dialogue Master audit."""
        print(f"\n--- CHAPTER {chapter_number}: DIALOGUE AUDIT (SRV-013) ---")
        service_data = load_service("SRV-013", self.base_dir)
        system_prompt = format_system_prompt(service_data)
        
        chapter = self.memory.load_artifact(f"chapter_{chapter_number:02d}_varied.json")
        psychology = self.memory.load_artifact("psychology.json")
        
        user_prompt = f"""
        Audit the dialogue in this chapter for subtext, distinctiveness, and narrative purpose.
        
        CHAPTER:
        {chapter}
        
        CHARACTER PSYCHOLOGY (speech_style for each character):
        {psychology}
        
        Flag:
        - Lines that are "on the nose" (characters saying exactly what they mean)
        - Characters whose voices are indistinguishable
        - Dialogue that exists only to transmit information
        - Missing subtext opportunities
        
        Output JSON: {{"flagged_lines": [...], "rewrite_proposals": [...], "differentiation_score": 0.0}}
        """
        
        response = self.llm.execute_prompt("SRV-013", system_prompt, user_prompt)
        audit_file = os.path.join(self.base_dir, "08_Memory", f"dialogue_audit_chapter_{chapter_number:02d}.json")
        with open(audit_file, 'w', encoding='utf-8') as f:
            f.write(response)
        print(f"Dialogue audit complete for Chapter {chapter_number}.")
        return response

    async def run_chapter_revision(self, chapter_number: int, continuity_report: dict):
        """Revise chapter based on continuity report."""
        print(f"\n--- CHAPTER {chapter_number}: REVISION ---")
        service_data = load_service("SRV-005", self.base_dir)
        system_prompt = format_system_prompt(service_data)
        
        chapter_data = self.memory.load_artifact(f"chapter_{chapter_number:02d}_varied.json")
        
        user_prompt = f"""
        REVISE this chapter based on the continuity report.
        
        CONTINUITY REPORT:
        {json.dumps(continuity_report, indent=2)}
        
        CURRENT CHAPTER:
        {chapter_data}
        
        Fix all violations. Maintain the story events but correct continuity errors.
        Output the revised chapter JSON.
        """
        
        response = self.llm.execute_prompt("SRV-005", system_prompt, user_prompt)
        self.memory.save_artifact(f"chapter_{chapter_number:02d}_varied.json", response)
        
        # Revision remains provisional until approval.

    async def post_chapter_extraction(self, chapter_number: int):
        """Commit facts from the final copy-edited chapter only."""
        chapter = self.memory.load_artifact(f"chapter_{chapter_number:02d}.json")
        prompt = format_system_prompt(load_service("SRV-009", self.base_dir))
        response = self.llm.execute_prompt("SRV-009", prompt,
            "Extract facts from the approved chapter below. Return ONE JSON object "
            "with summary (object: chapter, events, character_state_changes, new_facts_established, "
            "open_threads, information_gap, foreshadowing_planted) and bible_updates (object). "
            "Each foreshadowing seed has text and intended_payoff_chapter.\n" + chapter)
        result = parse_json(response)
        if not isinstance(result.get('summary'), dict) or not isinstance(result.get('bible_updates'), dict):
            raise ValueError('Extraction requires summary and bible_updates objects.')
        self.memory.save_chapter_summary(chapter_number, result['summary'])
        await self.update_story_bible(result['bible_updates'])
        await self.update_foreshadowing_registry(chapter_number, result['summary'])

    async def update_foreshadowing_registry(self, chapter_number: int, summary: dict):
        """Update the foreshadowing registry with new seeds and resolved payoffs."""
        registry_file = os.path.join(self.base_dir, "08_Memory", "foreshadowing_registry.json")
        
        if os.path.exists(registry_file):
            with open(registry_file, 'r', encoding='utf-8') as f:
                registry = json.load(f)
        else:
            registry = {"seeds": []}
        
        # Add new foreshadowing seeds
        for seed in summary.get("foreshadowing_planted", []):
            if any(existing.get('chapter_planted') == chapter_number and existing.get('text') == seed.get('text', '')
                   for existing in registry['seeds']):
                continue
            seed_id = f"FS-{len(registry['seeds']) + 1:03d}"
            registry["seeds"].append({
                "id": seed_id,
                "chapter_planted": chapter_number,
                "text": seed.get("text", ""),
                "intended_payoff_chapter": seed.get("intended_payoff_chapter"),
                "payoff_description": f"Payoff for: {seed.get('text', '')}",
                "resolved": False,
                "resolution_chapter": None
            })
        
        # Mark payoffs as resolved if they occur in this chapter
        for seed in registry["seeds"]:
            if seed.get("intended_payoff_chapter") == chapter_number and not seed.get("resolved"):
                seed["resolved"] = True
                seed["resolution_chapter"] = chapter_number
        
        atomic_json(registry_file, registry)
        
        print(f"Foreshadowing registry updated: {len(registry['seeds'])} total seeds")

    async def run_rolling_critique(self, chapter_number: int):
        """H3: SRV-026 rolling critique at checkpoints 3, 6, 9, 12, 15."""
        checkpoints = [3, 6, 9, 12, 15]
        if chapter_number not in checkpoints:
            return
        
        print(f"\n--- ROLLING CRITIQUE (SRV-026) at Chapter {chapter_number} ---")
        service_data = load_service("SRV-026", self.base_dir)
        system_prompt = format_system_prompt(service_data)
        
        chapters_so_far = self.memory.load_chapters_up_to(chapter_number)
        outline = self.memory.load_artifact("outline.json")
        
        user_prompt = f"""
        Read the following {chapter_number} chapters of the manuscript in progress.
        
        CHAPTERS:
        {json.dumps(chapters_so_far, indent=2)}
        
        OUTLINE (intended direction):
        {outline}
        
        Produce your Critical Framework evaluation across all six dimensions.
        Focus especially on: what is the Signature Failure emerging in this manuscript?
        What is the one recurring weakness that, if uncorrected, will define the floor of this book?
        End with Three Priority Actions the author must apply immediately to the next chapters.
        
        Output JSON with: critical_report, signature_failure, priority_actions
        """
        
        response = self.llm.execute_prompt("SRV-026", system_prompt, user_prompt)
        self.memory.save_artifact(f"critique_checkpoint_{chapter_number}.json", response)
        
        # Extract priority actions for future chapters
        try:
            critique = json.loads(response)
            self.active_critique_notes = critique.get("priority_actions", [])
        except:
            pass
        
        print(f"Rolling critique complete. Priority actions: {len(self.active_critique_notes)}")

    def emit_event(self, event_type: str, data: dict):
        """Event bus emission for pipeline state changes."""
        event_file = os.path.join(self.base_dir, "08_Memory", f"event_{event_type.lower()}.json")
        event = {
            "type": event_type,
            "data": data,
            "timestamp": __import__("datetime").datetime.now().isoformat()
        }
        with open(event_file, 'w', encoding='utf-8') as f:
            json.dump(event, f, indent=2)
        print(f"Event emitted: {event_type}")

    async def run_drafting_phase(self, total_chapters: int = None):
        """Run the full drafting phase with all chapters."""
        if total_chapters is None:
            total_chapters = self.pipeline_state.get("total_chapters", 15)
        
        start_chapter = self.pipeline_state.get("last_completed_chapter", 0) + 1
        
        for chapter_num in range(start_chapter, total_chapters + 1):
            # Write and validate chapter with revision loop
            success = await self.write_and_validate_chapter(chapter_num)
            
            if success:
                self.pipeline_state["last_completed_chapter"] = chapter_num
                self.pipeline_state["last_completed_phase"] = f"chapter_{chapter_num}"
                self.save_pipeline_state()
                
                # Rolling critique checkpoint
                await self.run_rolling_critique(chapter_num)
            else:
                # Escalation - pause for human review
                print(f"\nPIPELINE PAUSED: Chapter {chapter_num} requires human review")
                break

    async def run_emotional_compliance_check(self, chapter_number: int):
        """A4: Check if chapter emotional intensity matches planned arc."""
        # This would need the pacing graph from SRV-002
        # For now, placeholder
        pass

    async def run_dialogue_rewrite(self, chapter_number: int):
        """A2: Targeted dialogue rewrite based on SRV-013 audit."""
        print(f"\n--- CHAPTER {chapter_number}: DIALOGUE REWRITE (SRV-005) ---")
        service_data = load_service("SRV-005", self.base_dir)
        system_prompt = format_system_prompt(service_data)
        
        chapter = self.memory.load_artifact(f"chapter_{chapter_number:02d}_varied.json")
        
        # Load dialogue audit report
        audit_file = os.path.join(self.base_dir, "08_Memory", f"dialogue_audit_chapter_{chapter_number:02d}.json")
        if not os.path.exists(audit_file):
            print("No dialogue audit found, skipping rewrite.")
            return
        
        with open(audit_file, 'r', encoding='utf-8') as f:
            dialogue_audit = json.load(f)
        
        user_prompt = f"""
        TASK: Dialogue rewrite only. Do not touch the prose descriptions.
        
        DIALOGUE AUDIT FINDINGS:
        {json.dumps(dialogue_audit, indent=2)}
        
        CHAPTER (rewrite only the flagged dialogue lines):
        {chapter}
        
        For each flagged line:
        1. State what the subtext is (what the character actually means)
        2. Write the surface dialogue that carries the subtext without stating it
        3. Add a beat (physical action) that reinforces the subtext
        
        Return the full chapter with only the dialogue sections replaced.
        """
        
        revised = self.llm.execute_prompt("SRV-005", system_prompt, user_prompt)
        self.memory.save_artifact(f"chapter_{chapter_number:02d}_varied.json", revised)
        print(f"Dialogue rewrite complete for Chapter {chapter_number}.")

    async def run_opening_specialist(self):
        """A3: SRV-029 Opening Specialist - run after Chapter 1 QA approval."""
        print("\n--- OPENING SPECIALIST (SRV-029) ---")
        service_data = load_service("SRV-029", self.base_dir)
        system_prompt = format_system_prompt(service_data)
        
        chapter_1 = self.memory.load_artifact("chapter_01_varied.json")
        voice_sample = self.memory.load_artifact("voice_sample.md")
        outline = self.memory.load_artifact("outline.json")
        project_schema = self.memory.load_schema("project.schema.json")
        
        user_prompt = f"""
        Generate three distinct opening alternatives for Chapter 1.
        
        CURRENT CHAPTER 1 OPENING:
        {chapter_1}
        
        VOICE CALIBRATION SAMPLE:
        {voice_sample}
        
        OUTLINE (genre, pacing, inciting incident):
        {outline}
        
        PROJECT SCHEMA (POV, target audience):
        {project_schema}
        
        Produce three options:
        Option A - In Medias Res (action-first)
        Option B - Voice-First (character-first)  
        Option C - World-First (concept-first)
        
        Each option: 250 words max, with evaluation.
        Output JSON with options array and recommendation.
        """
        
        response = self.llm.execute_prompt("SRV-029", system_prompt, user_prompt)
        self.memory.save_artifact("opening_options.json", response)
        print("Opening Specialist complete. Options saved to opening_options.json.")
        return response

    async def run_reader_proxy(self, chapter_number: int):
        """A5: SRV-030 Reader Proxy - naive readability audit."""
        print(f"\n--- CHAPTER {chapter_number}: READER PROXY (SRV-030) ---")
        service_data = load_service("SRV-030", self.base_dir)
        system_prompt = format_system_prompt(service_data)
        
        chapter = self.memory.load_artifact(f"chapter_{chapter_number:02d}_varied.json")
        
        # Get previous chapter summaries for context
        prev_summaries = self.memory.load_chapter_summaries_up_to(chapter_number - 1)
        
        user_prompt = f"""
        Read this chapter as a smart but non-expert reader who has read the previous chapters.
        You know what happened before, but you do NOT have the outline, character bible, or author's intentions.
        
        PREVIOUS CHAPTER SUMMARIES:
        {json.dumps(prev_summaries, indent=2)}
        
        CURRENT CHAPTER:
        {chapter}
        
        Flag specifically:
        1. CONFUSION POINTS - where you don't have enough info to understand what's happening
        2. BOREDOM POINTS - scenes where nothing changes, urge to skim
        3. LOST TRACK - unsure who's speaking, where scene is set, physical reality
        4. MOTIVATION GAPS - character action doesn't make sense given what YOU know
        5. ASSUMPTION FAILURES - author assumed you remember a detail from chapters ago
        
        Output JSON with all five categories, specific locations, severity.
        """
        
        response = self.llm.execute_prompt("SRV-030", system_prompt, user_prompt)
        self.memory.save_artifact(f"reader_proxy_chapter_{chapter_number:02d}.json", response)
        print(f"Reader Proxy complete for Chapter {chapter_number}.")
        return response

    async def run_publishing_consultation(self):
        """Generate metadata from the outline and approved chapter summaries."""
        summaries = self.memory.load_chapter_summaries_up_to(self.pipeline_state['total_chapters'])
        response = self.llm.execute_prompt('SRV-019',
            format_system_prompt(load_service('SRV-019', self.base_dir)),
            'Return one JSON object containing title (string), blurb (string), keywords (array). '
            'Base it on this outline and chapter summaries.\n' +
            self.memory.load_artifact('outline.json') + '\n' + json.dumps(summaries))
        metadata = parse_json(response)
        if not isinstance(metadata.get('title'), str) or not metadata['title'].strip():
            raise ValueError('Metadata requires a title.')
        self.memory.save_artifact('metadata.json', response)

    async def run_formatting(self):
        """Assemble saved final prose without an LLM rewriting or truncating it."""
        count = self.pipeline_state.get('total_chapters', 0)
        if count < 1 or self.pipeline_state.get('last_completed_chapter', 0) != count:
            raise ValueError('Cannot format an incomplete manuscript.')
        metadata = parse_json(self.memory.load_artifact('metadata.json'))
        parts = ['# ' + metadata['title']]
        for number in range(1, count + 1):
            chapter = parse_json(self.memory.load_artifact(f'chapter_{number:02d}.json'))
            prose = chapter.get('prose_content')
            if not isinstance(prose, str) or not prose.strip():
                raise ValueError(f'Chapter {number} has no prose.')
            parts.append(f'## Chapter {number}: {chapter.get("title", "")}\n\n{prose.strip()}')
        manuscript = '\n\n'.join(parts) + '\n'
        self.memory.save_text_artifact('manuscript.md', manuscript)
        self.memory.save_artifact('delivery.json', json.dumps({
            'chapters': count, 'word_count': sum(len(parse_json(self.memory.load_artifact(
                f'chapter_{n:02d}.json'))['prose_content'].split()) for n in range(1, count + 1)),
            'manuscript': 'manuscript.md', 'status': 'draft_complete',
        }))
        return manuscript

    async def run_ceo_signoff(self) -> dict:
        """SRV-001: CEO — Stage 6 final gate (WF-001). The pipeline is not
        'done' until this passes; this is the only other point besides Stage 1
        where the CEO is authoritative rather than advisory."""
        print("\n--- STAGE 6: CEO FINAL SIGN-OFF (SRV-001) ---")
        service_data = load_service("SRV-001", self.base_dir)
        system_prompt = format_system_prompt(service_data)

        metadata = self.memory.load_artifact("metadata.json")
        total_chapters = self.pipeline_state.get("total_chapters", 0)

        user_prompt = f"""
        Execute a Final Sign-off Gate decision.
        gate_type: "signoff"

        Manuscript is complete: {total_chapters} chapters, all previously reported
        as APPROVED through Stage 4/5.

        METADATA / BLURB:
        {metadata}

        Confirm the manuscript is ready for release per your Quality Checklist,
        or reject with specific conditions.
        Output your decision per your Interface Contract.
        """

        response = self.llm.execute_prompt("SRV-001", system_prompt, user_prompt)
        self.memory.save_artifact("ceo_signoff_decision.json", response)

        try:
            decision = json.loads(response.strip().strip("`").replace("json\n", "", 1))
        except Exception:
            raise ValueError('Invalid final decision; cannot approve.')

        self.pipeline_state["ceo_signoff_decision"] = decision.get("decision", "UNKNOWN")
        self.save_pipeline_state()
        print(f"Stage 6 Complete. CEO decision: {decision.get('decision', 'UNKNOWN')}")
        return decision

    async def run_publication_phase(self):
        """Stage 6 in full: Publishing Consultation -> Formatting -> CEO Sign-off.
        Sequential by necessity (SRV-020 depends on SRV-019's metadata.json;
        SRV-001 needs the finished manuscript+metadata to sign off)."""
        await self.run_publishing_consultation()
        await self.run_formatting()
        decision = await self.run_ceo_signoff()
        if decision.get("decision") != "APPROVED":
            print(f"PIPELINE HALTED at Stage 6 (CEO REJECTED): {decision.get('rationale', '')}")
            return False
        print("\n*** STAGE 6 COMPLETE — MANUSCRIPT SIGNED OFF ***")
        return True

    # Backward compatibility
    def run_phase_4_drafting(self):
        """Legacy method - runs Chapter 1 only."""
        print("\n--- PHASE 4: PROSE DRAFTING (SRV-005) - LEGACY ---")
        # This runs the old single-chapter flow for backward compat
        return asyncio.run(self.run_chapter_draft(1))
