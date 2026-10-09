"""Optional narrated HyperFrames motion storybooks built from final book artifacts."""
import hashlib
from html import escape
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from audiobook import read, studio_data, status as audio_status
from job_runner import atomic_json
from job_lock import job_lock, worker_is_active


def engine():
    candidates = [Path(__file__).resolve().parents[1] / 'node_modules/hyperframes']
    cache = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.cache')) / 'npm-cache/_npx'
    if cache.exists():
        candidates.extend(cache.glob('*/node_modules/hyperframes'))
    available = []
    for path in candidates:
        try:
            metadata = read(path / 'package.json')
            if metadata and (path / 'bin/hyperframes.mjs').exists():
                available.append((tuple(int(v) for v in metadata['version'].split('.')[:3]), path))
        except (ValueError, TypeError):
            pass
    if not available or not shutil.which('node'):
        raise RuntimeError('Install Node.js and HyperFrames to enable video export: npm install hyperframes')
    return max(available, key=lambda item: item[0])[1]


def fingerprint(book, numbers, audio, cast):
    payload = {'book': book, 'chapters': numbers, 'cast': cast,
               'tracks': {str(n): audio['tracks'][str(n)]['fingerprint'] for n in numbers}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def cast_for(job):
    from orchestrator import relevant_character_context
    return relevant_character_context(read(Path(job) / '08_Memory/psychology.json', {}), '', 8)


def status(job):
    job = Path(job)
    state = read(job / 'film/state.json', {'status': 'idle'})
    try:
        engine_path = engine()
        state['engine_available'] = True
        state['engine_version'] = read(engine_path / 'package.json')['version']
    except RuntimeError as error:
        state.update(engine_available=False, setup_message=str(error))
    if state.get('status') in ('building', 'rendering') and not worker_is_active(job / 'film'):
        state.update(status='interrupted', error='The video worker stopped. Build or render again to retry.')
    if state.get('status') == 'pending' and time.time() - state.get('updated_at', 0) > 30:
        state.update(status='interrupted', error='The video worker did not start. Try again.')
    if state.get('fingerprint'):
        try:
            book, audio = studio_data(job), audio_status(job)
            current = fingerprint(book, state['chapters'], audio, cast_for(job))
            if current != state['fingerprint']:
                state.update(status='stale', error='The manuscript, cast or narration changed. Build a fresh video project.')
        except (KeyError, ValueError):
            state.update(status='stale', error='Generate current narration before rebuilding this video.')
    return state


def prepare(job, data):
    job = Path(job)
    engine()
    action = data.get('action', 'build')
    if action not in ('build', 'render'):
        raise ValueError('Choose build or render.')
    book, audio = studio_data(job), audio_status(job)
    directory = job / 'film'
    directory.mkdir(exist_ok=True)
    with job_lock(directory):
        previous = status(job)
        if previous['status'] in ('pending', 'building', 'rendering'):
            raise ValueError('A video job is already running.')
        if action == 'render':
            if previous['status'] not in ('ready', 'completed', 'failed', 'interrupted') or not previous.get('validated') or not (directory / 'index.html').exists():
                raise ValueError('Build and preview a current video project before rendering.')
            numbers = previous['chapters']
        else:
            numbers = data.get('chapters')
            valid = {c['number'] for c in book['chapters']}
            if not isinstance(numbers, list) or not numbers or any(type(n) is not int or n not in valid for n in numbers):
                raise ValueError('Select completed chapters for the video.')
        if any(str(n) not in audio['tracks'] for n in numbers):
            raise ValueError('Generate narration for every selected chapter first in Manuscript Studio.')
        resolution = data.get('resolution', '1080p')
        if resolution not in ('1080p', '4k'):
            raise ValueError('Choose 1080p or 4K.')
        identity = fingerprint(book, sorted(set(numbers)), audio, cast_for(job))
        if action == 'render' and identity != previous.get('fingerprint'):
            raise ValueError('The book changed. Rebuild the video before rendering.')
        atomic_json(directory / 'state.json', {**previous, 'status': 'pending', 'action': action,
            'chapters': sorted(set(numbers)), 'resolution': resolution, 'fingerprint': identity,
            'error': None, 'updated_at': time.time()})


def launch(root, job):
    root, job = Path(root).resolve(), Path(job).resolve()
    with (job / 'film/worker.log').open('a', encoding='utf-8') as log:
        options = {'start_new_session': True} if os.name != 'nt' else {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS}
        return subprocess.Popen([sys.executable, '-u', str(root / 'athena.py'), 'film', '--job', job.name],
            cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **options)


def character_svg(name, index):
    hue = int(hashlib.sha256(name.encode()).hexdigest()[:4], 16) % 360
    return f'<svg viewBox="0 0 340 440" role="img" aria-label="Illustrated portrait of {escape(name, quote=True)}"><rect width="340" height="440" rx="160" fill="hsl({hue},22%,28%)"/><circle cx="170" cy="122" r="52" fill="#e3c7a7"/><path d="M112 112 Q111 41 174 48 Q236 50 226 118 Q195 93 164 83 Q146 108 112 112" fill="#252d31"/><path d="M68 398 Q54 229 127 204 L170 246 L213 204 Q286 237 272 398Z" fill="hsl({hue},32%,48%)"/><path d="M127 204 L170 246 L145 319 L96 255Z" fill="hsl({hue},24%,62%)"/><path d="M213 204 L170 246 L195 319 L245 255Z" fill="hsl({hue},24%,62%)"/><path d="M127 390 Q165 368 213 390" stroke="#e3c7a7" stroke-width="18" stroke-linecap="round" fill="none"/></svg>'


def build(job, state):
    job = Path(job); directory = job / 'film'; assets = directory / 'assets'
    assets.mkdir(exist_ok=True)
    book, audio, cast = studio_data(job), audio_status(job), cast_for(job)
    if not cast:
        cast = [{'name': 'Narrator', 'voice': 'The voice of the story'}]
    for index, person in enumerate(cast):
        (assets / f'character-{index}.svg').write_text(character_svg(person['name'], index), encoding='utf-8')
    engine_path = engine()
    shutil.copy2(engine_path / 'dist/hyperframes-player.global.js', directory / 'player.js')
    title = escape(book['title'])
    clips, captions, animation, storyboard = [], [], [], []
    clock = 0.0
    for chapter in book['chapters']:
        number = chapter['number']
        if number not in state['chapters']:
            continue
        track = audio['tracks'][str(number)]
        duration = track['duration']
        if duration <= 0:
            raise ValueError('Narration has no duration.')
        filename = f'chapter-{number:03d}.wav'
        shutil.copy2(job / 'audio' / track['filename'], assets / filename)
        clips.append(f'<audio id="audio-{number}" src="assets/{filename}" data-start="{clock:.5f}" data-duration="{duration:.5f}" data-track-index="3" data-volume="1"></audio>')
        # Reading cards span all prose. Timing is estimated from word shares;
        # these are reading cards, not word-aligned transcription captions.
        words = chapter['prose'].split()
        groups = [words[i:i+65] for i in range(0, len(words), 65)]
        offset = clock
        for index, group in enumerate(groups):
            length = duration * len(group) / len(words)
            key = f'c{number}-s{index}'
            text = ' '.join(group)
            relevant = [i for i,p in enumerate(cast) if p['name'].casefold() in text.casefold()]
            figures = relevant[:2] or [index % len(cast)]
            portraits = ''.join(f'<div class="portrait"><img src="assets/character-{i}.svg" alt="Illustrated character {escape(cast[i]["name"], quote=True)}"><p>{escape(cast[i]["name"])}</p></div>' for i in figures)
            clips.append(f'<section id="{key}" class="clip scene" data-start="{offset:.5f}" data-duration="{length:.5f}" data-track-index="0"><div class="stage"><div class="moon"></div><div class="arches"><i></i><i></i><i></i></div><div class="figures">{portraits}</div><div class="chapter"><p>CHAPTER {number:02d} · ILLUSTRATED READING</p><h1>{escape(chapter["title"])}</h1></div></div><div class="reading"><p>{escape(text)}</p></div></section>')
            animation.append(f'animate("#{key} .figures",[{{opacity:0}},{{opacity:1,offset:.12}},{{opacity:1,offset:.88}},{{opacity:0}}],{offset:.5f},{length:.5f});')
            animation.append(f'animate("#{key} .reading",[{{opacity:0}},{{opacity:1,offset:.08}},{{opacity:1,offset:.92}},{{opacity:0}}],{offset:.5f},{length:.5f});')
            storyboard.append({'chapter': number, 'card': index+1, 'start': round(offset,2), 'duration': round(length,2),
                               'characters': [cast[i]['name'] for i in figures], 'text': text})
            offset += length
        clock += duration
    style = '''*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;background:#101e24;color:#f4ebdb;font-family:serif}#root{width:100%;height:100%;position:relative;overflow:hidden}.scene{position:absolute;inset:0;display:grid;grid-template-columns:58% 42%;background:#101e24}.stage{position:relative;overflow:hidden;border-right:1px solid #7f735b}.moon{position:absolute;left:78px;top:64px;width:200px;height:200px;border-radius:50%;background:#d6c394}.arches{position:absolute;inset:200px 70px 100px;display:flex;gap:35px;opacity:.55}.arches i{flex:1;border:3px solid #729194;border-radius:180px 180px 0 0}.figures{position:absolute;inset:220px 80px 170px;display:flex;justify-content:center;align-items:end;gap:25px}.portrait{width:340px;flex-shrink:1;min-width:0;text-align:center}.portrait img{display:block;width:100%;max-height:440px}.portrait p{font:24px sans-serif;letter-spacing:1px;margin-top:22px}.chapter{position:absolute;bottom:48px;left:80px;right:70px}.chapter p{font:16px sans-serif;color:#d6c394;letter-spacing:3px}.chapter h1{font-size:48px;line-height:1.2;font-weight:400;margin:12px 0;overflow-wrap:anywhere}.reading{display:flex;align-items:center;padding:75px 72px}.reading p{font-size:38px;line-height:1.52;margin:0;overflow-wrap:anywhere}'''
    html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title><style>{style}</style></head><body><div id="root" data-composition-id="book-film" data-width="1920" data-height="1080" data-fps="30" data-duration="{clock:.5f}">{''.join(clips)}</div><script>function animate(selector,frames,start,duration){{const a=document.querySelector(selector).animate(frames,{{delay:start*1000,duration:duration*1000,iterations:1,fill:"both"}});a.pause();}}{''.join(animation)}</script></body></html>'''
    (directory / 'index.html').write_text(html, encoding='utf-8')
    (directory / 'preview.html').write_text('<!doctype html><html><head><meta charset="utf-8"><script src="player.js"></script><style>html,body{margin:0;background:#101e24;width:100%;height:100%}hyperframes-player{display:block;width:100%;height:100%}</style></head><body><hyperframes-player src="index.html" controls width="1920" height="1080"></hyperframes-player></body></html>', encoding='utf-8')
    atomic_json(directory / 'storyboard.json', {'title': book['title'], 'duration': clock, 'cast': cast, 'cards': storyboard,
        'style': 'Vector character portraits with motion and complete narrated reading cards', 'timing': 'Reading cards use estimated word-share timing.'})
    atomic_json(directory / 'hyperframes.json', {'name':'book-film','width':1920,'height':1080,'fps':30})
    atomic_json(directory / 'package.json', {'private':True,'scripts':{'render':f'hyperframes render . --resolution {state["resolution"]}'},
                'devDependencies':{'hyperframes':read(engine_path / 'package.json')['version']}})
    state.update(duration=round(clock,2), cards=len(storyboard), cast=[p['name'] for p in cast],
                 engine_version=read(engine_path / 'package.json')['version'])


def run(job):
    job = Path(job); directory = job / 'film'
    with job_lock(job), job_lock(directory):
        state = read(directory / 'state.json')
        try:
            state.update(status='building' if state['action']=='build' else 'rendering', updated_at=time.time())
            atomic_json(directory / 'state.json', state)
            engine_path = engine()
            command = [shutil.which('node'), str(engine_path / 'bin/hyperframes.mjs')]
            if state['action'] == 'build':
                state['validated'] = False
                build(job, state)
                result = subprocess.run(command + ['check', str(directory), '--json'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
                (directory / 'check.log').write_text(result.stdout + result.stderr, encoding='utf-8')
                if result.returncode:
                    raise RuntimeError('Video validation failed. See the studio render log for details.')
                state['status'] = 'ready'
                state['validated'] = True
            else:
                output = directory / 'film.mp4'
                temporary = directory / 'rendering.mp4'
                result = subprocess.run(command + ['render', str(directory), '--output', str(temporary),
                    '--resolution', state['resolution'], '--fps', '30', '--quality', 'delivery'], cwd=directory,
                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=86400)
                (directory / 'render.log').write_text(result.stdout + result.stderr, encoding='utf-8')
                if result.returncode or not temporary.exists() or not temporary.stat().st_size:
                    raise RuntimeError('Video render failed. See the studio render log and retry.')
                temporary.replace(output)
                state['status'] = 'completed'
                state['rendered_resolution'] = state['resolution']
            state.update(error=None, updated_at=time.time())
            atomic_json(directory / 'state.json', state)
        except BaseException as error:
            state.update(status='failed', error=str(error), updated_at=time.time())
            atomic_json(directory / 'state.json', state)
            raise
