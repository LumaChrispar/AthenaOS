"""Read-only view of how a book is planned, for the pipeline inspector.

Nothing here calls a model or writes to the job; it reads what the worker
already saved and describes it. Stage names and ordering mirror
``job_runner.JobRunner.run_locked`` and ``orchestrator.write_and_validate_chapter``
so the view cannot drift into claiming work that did not happen: chapter-level
progress comes from ``job.json``, never from inference.
"""
import json
import os
import re
from pathlib import Path

import yaml
from service_loader import load_service, format_system_prompt

# The worker log grows without bound; the UI already reads a bounded tail and
# this module matches it so both views cover the same window.
LOG_TAIL_BYTES = 16000

# Rough English ratio. Enough to show a request approaching a server's context
# limit, which is the point; not a substitute for a real tokenizer.
CHARS_PER_TOKEN = 4

# One optional subdirectory, so the per-chapter summaries under chapters/ can be
# read. Segments must start alphanumeric, so "." and ".." can never be a segment;
# the resolved-path check below is the second line of defence.
SAFE_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)?')
CHAPTER_HEADING = re.compile(r'^---\s*CHAPTER\s+(\d+):\s*(.+?)\s*(?:\((SRV-\d+)\))?\s*---')
ATTEMPT_HEADING = re.compile(r'^===\s*Chapter\s+(\d+),\s*Attempt\s+(\d+)/(\d+)')
EVENT_PATTERN = re.compile(r'Error|Warning|ESCALATION|\[RETRY|Job stopped|model-call limit')

# Planning steps, mirroring the order JobRunner.run_locked awaits them.
PLANNING_STAGES = (
    ('intake', 'Concept & intake', 'SRV-001', 'intake_brief.json · ceo_intake_decision.json',
     'Turns your brief into a writing brief and an approve-or-reject decision.'),
    ('architecture', 'Story architecture', 'SRV-002', 'outline.json',
     'Plans the acts and one beat per chapter: goal, conflict, outcome.'),
    ('characters', 'Character psychology', 'SRV-003', 'psychology.json',
     'Profiles each character, including the speech style the dialogue pass needs.'),
    ('world', 'World building', 'SRV-004', 'story_bible.json',
     'Establishes locations, world rules, and the timeline.'),
    ('voice', 'Voice calibration', 'SRV-028', 'voice_sample.md',
     'Creates a compact voice card that guides every drafted scene.'),
)

FINISH_STAGES = (
    ('metadata', 'Publishing metadata', 'SRV-019', 'metadata.json',
     'Title, blurb, and keywords derived from the outline and chapter summaries.'),
    ('manuscript', 'Manuscript assembly', '—', 'manuscript.md · delivery.json',
     'Joins the approved chapters into the finished manuscript without rewriting them.'),
)

# The per-chapter passes, in the order orchestrator.write_and_validate_chapter
# runs them. Used to explain which services a chapter step calls.
CHAPTER_PASSES = (
    ('Scene-by-scene drafting', 'SRV-005'),
    ('Targeted voice edits', 'SRV-027'),
    ('Dialogue audit', 'SRV-013'),
    ('Targeted dialogue edits', 'SRV-005'),
    ('Developmental edit', 'SRV-007'),
    ('Continuity check', 'SRV-016'),
    ('QA check', 'SRV-010'),
    ('Reader proxy', 'SRV-030'),
    ('Targeted copy edit', 'SRV-008'),
)

# Artifacts grouped so the browser can say what each one is for.
ARTIFACT_GROUPS = (
    ('plan', ('intake_brief.json', 'ceo_intake_decision.json', 'outline.json',
              'psychology.json', 'story_bible.json', 'story_bible_initial.json',
              'foreshadowing_registry.json')),
    ('voice', ('voice_sample.md',)),
    ('delivery', ('metadata.json', 'manuscript.md', 'delivery.json', 'ceo_signoff_decision.json')),
    ('state', ('pipeline_state.json', 'usage.json', 'chat_usage.json')),
)


def estimate_tokens(text):
    """Approximate token count. Four characters per token is the usual English rule of thumb."""
    return len(text) // CHARS_PER_TOKEN


def _read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def _read_text(path):
    try:
        return path.read_text(encoding='utf-8')
    except OSError:
        return ''


def read_log_tail(job, limit=LOG_TAIL_BYTES):
    """Return the tail of worker.log plus whether earlier content was dropped."""
    path = Path(job) / 'worker.log'
    if not path.exists():
        return '', False
    with path.open('rb') as stream:
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(max(0, size - limit))
        return stream.read().decode('utf-8', errors='replace'), size > limit


