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
            if not isinstance(beat, dict):
                raise ValueError('Each chapter beat must be an object.')
            for field in ('goal', 'conflict', 'outcome'):
                if not isinstance(beat.get(field), str) or not beat[field].strip():
                    raise ValueError(f'Each chapter beat must contain a nonempty {field}.')
    if not isinstance(outline.get('title'), str) or not outline['title'].strip():
        raise ValueError('Outline must contain a nonempty title.')
    state = str(outline.get('state') or outline.get('status') or '').upper()
    if state in ('REJECTED', 'REVISION_REQUIRED'):
        raise ValueError('Outline is marked for revision and cannot be approved.')
    # Runtime approval means the outline passed the structural checks above.
    # It does not claim an editorial review that this pipeline does not run.
    outline['state'] = 'APPROVED'
    outline['approval_basis'] = 'Runtime structural validation: title and complete chapter beats.'
    return outline
