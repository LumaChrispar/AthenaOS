'use strict';
const $ = id => document.getElementById(id);
const bookId = location.pathname.match(/\/books\/([0-9a-f]{32})\/studio/)[1];
const base = `/api/jobs/${bookId}`;
let token = '', book = null, current = 1, audioState = {tracks: {}}, playing = null, busy = false, polling = false, signature = '', submitted = false;
const node = (tag, text, className) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (className) n.className = className; return n; };
async function api(path, data) {
  const response = await fetch(path, data === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Athena-Token': token}, body: JSON.stringify(data)});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'The request failed.');
  return value;
}
function message(text, error = false) { $('message').textContent = text; $('message').classList.toggle('error', error); }
function tab(name) {
  for (const key of ['manuscript', 'masters', 'voices']) {
    $(`${key}-panel`).hidden = key !== name;
    $(`tab-${key}`).classList.toggle('active', key === name);
    $(`tab-${key}`).setAttribute('aria-pressed', String(key === name));
  }
}
function settings() {
  return {provider: $('speech-provider').value, base_url: $('speech-url').value.trim(), model: $('speech-model').value.trim(),
    voice: $('speech-voice').value.trim(), speed: Number($('speech-speed').value), timeout_seconds: Number($('speech-timeout').value)};
}
function voiceSummary() {
  const s = settings();
  $('engine-summary').textContent = `${s.provider === 'openai' ? 'OpenAI · cloud' : s.provider === 'kokoro' ? 'Kokoro · local' : 'Local speech server'} / ${s.model}`;
  $('voice-summary').textContent = s.voice; $('speed-summary').textContent = `${s.speed}×`;
  $('voice-options').replaceChildren(...(s.provider === 'openai' ? ['alloy', 'ash', 'coral', 'echo', 'fable', 'nova', 'onyx', 'sage', 'shimmer'] : ['af_heart', 'af_bella', 'af_sarah', 'am_adam', 'am_michael', 'bf_emma', 'bm_george']).map(v => { const n = document.createElement('option'); n.value = v; return n; }));
  $('provider-help').textContent = s.provider === 'openai'
    ? 'Cloud generation sends the selected manuscript to OpenAI and uses your account’s paid speech API. Save an OpenAI key in Athena Settings first.'
    : 'Start your local speech server before generating. For Kokoro-FastAPI, the usual address is http://127.0.0.1:8880/v1. Enter a voice supported by your server.';
}
function applySettings(s) {
  for (const [key, id] of Object.entries({provider:'speech-provider', base_url:'speech-url', model:'speech-model', voice:'speech-voice', speed:'speech-speed', timeout_seconds:'speech-timeout'})) $(id).value = s[key];
  voiceSummary();
}
function selectChapter(number) {
  current = number;
  const chapter = book.chapters.find(c => c.number === number);
  $('chapter-label').textContent = `CHAPTER ${number} · ${chapter.words.toLocaleString()} WORDS`;
  $('chapter-title').textContent = chapter.title;
  $('prose').replaceChildren(...chapter.prose.split(/\n\s*\n/).filter(p => p.trim()).map(p => node('p', p)));
  for (const button of $('chapters').children) {
    const active = Number(button.dataset.number) === number;
    button.classList.toggle('active', active); button.setAttribute('aria-current', String(active));
  }
}
function audioUrl(track) { return `${base}/audio/${track.filename}`; }
async function play(number) {
  const track = audioState.tracks[number];
  if (!track) { message('Generate this chapter first.'); return; }
  playing = Number(number); selectChapter(playing);
  $('playing-title').textContent = track.title; $('playing-voice').textContent = `AI narration · ${track.voice}`;
  $('audio').src = audioUrl(track); $('audio').playbackRate = Number($('playback-speed').value);
  try { await $('audio').play(); } catch { message('Press Play in the audio player to start listening.'); }
}
function step(direction) {
  const numbers = Object.keys(audioState.tracks).map(Number).sort((a,b) => a-b);
  const index = numbers.indexOf(playing);
  const number = numbers[index + direction];
  if (number !== undefined) play(number);
}
function renderAudio() {
  busy = submitted || ['pending', 'running'].includes(audioState.status);
  $('generate-book').disabled = $('generate-chapter').disabled = busy || !book;
  for (const input of $('voice-form').querySelectorAll('input,select,button')) input.disabled = busy;
  $('progress').max = audioState.total_chunks || 1; $('progress').value = audioState.completed_chunks || 0;
  $('progress-label').textContent = busy
    ? `${audioState.status === 'running' ? 'Narrating' : 'Queued'}${audioState.active_chapter ? ` chapter ${audioState.active_chapter}` : ''} · ${audioState.completed_chunks || 0} / ${audioState.total_chunks || '…'} chunks saved`
    : audioState.status === 'completed' ? 'Narration saved. Ready to listen.' : audioState.status === 'failed' || audioState.status === 'interrupted' ? 'Paused. Generate again to resume.' : 'Ready when you are.';
  if (audioState.error) message(audioState.error, true);
  $('master-download').hidden = !audioState.master;
  if (audioState.master) $('master-download').href = audioUrl(audioState.master);
  const nextSignature = JSON.stringify(audioState.tracks);
  for (const button of $('masters').querySelectorAll('button')) if (button.textContent === 'Generate chapter') button.disabled = busy;
  if (signature === nextSignature) return;
  signature = nextSignature; $('masters').replaceChildren();
  for (const chapter of book.chapters) {
    const track = audioState.tracks[chapter.number];
    const card = node('article', undefined, 'master-card');
    card.append(node('p', `CHAPTER ${chapter.number}`, 'eyebrow'), node('h3', chapter.title), node('p', track ? `${Math.floor(track.duration/60)}m ${Math.round(track.duration%60)}s · ${track.voice}` : 'Ready for narration', 'quiet'));
    const actions = node('div', undefined, 'actions'), action = node('button', track ? 'Play chapter' : 'Generate chapter', 'primary');
    action.onclick = () => track ? play(chapter.number) : generate([chapter.number]);
    action.disabled = !track && busy; actions.append(action);
    if (track) { const link = node('a', 'Download WAV ↓', 'outline'); link.href = audioUrl(track); link.download = ''; actions.append(link); }
    card.append(actions); $('masters').append(card);
  }
}
async function refresh() {
  if (polling || !book) return;
  polling = true;
  try { audioState = await api(base + '/audio-status'); renderAudio(); }
  catch (error) { message(error.message, true); }
  finally { polling = false; }
}
async function generate(numbers) {
  if (busy) return;
  if (!$('voice-form').reportValidity()) { tab('voices'); return; }
  submitted = true; renderAudio(); message('Queuing narration. Saved chunks will be reused when text and voice settings match.');
  try {
    await api(base + '/narrate', {settings: settings(), chapters: numbers});
    audioState = await api(base + '/audio-status');
    message('Narration started. You can keep reading or close this page.');
  } catch (error) { message(error.message, true); }
  finally { submitted = false; signature = ''; renderAudio(); }
}
for (const key of ['manuscript','masters','voices']) $(`tab-${key}`).onclick = () => tab(key);
$('open-voices').onclick = () => tab('voices');
$('generate-chapter').onclick = () => generate([current]);
$('generate-book').onclick = () => generate(book.chapters.map(c => c.number));
$('speech-provider').onchange = () => applySettings($('speech-provider').value === 'openai'
  ? {provider:'openai',base_url:'https://api.openai.com/v1',model:'gpt-4o-mini-tts',voice:'alloy',speed:1,timeout_seconds:300}
  : {provider:$('speech-provider').value,base_url:'http://127.0.0.1:8880/v1',model:'kokoro',voice:'af_heart',speed:1,timeout_seconds:300});
$('voice-form').oninput = voiceSummary;
$('voice-form').onsubmit = async event => {
  event.preventDefault(); $('save-voice').disabled = true;
  try { applySettings(await api('/api/narration-settings', settings())); message('Narration settings saved for your books.'); }
  catch (error) { message(error.message, true); }
  finally { $('save-voice').disabled = busy; }
};
$('previous').onclick = () => step(-1); $('next').onclick = () => step(1);
$('playback-speed').onchange = () => { $('audio').playbackRate = Number($('playback-speed').value); };
$('audio').onended = () => { if ($('auto-advance').checked) step(1); };
$('audio').onerror = () => message('This audio could not be played. Refresh the studio to check whether the manuscript changed.', true);
(async () => {
  try {
    token = (await api('/api/bootstrap')).token;
    book = await api(base + '/studio');
    applySettings(await api('/api/narration-settings'));
    document.title = `${book.title} · Audiobook studio`;
    $('title').textContent = $('cover-title').textContent = book.title;
    $('blurb').textContent = book.blurb || 'Your finished manuscript, ready to read and bring to life.';
    $('chapter-count').textContent = `${book.chapters.length} chapters`; $('word-count').textContent = `${book.words.toLocaleString()} words`;
    $('workflow').href = `/books/${bookId}?workspace=1`; $('manuscript-download').href = base + '/manuscript';
    for (const chapter of book.chapters) {
      const button = node('button'); button.dataset.number = chapter.number;
      button.append(node('small', `CHAPTER ${chapter.number}`), node('span', chapter.title));
      button.onclick = () => selectChapter(chapter.number); $('chapters').append(button);
    }
    selectChapter(book.chapters[0].number); await refresh(); setInterval(refresh, 2500);
  } catch (error) { message(error.message, true); $('title').textContent = 'The audiobook studio is not ready yet'; }
})();