def _artifact_group(name):
    if name.endswith(('.raw', '.raw.md')):
        return 'raw'
    for group, names in ARTIFACT_GROUPS:
        if name in names:
            return group
    if name.startswith('chapter_') and name.endswith('_summary.json'):
        return 'summary'
    if name.startswith('chapter_'):
        return 'chapter'
    if re.match(r'(continuity_report|dev_edit_report|qa_|dialogue_audit_|reader_proxy_|critique_)chapter_|^critique_checkpoint_', name):
        return 'review'
    if name.startswith('event_'):
        return 'state'
    return 'other'


def artifacts(job):
    """Every planning artifact saved so far, with its size and purpose."""
    memory = Path(job) / '08_Memory'
    found = []
    for path in sorted(memory.rglob('*')):
        if not path.is_file() or 'schemas' in path.relative_to(memory).parts:
            continue
        found.append({
            'name': path.relative_to(memory).as_posix(),
            'bytes': path.stat().st_size,
            'group': _artifact_group(path.name),
        })
    return found


def _critique_checkpoints(job):
    """Matching config/quality.yaml, falling back to the pipeline's own default."""
    try:
        config = yaml.safe_load(_read_text(Path(job) / 'config' / 'quality.yaml')) or {}
    except yaml.YAMLError:
        config = {}
    checkpoints = config.get('critique_checkpoints') or [3, 6, 9, 12, 15]
    try:
        return [int(number) for number in checkpoints]
    except (TypeError, ValueError):
        return [3, 6, 9, 12, 15]


def _stage(step, label, service, artifact, note, completed, active):
    if step in completed:
        status = 'done'
    elif step == active:
        status = 'active'
    else:
        status = 'pending'
    return {'step': step, 'label': label, 'service': service,
            'artifact': artifact, 'note': note, 'status': status}


def stages(job, state, pipeline, total):
    """Every pipeline step in execution order with its real status."""
    completed = set(state.get('completed_steps') or [])
    active = state.get('active_step')
    built = [_stage(step, label, service, artifact, note, completed, active)
             for step, label, service, artifact, note in PLANNING_STAGES]
    checkpoints = _critique_checkpoints(job)
    for number in range(1, total + 1):
        suffix = f'{number:02d}'
        built.append(_stage(
            f'chapter_{number}', f'Chapter {number}', 'SRV-005 · SRV-027 · SRV-013 · SRV-007 · SRV-016 · SRV-010 · SRV-008',
            f'chapter_{suffix}.json',
            'Plans and saves 3–5 scenes, drafts each separately, then runs focused voice, dialogue, '
            'editorial, continuity, QA, and copy passes until every gate passes.',
            completed, active))
        built.append(_stage(
            f'canon_{number}', f'Canon {number}', 'SRV-009',
            f'chapters/chapter_{suffix}_summary.json',
            'Extracts this chapter’s facts, then saves canon updates locally without regenerating the full bible.',
            completed, active))
        if number in checkpoints:
            built.append(_stage(
                f'critique_{number}', f'Rolling critique {number}', 'SRV-026',
                f'critique_checkpoint_{number}.json',
                'Reads the manuscript so far and sets priority actions for later chapters.',
                completed, active))
    built.extend(_stage(step, label, service, artifact, note, completed, active)
                 for step, label, service, artifact, note in FINISH_STAGES)
    return built


def chapter_passes(job, number, log):
    """Which per-chapter services the worker has actually logged for this chapter.

    Reads the headings the orchestrator printed rather than assuming a pass ran,
    so a stalled chapter shows exactly where it stopped. Repeat headings collapse
    into a run count, which is how a retried chapter announces itself.
    """
    if not number:
        return {'attempt': None, 'passed': []}
    seen, order, attempt = {}, [], None
    for line in log.splitlines():
        line = line.strip()
        attempt_match = ATTEMPT_HEADING.match(line)
        if attempt_match and int(attempt_match.group(1)) == number:
            attempt = {'current': int(attempt_match.group(2)), 'of': int(attempt_match.group(3))}
            continue
        heading = CHAPTER_HEADING.match(line)
        if not heading or int(heading.group(1)) != number:
            continue
        key = (heading.group(2).title(), heading.group(3) or '—')
        if key not in seen:
            seen[key] = 0
            order.append(key)
        seen[key] += 1
    passed = [{'label': label, 'service': service, 'runs': seen[(label, service)]}
              for label, service in order]
    return {'attempt': attempt, 'passed': passed,
            'retried': any(pass_['runs'] > 1 for pass_ in passed)}


