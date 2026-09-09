import re
import statistics
from collections import Counter
from typing import List, Dict, Any

class ProseAnalyzer:
    """
    Programmatic prose quality analysis.
    Provides objective metrics before any LLM scoring.
    """
    
    def passive_voice_rate(self, text: str) -> float:
        """Ratio of passive constructions to total sentences."""
        sentences = re.split(r'[.!?]+', text)
        passive_pattern = re.compile(
            r'\b(was|were|been|being|is|are|am)\b\s+\w+ed\b', re.IGNORECASE
        )
        passive_count = sum(1 for s in sentences if passive_pattern.search(s))
        return passive_count / max(len(sentences), 1)
    
    def sentence_length_variance(self, text: str) -> float:
        """Standard deviation of word counts per sentence. Higher = more varied."""
        sentences = re.split(r'[.!?]+', text)
        lengths = [len(s.split()) for s in sentences if s.strip()]
        return statistics.stdev(lengths) if len(lengths) > 1 else 0
    
    def sentence_length_stats(self, text: str) -> Dict[str, float]:
        """Detailed sentence length statistics."""
        sentences = re.split(r'[.!?]+', text)
        lengths = [len(s.split()) for s in sentences if s.strip()]
        if not lengths:
            return {"mean": 0, "stdev": 0, "min": 0, "max": 0, "median": 0}
        
        return {
            "mean": statistics.mean(lengths),
            "stdev": statistics.stdev(lengths) if len(lengths) > 1 else 0,
            "min": min(lengths),
            "max": max(lengths),
            "median": statistics.median(lengths)
        }
    
    def repeated_phrase_score(self, text: str, previous_chapters: List[str] = None) -> float:
        """Detect n-gram overlap between current chapter and previous chapters."""
        def get_ngrams(t: str, n: int = 4) -> Counter:
            words = t.lower().split()
            return Counter(tuple(words[i:i+n]) for i in range(len(words)-n))
        
        current_ngrams = get_ngrams(text)
        if not current_ngrams:
            return 0.0
            
        overlap_total = 0
        for prev in previous_chapters or []:
            prev_ngrams = get_ngrams(prev)
            overlap = sum((current_ngrams & prev_ngrams).values())
            overlap_total += overlap
        
        return overlap_total / max(len(current_ngrams), 1)
    
    def paragraph_density(self, text: str) -> float:
        """Average words per paragraph. Over 150 = too dense."""
        paragraphs = [p for p in text.split('\n\n') if p.strip()]
        if not paragraphs:
            return 0
        return sum(len(p.split()) for p in paragraphs) / len(paragraphs)
    
    def dialogue_ratio(self, text: str) -> float:
        """Ratio of dialogue words to total words."""
        dialogue_matches = re.findall(r'"[^"]*"', text)
        dialogue_words = sum(len(d.split()) for d in dialogue_matches)
        total_words = len(text.split())
        return dialogue_words / max(total_words, 1)
    
    def adjective_density(self, text: str) -> float:
        """Adjectives per 100 words."""
        # Simple adjective detection (words ending in common adj suffixes before nouns)
        words = text.split()
        adj_count = sum(1 for w in words if re.search(r'(ous|ive|ful|less|al|ic|able|ible|ant|ent|ed|ing)$', w.lower()))
        return (adj_count / max(len(words), 1)) * 100
    
    def adverb_density(self, text: str) -> float:
        """Adverbs per 100 words (-ly words)."""
        words = text.split()
        adv_count = sum(1 for w in words if w.lower().endswith('ly') and len(w) > 3)
        return (adv_count / max(len(words), 1)) * 100
    
    def opening_pattern_diversity(self, text: str) -> float:
        """Measure diversity of sentence opening patterns."""
        sentences = re.split(r'[.!?]+', text)
        openings = []
        
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            words = s.split()
            if not words:
                continue
            
            first_word = words[0].lower()
            # Categorize opening type
            if first_word in ('the', 'a', 'an', 'this', 'that', 'these', 'those'):
                openings.append('determiner')
            elif first_word in ('i', 'he', 'she', 'it', 'we', 'they', 'you'):
                openings.append('pronoun')
            elif first_word.endswith('ly'):
                openings.append('adverb')
            elif first_word in ('and', 'but', 'or', 'so', 'yet', 'for', 'nor'):
                openings.append('conjunction')
            elif first_word.endswith('ing'):
                openings.append('participle')
            elif first_word in ('in', 'on', 'at', 'by', 'with', 'from', 'to', 'for', 'of'):
                openings.append('preposition')
            else:
                openings.append('other')
        
        if not openings:
            return 0.0
        
        unique = len(set(openings))
        return unique / len(openings)
    
    def atmospheric_descriptor_count(self, text: str) -> int:
        """Count atmospheric descriptors (weather, lighting, fog, etc.)."""
        atmospheric_words = [
            'fog', 'mist', 'haze', 'smog', 'cloud', 'overcast', 'grey', 'gray',
            'rain', 'storm', 'thunder', 'lightning', 'wind', 'breeze', 'gust',
            'cold', 'hot', 'warm', 'chill', 'freeze', 'heat', 'temperature',
            'dark', 'darkness', 'shadow', 'shade', 'dim', 'gloom', 'murk',
            'light', 'bright', 'sun', 'sunlight', 'moon', 'moonlight', 'glow',
            'silence', 'quiet', 'still', 'sound', 'noise', 'echo', 'hum'
        ]
        
        text_lower = text.lower()
        count = 0
        for word in atmospheric_words:
            count += len(re.findall(r'\b' + re.escape(word) + r'\b', text_lower))
        return count
    
    def hedged_language_count(self, text: str) -> int:
        """Count hedged emotional statements."""
        hedge_patterns = [
            r'\b(kind of|sort of|seemed to|appeared to|almost|nearly)\b',
            r'\b(felt like|feels like|was like|were like)\b',
            r'\b(a bit of|a little|somewhat|rather|quite)\b',
        ]
        
        count = 0
        for pattern in hedge_patterns:
            count += len(re.findall(pattern, text, re.IGNORECASE))
        return count
    
    def word_count(self, text: str) -> int:
        """Total word count."""
        return len(text.split())
    
    def run_full_analysis(self, text: str, previous_chapters: List[str] = None) -> Dict[str, Any]:
        """Run complete analysis and return all metrics."""
        previous_chapters = previous_chapters or []
        
        # Extract prose from chapter JSON if needed
        prose = text
        try:
            data = json.loads(text)
            prose = data.get("prose_content", "") or data.get("content", "") or str(data)
        except:
            pass
        
        return {
            "passive_voice_rate": round(self.passive_voice_rate(prose), 3),
            "sentence_length_variance": round(self.sentence_length_variance(prose), 2),
            "sentence_length_stats": self.sentence_length_stats(prose),
            "repeated_phrase_score": round(self.repeated_phrase_score(prose, previous_chapters), 4),
            "paragraph_density_avg": round(self.paragraph_density(prose), 1),
            "dialogue_ratio": round(self.dialogue_ratio(prose), 3),
            "adjective_density": round(self.adjective_density(prose), 2),
            "adverb_density": round(self.adverb_density(prose), 2),
            "opening_pattern_diversity": round(self.opening_pattern_diversity(prose), 3),
            "atmospheric_descriptor_count": self.atmospheric_descriptor_count(prose),
            "hedged_language_count": self.hedged_language_count(prose),
            "word_count": self.word_count(prose),
            "quality_yaml_checks": {
                "passive_voice_violation": self.passive_voice_rate(prose) > 0.15,
                "repetition_flag": self.repeated_phrase_score(prose, previous_chapters) > 0.02,
                "sentence_length_too_uniform": self.sentence_length_variance(prose) < 5.0,
                "paragraphs_too_dense": self.paragraph_density(prose) > 150,
                "excessive_atmosphere": self.atmospheric_descriptor_count(prose) > (self.word_count(prose) / 500),
                "excessive_hedging": self.hedged_language_count(prose) > 3
            }
        }


# Import json at top level
import json