"""Durable local book jobs. No model calls are needed to inspect a job."""
import asyncio
import inspect
import json
import os
from pathlib import Path
import shutil
import time
import uuid
import subprocess
import sys
import yaml


def atomic_json(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def create_job(root, concept, chapters=None, model_config=None):
    if not concept.strip():
        raise ValueError('A nonempty concept is required.')
    if chapters is not None and chapters < 1:
        raise ValueError('Chapter count must be positive.')
    job = Path(root) / 'jobs' / uuid.uuid4().hex
    job.mkdir(parents=True)
    for folder in ('config', '06_Services'):
        shutil.copytree(Path(root) / folder, job / folder)
    shutil.copytree(Path(root) / '08_Memory' / 'schemas', job / '08_Memory' / 'schemas')
    if model_config:
        config_path = job / 'config' / 'models.yaml'
        config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
        config.update(model_config)
        config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding='utf-8')
    atomic_json(job / 'job.json', {
        'version': 1, 'concept': concept, 'chapters': chapters,
        'status': 'pending', 'completed_steps': [], 'active_step': None,
        'error': None, 'created_at': time.time(),
    })
    return job


def launch_worker(root, job):
    root, job = Path(root).resolve(), Path(job).resolve()
    with (job / 'worker.log').open('a', encoding='utf-8') as log:
        options = {'start_new_session': True} if os.name != 'nt' else {
            'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        }
        return subprocess.Popen([sys.executable, '-u', str(root / 'athena.py'), 'resume', '--job', job.name],
                                stdin=subprocess.DEVNULL, stdout=log, stderr=log, cwd=root, **options)


class JobRunner:
    def __init__(self, job, orchestrator_factory=None):
        self.job = Path(job).resolve()
        self.state_path = self.job / 'job.json'
        self.state = json.loads(self.state_path.read_text(encoding='utf-8'))
        self.factory = orchestrator_factory

    def save(self):
        self.state['updated_at'] = time.time()
        atomic_json(self.state_path, self.state)

    async def step(self, name, function, *args):
        if name in self.state['completed_steps']:
            return
        self.state['active_step'] = name
        self.save()
        for attempt in range(3):
            try:
                result = function(*args)
                if inspect.isawaitable(result):
                    result = await result
                break
            except (ValueError, KeyError, TypeError) as error:
                self.state['error'] = f'{name}: output validation attempt {attempt + 1}: {error}'
                self.save()
                if attempt == 2:
                    raise
        if result is False:
            raise RuntimeError(f'{name} failed its quality gate.')
        if isinstance(result, dict) and 'decision' in result and result['decision'] != 'APPROVED':
            raise RuntimeError(f'{name}: {result.get("rationale", result["decision"])}')
        self.state['completed_steps'].append(name)
        self.state['error'] = None
        self.save()

    async def run(self):
        # OS-held lock releases on crashes; the file itself may safely remain.
        lock = (self.job / '.worker.lock').open('a+b')
        try:
            lock.seek(0)
            if os.name == 'nt':
                import msvcrt
                if not lock.read(1):
                    lock.write(b'0')
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock.close()
            raise RuntimeError('Another worker is already running this job.')
        try:
            self.state = json.loads(self.state_path.read_text(encoding='utf-8'))
            if self.state['status'] == 'completed':
                return
            self.state.update(status='running', error=None)
            self.save()
            if self.factory is None:
                from orchestrator import Orchestrator
                self.factory = Orchestrator
            orch = self.factory(str(self.job))
            concept = self.state['concept']
            if self.state['chapters']:
                concept += f'\nPlan exactly {self.state["chapters"]} chapters, including the ending.'
            await self.step('intake', orch.run_ceo_intake, concept)
            await self.step('architecture', orch.run_phase_1_architecture, concept)
            await self.step('characters', orch.run_phase_2_psychology)
            await self.step('world', orch.run_phase_3_world)
            await self.step('voice', orch.run_voice_calibration)
            count = orch.pipeline_state.get('total_chapters', 0)
            if not isinstance(count, int) or count < 1:
                raise ValueError('Outline must contain at least one chapter.')
            if self.state['chapters'] and count != self.state['chapters']:
                raise ValueError('Outline chapter count does not match requested chapter count.')
            for number in range(1, count + 1):
                await self.step(f'chapter_{number}', orch.write_and_validate_chapter, number)
                await self.step(f'canon_{number}', orch.post_chapter_extraction, number)
                orch.pipeline_state['last_completed_chapter'] = number
                orch.save_pipeline_state()
                await self.step(f'critique_{number}', orch.run_rolling_critique, number)
            await self.step('metadata', orch.run_publishing_consultation)
            await self.step('manuscript', orch.run_formatting)
            self.state.update(status='completed', active_step=None, error=None)
            self.save()
        except BaseException as error:
            self.state.update(status='interrupted' if isinstance(error, (KeyboardInterrupt, asyncio.CancelledError)) else 'failed',
                              error=str(error) or type(error).__name__)
            self.save()
            raise
        finally:
            lock.close()