def outline(job, stage_status):
    """The planned beat sheet, with each chapter tagged by its pipeline status."""
    data = _read_json(Path(job) / '08_Memory' / 'outline.json')
    if not isinstance(data, dict) or not isinstance(data.get('beat_sheets'), list):
        return None
    acts, chapter = [], 0
    for act in data['beat_sheets']:
        if not isinstance(act, dict):
            continue
        beats = []
        for beat in act.get('beats') or []:
            if not isinstance(beat, dict):
                continue
            chapter += 1
            beats.append({
                'chapter': chapter,
                'goal': beat.get('goal', ''),
                'conflict': beat.get('conflict', ''),
                'outcome': beat.get('outcome', ''),
                'status': stage_status.get(f'chapter_{chapter}', 'pending'),
            })
        acts.append({'act': act.get('act'), 'name': act.get('name', ''), 'beats': beats})
    return {'title': data.get('title', ''), 'acts': acts, 'chapters': chapter}


def _previous_tail(job, number):
    """The 500-word tail MemoryManager.get_chapter_tail would embed."""
    if number < 2:
        return ''
    data = _read_json(Path(job) / '08_Memory' / f'chapter_{number - 1:02d}.json')
    if not isinstance(data, dict):
        return ''
    prose = data.get('prose_content') or data.get('content') or ''
    words = str(prose).split()
    return ' '.join(words[-500:])


def context_budget(job, number):
    """Size the chapter-draft request the way the orchestrator actually builds it.

    Every row is a file the SRV-005 prompt embeds verbatim, measured on disk.
    """
    memory = Path(job) / '08_Memory'
    try:
        system = format_system_prompt(load_service('SRV-005', str(job)))
    except (OSError, ValueError):
        system = _read_text(Path(job) / '06_Services' / 'SRV-005.md')
    components = [
        ('SRV-005 system prompt', '06_Services/SRV-005.md', system),
        ('Outline', '08_Memory/outline.json', _read_text(memory / 'outline.json')),
        ('Character profiles', '08_Memory/psychology.json', _read_text(memory / 'psychology.json')),
        ('Story bible', '08_Memory/story_bible.json', _read_text(memory / 'story_bible.json')),
        ('Voice sample', '08_Memory/voice_sample.md', _read_text(memory / 'voice_sample.md')),
        ('Chapter schema', '08_Memory/schemas/chapter.schema.json',
         _read_text(memory / 'schemas' / 'chapter.schema.json')),
    ]
    tail = _previous_tail(job, number)
    if tail:
        components.append((f'Chapter {number - 1} tail (500 words)',
                           f'08_Memory/chapter_{number - 1:02d}.json', tail))
    rows = [{'label': label, 'source': source, 'bytes': len(text),
             'tokens': estimate_tokens(text)}
            for label, source, text in components if text]
    preview = [{'label': label, 'bytes': len(text.encode('utf-8')),
                'text': text[:1400] + ('\n… preview shortened …' if len(text) > 1400 else '')}
               for label, _source, text in components if text]
    prompt_tokens = sum(row['tokens'] for row in rows)
    try:
        config = yaml.safe_load(_read_text(Path(job) / 'config' / 'models.yaml')) or {}
    except yaml.YAMLError:
        config = {}
    output_tokens = config.get('max_output_tokens', 8192)
    needed = prompt_tokens + output_tokens
    if needed > 32768:
        advice = (f'About {needed:,} tokens for one request. Raise the loaded context length in your '
                  'model server above that, or the request will be rejected or come back empty.')
    elif needed > 8192:
        advice = (f'About {needed:,} tokens for one request — more than a typical 8k local context. '
                  'Raise the loaded context length in your model server.')
    else:
        advice = f'About {needed:,} tokens for one request. This fits a 16k context with room to spare.'
    return {'chapter': number, 'rows': rows, 'prompt_tokens': prompt_tokens,
            'output_tokens': output_tokens, 'context_needed': needed, 'advice': advice,
            'preview': preview}


def call_budget(job):
    """Model calls spent against the per-book cap."""
    usage = _read_json(Path(job) / '08_Memory' / 'usage.json', {}) or {}
    try:
        config = yaml.safe_load(_read_text(Path(job) / 'config' / 'models.yaml')) or {}
    except yaml.YAMLError:
        config = {}
    cap = config.get('max_calls_per_job', 200)
    calls = usage.get('calls', 0)
    return {'calls': calls, 'cap': cap, 'percent': round(100 * calls / cap) if cap else 0,
            'prompt_tokens': usage.get('prompt_tokens', 0),
            'completion_tokens': usage.get('completion_tokens', 0),
            'by_service': usage.get('by_service', {}),
            'warn': bool(cap) and calls >= cap * 0.8}


