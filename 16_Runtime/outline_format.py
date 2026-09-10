"""Normalize equivalent chapter outlines without inventing missing story beats."""
def normalize_outline(value):
    if not isinstance(value, dict):
        raise ValueError('Outline must be a JSON object.')
    outline = dict(value)
    if 'beat_sheets' not in outline:
        chapters = outline.get('chapter_roadmap')
        if isinstance(chapters, list) and chapters:
            outline['beat_sheets'] = [{'act': 1, 'name': 'Story', 'beats': chapters}]
    acts = outline.get('beat_sheets')
    if not isinstance(acts, list) or not acts:
        raise ValueError('Outline must contain beat_sheets with chapter beats.')
    for act in acts:
        if not isinstance(act, dict) or not isinstance(act.get('beats'), list) or not act['beats']:
            raise ValueError('Each outline act must contain chapter beats.')
        for beat in act['beats']:
            if not isinstance(beat, dict) or not isinstance(beat.get('goal'), str) or not beat['goal'].strip():
                raise ValueError('Each chapter beat must contain a nonempty goal.')
    return outline
