"""Durable chapter narration through local Kokoro or a compatible speech API."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import wave
from urllib.parse import urlsplit

import httpx
from job_runner import atomic_json
from job_lock import job_lock
from providers import api_key_for

DEFAULTS = {'provider': 'kokoro', 'base_url': 'http://127.0.0.1:8880/v1',
            'model': 'kokoro', 'voice': 'af_heart', 'speed': 1.0, 'timeout_seconds': 300}


def read(path, default=None):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else default


def validate_settings(data):
    provider = data.get('provider', 'kokoro')
    if provider not in ('kokoro', 'local', 'openai'):
        raise ValueError('Choose Kokoro, a local compatible speech server, or OpenAI.')
    defaults = DEFAULTS if provider != 'openai' else {
        **DEFAULTS, 'base_url': 'https://api.openai.com/v1', 'model': 'gpt-4o-mini-tts', 'voice': 'alloy'}
    result = {key: data.get(key, value) for key, value in defaults.items()}
    result['provider'] = provider
    url = urlsplit(result['base_url'])
    if (url.username or url.password or url.query or url.fragment or url.path.rstrip('/') != '/v1'
            or (provider == 'openai' and (url.scheme != 'https' or url.hostname != 'api.openai.com'))
            or (provider != 'openai' and (url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost', '::1')))):
        raise ValueError('Local speech servers need a loopback HTTP address ending in /v1. OpenAI uses https://api.openai.com/v1.')
    for key in ('model', 'voice'):
        if not isinstance(result[key], str) or not 1 <= len(result[key].strip()) <= 200:
            raise ValueError(f'Enter a speech {key} between 1 and 200 characters.')
        result[key] = result[key].strip()
    speed = result['speed']
    if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not 0.25 <= speed <= 4:
        raise ValueError('Narration speed must be between 0.25 and 4.')
    if type(result['timeout_seconds']) is not int or not 30 <= result['timeout_seconds'] <= 3600:
        raise ValueError('Speech timeout must be between 30 and 3600 seconds.')
    result['base_url'] = result['base_url'].rstrip('/')
    return result


def studio_data(job):
    job = Path(job)
    state = read(job / 'job.json')
    if state.get('deleted_at') or state['status'] != 'completed':
        raise ValueError('Finish the manuscript before opening the audiobook studio.')
    memory = job / '08_Memory'
    metadata = read(memory / 'metadata.json', {})
    count = read(memory / 'pipeline_state.json', {}).get('total_chapters', 0)
    chapters = []
    for number in range(1, count + 1):
        chapter = read(memory / f'chapter_{number:02d}.json', {})
        prose = chapter.get('prose_content', '')
        if not isinstance(prose, str) or not prose.strip():
            raise ValueError(f'Chapter {number} has no final prose.')
        chapters.append({'number': number, 'title': chapter.get('title') or f'Chapter {number}',
                         'prose': prose, 'words': len(prose.split())})
    if not chapters:
        raise ValueError('No completed chapters are available.')
    return {'title': metadata.get('title') or state['concept'][:80], 'blurb': metadata.get('blurb', ''),
            'chapters': chapters, 'words': sum(c['words'] for c in chapters)}


def chunks(text, maximum=1400):
    """Bound every chunk, even a sentence without punctuation."""
    pieces = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= maximum:
            pieces.append(remaining)
            break
        window = remaining[:maximum + 1]
        boundary = max(window.rfind('\n\n'), window.rfind('. '), window.rfind('? '), window.rfind('! '))
        if boundary < maximum // 3:
            boundary = window.rfind(' ')
        if boundary < 1:
            boundary = maximum
        elif remaining[boundary] in '.?!':
            boundary += 1
        pieces.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].strip()
    return pieces


def wav_data(data):
    # Some streaming WAV servers leave sentinel lengths in RIFF/data headers.
    # Correct sizes only for the actual data chunk, preserving other RIFF chunks.
    value = bytearray(data)
    if value[:4] != b'RIFF' or value[8:12] != b'WAVE':
        raise ValueError('The speech server did not return a PCM WAV file.')
    value[4:8] = (len(value) - 8).to_bytes(4, 'little')
    offset = 12
    while offset + 8 <= len(value):
        size = int.from_bytes(value[offset + 4:offset + 8], 'little')
        if value[offset:offset + 4] == b'data' and size > len(value) - offset - 8:
            value[offset + 4:offset + 8] = (len(value) - offset - 8).to_bytes(4, 'little')
            break
        offset += 8 + size + size % 2
    try:
        with wave.open(io.BytesIO(value), 'rb') as source:
            spec = (source.getnchannels(), source.getsampwidth(), source.getframerate())
            frames = source.readframes(source.getnframes())
            if not frames or len(frames) % (spec[0] * spec[1]):
                raise ValueError('The speech server returned empty or incomplete audio.')
            return spec, frames
    except (wave.Error, EOFError) as error:
        raise ValueError('The speech server returned an unsupported WAV file.') from error


def merge_wavs(paths, destination):
    spec = None
    temporary = Path(destination).with_suffix('.wav.tmp')
    try:
        with wave.open(str(temporary), 'wb') as output:
            for path in paths:
                current, frames = wav_data(Path(path).read_bytes())
                if spec is None:
                    spec = current
                    output.setnchannels(spec[0])
                    output.setsampwidth(spec[1])
                    output.setframerate(spec[2])
                if current != spec:
                    raise ValueError('Speech audio formats changed between chunks. Use one model and voice.')
                output.writeframes(frames)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def fingerprint(chapter, settings):
    return hashlib.sha256(json.dumps({'chapter': chapter, 'settings': settings}, sort_keys=True).encode()).hexdigest()


def status(job):
    job = Path(job)
    result = read(job / 'audio/state.json', {'status': 'idle', 'tracks': {}})
    if result.get('status') == 'running':
        from job_lock import worker_is_active
        if not worker_is_active(job / 'audio'):
            result = {**result, 'status': 'interrupted', 'error': 'Narration stopped. Generate again to resume saved chunks.'}
    result = dict(result)
    settings = result.get('settings')
    studio = studio_data(job)
    tracks = {}
    for chapter in studio['chapters']:
        track = result.get('tracks', {}).get(str(chapter['number']))
        if track and settings and track.get('fingerprint') == fingerprint(chapter, settings):
            tracks[str(chapter['number'])] = track
    result['tracks'] = tracks
    master = result.get('master')
    current = [tracks.get(str(c['number']), {}).get('fingerprint') for c in studio['chapters']]
    if master and (None in current or master.get('fingerprints') != current):
        result.pop('master', None)
    return result


def prepare(job, settings, numbers):
    job = Path(job)
    settings = validate_settings(settings)
    chapters = studio_data(job)['chapters']
    valid = {c['number'] for c in chapters}
    if not isinstance(numbers, list) or not numbers or any(type(n) is not int or n not in valid for n in numbers):
        raise ValueError('Choose completed chapters to narrate.')
    if settings['provider'] == 'openai':
        api_key_for('openai', job.parents[1])
    directory = job / 'audio'
    directory.mkdir(exist_ok=True)
    with job_lock(directory):
        old = read(directory / 'state.json', {})
        atomic_json(directory / 'state.json', {'status': 'pending', 'settings': settings,
            'chapters': sorted(set(numbers)), 'tracks': old.get('tracks', {}), 'error': None,
            'completed_chunks': 0, 'total_chunks': 0, 'updated_at': time.time()})


def launch(root, job):
    root, job = Path(root).resolve(), Path(job).resolve()
    with (job / 'audio/worker.log').open('a', encoding='utf-8') as log:
        options = {'start_new_session': True} if os.name != 'nt' else {
            'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS}
        return subprocess.Popen([sys.executable, '-u', str(root / 'athena.py'), 'narrate', '--job', job.name],
                                cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **options)


def run(job, synthesize=None):
    job = Path(job)
    directory = job / 'audio'
    with job_lock(job), job_lock(directory):
        state = read(directory / 'state.json')
        try:
            settings = validate_settings(state['settings'])
            chapters = [c for c in studio_data(job)['chapters'] if c['number'] in state['chapters']]
            work = [(c, chunks(f'Chapter {c["number"]}. {c["title"]}.\n\n{c["prose"]}')) for c in chapters]
            state.update(status='running', error=None, completed_chunks=0,
                         total_chunks=sum(len(parts) for _, parts in work))
            atomic_json(directory / 'state.json', state)
            for chapter, parts in work:
                identity = fingerprint(chapter, settings)
                paths = []
                state['active_chapter'] = chapter['number']
                for index, text in enumerate(parts):
                    path = directory / f'{identity}-{index:04d}.wav'
                    if not path.exists():
                        data = synthesize(text, settings) if synthesize else speech(text, settings, job.parents[1])
                        wav_data(data)
                        temporary = path.with_suffix('.tmp')
                        temporary.write_bytes(data)
                        temporary.replace(path)
                    paths.append(path)
                    state['completed_chunks'] += 1
                    state['updated_at'] = time.time()
                    atomic_json(directory / 'state.json', state)
                filename = f'chapter-{chapter["number"]:03d}-{identity[:16]}.wav'
                merge_wavs(paths, directory / filename)
                with wave.open(str(directory / filename), 'rb') as audio:
                    duration = audio.getnframes() / audio.getframerate()
                state['tracks'][str(chapter['number'])] = {'filename': filename, 'fingerprint': identity,
                    'title': chapter['title'], 'duration': round(duration, 2), 'voice': settings['voice']}
                atomic_json(directory / 'state.json', state)
            # Whole-book master is available only when every current chapter is narrated
            # with these same settings and this exact manuscript revision.
            all_chapters = studio_data(job)['chapters']
            tracks = [state['tracks'].get(str(c['number']), {}) for c in all_chapters]
            if all(t.get('fingerprint') == fingerprint(c, settings) for c, t in zip(all_chapters, tracks)):
                identity = hashlib.sha256(''.join(t['fingerprint'] for t in tracks).encode()).hexdigest()[:16]
                filename = f'book-{identity}.wav'
                merge_wavs([directory / t['filename'] for t in tracks], directory / filename)
                state['master'] = {'filename': filename, 'fingerprints': [t['fingerprint'] for t in tracks]}
            else:
                state.pop('master', None)
            state.update(status='completed', active_chapter=None, updated_at=time.time())
            atomic_json(directory / 'state.json', state)
        except BaseException as error:
            state.update(status='failed', error=str(error), updated_at=time.time())
            atomic_json(directory / 'state.json', state)
            raise


def speech(text, settings, root):
    headers = {}
    if settings['provider'] == 'openai':
        headers['Authorization'] = 'Bearer ' + api_key_for('openai', root)
    try:
        response = httpx.post(settings['base_url'] + '/audio/speech', headers=headers,
            json={'model': settings['model'], 'voice': settings['voice'], 'input': text,
                  'speed': settings['speed'], 'response_format': 'wav'},
            timeout=settings['timeout_seconds'], follow_redirects=False)
        response.raise_for_status()
        return response.content
    except httpx.HTTPStatusError as error:
        raise RuntimeError(f'Speech server returned HTTP {error.response.status_code}. Check the model, voice and credentials; saved audio chunks are kept.') from None
    except httpx.HTTPError:
        raise RuntimeError('Cannot reach the speech server. Start Kokoro or check your connection, then generate again to resume saved chunks.') from None