def events(log):
    """Worker log lines worth reading: failures, retries, and escalations."""
    found = []
    for number, line in enumerate(log.splitlines(), 1):
        line = line.strip()
        if line and EVENT_PATTERN.search(line):
            found.append({'line': number, 'text': line})
    return found


def inspect_job(job):
    """The full inspector payload for one book."""
    job = Path(job)
    state = _read_json(job / 'job.json', {}) or {}
    pipeline = _read_json(job / '08_Memory' / 'pipeline_state.json', {}) or {}
    log, truncated = read_log_tail(job)
    total = pipeline.get('total_chapters') or state.get('chapters') or 0
    total = total if isinstance(total, int) and total > 0 else 0

    built = stages(job, state, pipeline, total)
    durations = state.get('step_durations_seconds', {})
    for stage in built:
        stage['duration_seconds'] = durations.get(stage['step'])
    status = {stage['step']: stage['status'] for stage in built}

    active = state.get('active_step') or ''
    match = re.match(r'chapter_(\d+)', active)
    if match:
        current = int(match.group(1))
    else:
        current = min((pipeline.get('last_completed_chapter') or 0) + 1, total) if total else 0
    current = max(current, 1) if total else 0

    return {
        'id': job.name,
        'status': state.get('status', 'pending'),
        'error': state.get('error'),
        'active_step': active or None,
        'completed_steps': state.get('completed_steps') or [],
        'total_chapters': total,
        'last_completed_chapter': pipeline.get('last_completed_chapter') or 0,
        'stages': built,
        'chapter': chapter_passes(job, current, log),
        'outline': outline(job, status),
        'artifacts': artifacts(job),
        'context': context_budget(job, current),
        'budget': call_budget(job),
        'events': events(log),
        'prompts': prompt_calls(job),
        'log_truncated': truncated,
    }


def prompt_calls(job):
    """Captured prompts, grouped by service, newest call last.

    Metadata only; the prompt bodies are large and are fetched one at a time by
    ``prompt_text`` when the pipeline view opens one.
    """
    prompts = Path(job) / '08_Memory' / 'prompts'
    grouped = {}
    try:
        names = sorted(name for name in os.listdir(prompts) if name.endswith('.json'))
    except OSError:
        return grouped
    for name in names:
        record = _read_json(prompts / name)
        if not isinstance(record, dict) or not isinstance(record.get('service'), str):
            continue
        record['chars'] = sum(len(record.get(part) or '') for part in ('system', 'user'))
        record.pop('system', None), record.pop('user', None)
        record['name'] = name
        grouped.setdefault(record['service'], []).append(record)
    return grouped


def prompt_text(job, name):
    """One captured prompt, verbatim, for viewing or copying."""
    if not isinstance(name, str) or not SAFE_NAME.fullmatch(name) or not name.endswith('.json'):
        raise ValueError('Invalid prompt name.')
    prompts = (Path(job) / '08_Memory' / 'prompts').resolve()
    path = (prompts / name).resolve()
    if not path.is_relative_to(prompts) or not path.is_file():
        raise ValueError('That prompt does not exist.')
    record = _read_json(path)
    if not isinstance(record, dict):
        raise ValueError('That prompt does not exist.')
    header = (f"service: {record.get('service')}\nmodel: {record.get('model')}\n"
              f"temperature: {record.get('temperature')}\ntokens: ~{record.get('prompt_tokens')}\n")
    return header + '\n===== SYSTEM =====\n' + (record.get('system') or '') + \
        '\n\n===== USER =====\n' + (record.get('user') or '')


def artifact_text(job, name):
    """Read one artifact for the viewer. Rejects anything that is not a plain file in 08_Memory."""
    if not isinstance(name, str) or not SAFE_NAME.fullmatch(name):
        raise ValueError('Invalid artifact name.')
    memory = (Path(job) / '08_Memory').resolve()
    path = (memory / name).resolve()
    if not path.is_relative_to(memory) or not path.is_file():
        raise ValueError('That artifact does not exist.')
    text = path.read_text(encoding='utf-8', errors='replace')
    limit = 512000
    return text if len(text) <= limit else text[:limit] + '\n\n… truncated for display.'
