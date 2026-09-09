import os
import json
from memory_manager import MemoryManager

class ContextBuilder:
    """Assembles a sliding context window before every SRV-005 call."""
    
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.memory = MemoryManager(base_dir)
        self.outline = None
    
    def load_outline(self):
        """Load and cache the outline."""
        if self.outline is None:
            outline_str = self.memory.load_artifact("outline.json")
            try:
                self.outline = json.loads(outline_str)
            except:
                self.outline = {}
        return self.outline
    
    def get_chapter_roadmap(self, chapter_number: int) -> dict:
        """Extract the scene objective and roadmap for a specific chapter from outline.json."""
        outline = self.load_outline()
        beat_sheets = outline.get("beat_sheets", [])
        
        # Find which act/chapter this belongs to
        chapter_count = 0
        for act in beat_sheets:
            beats = act.get("beats", [])
            for beat in beats:
                chapter_count += 1
                if chapter_count == chapter_number:
                    return {
                        "act": act.get("act"),
                        "act_name": act.get("name"),
                        "beat_id": beat.get("beat_id"),
                        "goal": beat.get("goal"),
                        "conflict": beat.get("conflict"),
                        "outcome": beat.get("outcome"),
                    }
        return {}
    
    def get_next_chapter_roadmap(self, chapter_number: int) -> dict:
        """Get the next chapter's roadmap for foreshadowing setup."""
        return self.get_chapter_roadmap(chapter_number + 1)
    
    def get_continuity_flags(self, chapter_number: int) -> list:
        """Get open continuity flags from SRV-016's last report."""
        # Load the latest continuity report
        # Check for continuity report from previous chapter
        if chapter_number > 1:
            report_file = os.path.join(self.memory.memory_dir, f"continuity_report_chapter_{chapter_number-1:02d}.json")
            if os.path.exists(report_file):
                with open(report_file, 'r', encoding='utf-8') as f:
                    report = json.load(f)
                    return report.get("open_flags", [])
        return []
    
    def get_voice_sample(self) -> str:
        """Load the voice sample from 08_Memory/voice_sample.md."""
        voice_file = os.path.join(self.memory.memory_dir, "voice_sample.md")
        if os.path.exists(voice_file):
            with open(voice_file, 'r', encoding='utf-8') as f:
                return f.read()
        return ""
    
    def get_chapter_context_fragment(self, chapter_number: int) -> dict:
        """Get relevant story bible fragment for this chapter."""
        return self.memory.get_context_fragment(chapter_number)
    
    def build(self, chapter_number: int) -> dict:
        """Build the complete context window for a chapter."""
        
        # 1. Previous chapter tail (500 words verbatim)
        prev_chapter_tail = ""
        if chapter_number > 1:
            prev_chapter_tail = self.memory.get_chapter_tail(chapter_number - 1, word_count=500)
        
        # 2. Current chapter's scene objective from outline.json
        current_roadmap = self.get_chapter_roadmap(chapter_number)
        
        # 3. Next chapter's scene objective (for foreshadowing)
        next_roadmap = self.get_next_chapter_roadmap(chapter_number)
        
        # 4. Relevant character states from story_bible.json
        context_fragment = self.get_chapter_context_fragment(chapter_number)
        
        # 5. Open continuity flags from SRV-016
        continuity_flags = self.get_continuity_flags(chapter_number)
        
        # 6. Voice sample
        voice_sample = self.get_voice_sample()
        
        # 6b. Active critique notes from rolling critique checkpoints
        active_critique = self.get_active_critique_notes(chapter_number)
        
        # 6c. Required payoffs from foreshadowing registry
        required_payoffs = self.get_required_payoffs(chapter_number)
        
        return {
            "previous_chapter_tail": prev_chapter_tail,
            "current_chapter_roadmap": current_roadmap,
            "next_chapter_roadmap": next_roadmap,
            "context_fragment": context_fragment,
            "continuity_flags": continuity_flags,
            "voice_sample": voice_sample,
            "active_critique_notes": active_critique,
            "required_payoffs": required_payoffs,
            "chapter_number": chapter_number
        }
    
    def get_active_critique_notes(self, chapter_number: int) -> list:
        """Get active critique notes from rolling SRV-026 checkpoints."""
        notes = []
        # Check for critique checkpoints at chapters 3, 6, 9, 12, 15
        checkpoints = [3, 6, 9, 12, 15]
        for cp in checkpoints:
            if cp < chapter_number:
                critique_file = os.path.join(self.memory.memory_dir, f"critique_checkpoint_{cp}.json")
                if os.path.exists(critique_file):
                    with open(critique_file, 'r', encoding='utf-8') as f:
                        critique = json.load(f)
                        # Extract priority actions
                        if isinstance(critique, dict) and "priority_actions" in critique:
                            notes.extend(critique["priority_actions"])
                        elif isinstance(critique, str):
                            # Parse from text if needed
                            pass
        return notes
    
    def get_required_payoffs(self, chapter_number: int) -> list:
        """Get foreshadowing seeds that should pay off in this chapter."""
        registry_file = os.path.join(self.memory.memory_dir, "foreshadowing_registry.json")
        if not os.path.exists(registry_file):
            return []
        
        with open(registry_file, 'r', encoding='utf-8') as f:
            registry = json.load(f)
        
        payoffs = []
        for seed in registry.get("seeds", []):
            if seed.get("intended_payoff_chapter") == chapter_number and not seed.get("resolved", False):
                payoffs.append({
                    "id": seed.get("id"),
                    "text": seed.get("text"),
                    "description": seed.get("payoff_description"),
                    "planted_chapter": seed.get("chapter_planted")
                })
        return payoffs


def build_scene_brief(chapter_data: dict, context: dict) -> dict:
    """Build a structured scene brief from chapter roadmap and context."""
    return {
        "pov_character": chapter_data.get("pov", "Unknown"),
        "location": chapter_data.get("location", "Unknown"),
        "time_of_day": chapter_data.get("time", "unspecified"),
        "weather_atmosphere": chapter_data.get("atmosphere", ""),
        "character_want": context.get("current_chapter_roadmap", {}).get("goal", ""),
        "obstacle": context.get("current_chapter_roadmap", {}).get("conflict", ""),
        "subtext_need": chapter_data.get("subtext", ""),
        "what_changes": context.get("current_chapter_roadmap", {}).get("outcome", ""),
        "emotional_arc": {
            "opening": chapter_data.get("emotion_start", ""),
            "closing": chapter_data.get("emotion_end", "")
        },
        "dominant_sense": chapter_data.get("dominant_sense", ""),
        "structural_purpose": chapter_data.get("purpose", ""),
        "required_foreshadowing": [],  # populated from foreshadowing registry
        "required_payoffs": context.get("required_payoffs", []),
        "continuity_flags": context.get("continuity_flags", []),
        "active_critique_notes": context.get("active_critique_notes", []),
    }