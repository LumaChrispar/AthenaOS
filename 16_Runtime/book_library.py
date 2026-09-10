"""Book changes run under the worker lock; snapshots preserve earlier drafts."""
import json
from pathlib import Path
import shutil
import time
import uuid
import yaml
from job_runner import atomic_json


def read(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def snapshot(job):
    destination = job / 'revisions' / uuid.uuid4().hex
    destination.mkdir(parents=True)
    shutil.copy2(job / 'job.json', destination / 'job.json')
    shutil.copytree(job / '08_Memory', destination / '08_Memory')
    shutil.copy2(job / 'config/models.yaml', destination / 'models.yaml')
    return destination


def update_model(job, config):
    path = job / 'config/models.yaml'
    current = yaml.safe_load(path.read_text(encoding='utf-8'))
    current.update(config)
    temporary = path.with_suffix('.yaml.tmp')
    temporary.write_text(yaml.safe_dump(current, sort_keys=False), encoding='utf-8')
    temporary.replace(path)


def editor_data(job):
    state = read(job / 'job.json')
    chapters = []
    for step in state['completed_steps']:
        if step.startswith('chapter_'):
            number = int(step.split('_')[1])
            chapter = read(job / '08_Memory' / f'chapter_{number:02d}.json', {})
            chapters.append({'number': number, 'title': chapter.get('title', ''),
                             'prose': chapter.get('prose_content', '')})
    return {'concept': state['concept'], 'can_edit_brief': not state['completed_steps'],
            'chapters': sorted(chapters, key=lambda c: c['number'])}


def edit_book(job, data):
    state = read(job / 'job.json')
    if data.get('kind') == 'brief':
        if state['completed_steps']:
            raise ValueError('The brief is already planned. Edit saved chapters or add a continuation instead.')
        concept = data.get('text')
        if not isinstance(concept, str) or not 1 <= len(concept.strip()) <= 30000:
            raise ValueError('The brief must contain 1–30,000 characters.')
        snapshot(job)
        state.update(concept=concept.strip(), error=None, status='pending', active_step=None)
        # Intake feedback from the old concept must not guide the edited concept.
        memory = job / '08_Memory'
        for name in ('outline.json', 'intake_brief.json', 'ceo_intake_decision.json', 'pipeline_state.json'):
            (memory / name).unlink(missing_ok=True)
    else:
        number, prose, title = data.get('number'), data.get('text'), data.get('title', '')
        if type(number) is not int or f'chapter_{number}' not in state['completed_steps']:
            raise ValueError('Choose a saved chapter.')
        if not isinstance(prose, str) or not 1 <= len(prose.strip()) <= 500000:
            raise ValueError('Chapter text must contain 1–500,000 characters.')
        if not isinstance(title, str) or len(title) > 300:
            raise ValueError('Chapter title must be at most 300 characters.')
        snapshot(job)
        path = job / '08_Memory' / f'chapter_{number:02d}.json'
        chapter = read(path)
        chapter.update(title=title, prose_content=prose, edited_by_user=True)
        atomic_json(path, chapter)
        atomic_json(job / '08_Memory' / f'chapter_{number:02d}_varied.json', chapter)
        # Rebuild derived facts in chapter order before continuing, so removed
        # events do not survive in old summaries or the story bible.
        state['rebuild_canon'] = sorted(int(s.split('_')[1]) for s in state['completed_steps'] if s.startswith('chapter_'))
        state['completed_steps'] = [s for s in state['completed_steps'] if s != 'rebuild_canon']
        if state['status'] == 'completed':
            from memory_manager import MemoryManager
            from orchestrator import Orchestrator
            import asyncio
            formatter = Orchestrator.__new__(Orchestrator)
            formatter.memory = MemoryManager(str(job))
            formatter.pipeline_state = read(job / '08_Memory/pipeline_state.json')
            asyncio.run(formatter.run_formatting())
    state['updated_at'] = time.time()
    atomic_json(job / 'job.json', state)


def continue_book(job, instructions, extra):
    state = read(job / 'job.json')
    if state['status'] != 'completed':
        raise ValueError('Resume the unfinished book first. Extra chapters can be added after completion.')
    if not isinstance(instructions, str) or not 1 <= len(instructions.strip()) <= 8000:
        raise ValueError('Describe the continuation in 1–8,000 characters.')
    count = read(job / '08_Memory/pipeline_state.json')['total_chapters']
    if type(extra) is not int or not 1 <= extra <= 200 or count + extra > 200:
        raise ValueError('Choose additional chapters within the 200-chapter book limit.')
    snapshot(job)
    state.update(status='pending', error=None, active_step=None, chapters=count + extra,
                 continuation={'instructions': instructions.strip(), 'start': count, 'extra': extra})
    state['completed_steps'] = [s for s in state['completed_steps'] if s not in ('continuation', 'metadata', 'manuscript')]
    atomic_json(job / 'job.json', state)
