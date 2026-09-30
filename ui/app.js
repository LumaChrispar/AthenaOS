const $ = id => document.getElementById(id);
let token = '', selected = null, endpoints = {}, polling = false;
let savedSettings = null;
let activitySignature = '', conversationSignature = '';
const pendingReplies = new Set(), chatDrafts = new Map();
let keyStatus = {configured: false, saved: false};
const TABS = ['writing', 'pipeline', 'log'];
let activeTab = 'writing', inspectSignature = '', logSignature = '', failureShown = false, inspecting = null;
const MODEL_GROUPS = [
  ['architecture-reasoning', 'Planning and continuity'],
  ['character-world-building', 'Characters and world'],
  ['prose-generation', 'Prose and editing'],
  ['voice-variation', 'Voice calibration'],
  ['analysis-critique', 'Analysis and critique'],
];
let fitRequest = 0;
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}
function showTab(name) {
  activeTab = TABS.includes(name) ? name : 'writing';
  for (const tab of TABS) {
    $(`tab-${tab}`).classList.toggle('active', tab === activeTab);
    $(`tab-${tab}`).setAttribute('aria-selected', String(tab === activeTab));
    $(`${tab}-panel`).hidden = tab !== activeTab;
  }
  if (activeTab === 'pipeline' && selected) loadInspector(selected);
}
function renderKeyStatus(status) {
  keyStatus = status;
  $('key-status').textContent = status.saved ? 'A key is saved securely. Leave the field blank to keep it, or paste a replacement.' : status.configured ? `Using a key from ${status.source}. You can save a replacement here.` : status.storage_error || 'No API key configured yet.';
  $('remove-key').hidden = !status.saved;
}
function clearKeyInput() { $('openrouter-key').value = ''; $('openrouter-key').type = 'password'; $('toggle-key').textContent = 'Show'; $('toggle-key').setAttribute('aria-pressed', 'false'); }
async function saveEnteredKey() {
  const key = $('openrouter-key').value.trim();
  if (!key) return;
  const status = await api('/api/openrouter-key', {action: 'save', key});
  clearKeyInput(); renderKeyStatus(status);
}
function notice(message, error = false) { $('notice').textContent = message; $('notice').className = error ? 'error' : ''; $('notice').hidden = !message; }
async function api(path, data) {
  const response = await fetch(path, data === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Athena-Token': token}, body: JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The request could not be completed.');
  return result;
}
function connection() { return {provider: $('provider').value, base_url: $('base-url').value, model: $('model').value.trim()}; }
function showView(view, path, navigate = true) {
  for (const name of ['create', 'settings', 'detail']) $(name + '-view').hidden = name !== view;
  $('new-book').classList.toggle('active', view === 'create');
  $('settings-link').classList.toggle('active', view === 'settings');
  if (navigate && location.pathname !== path) history.pushState({}, '', path);
  document.title = view === 'settings' ? 'Settings · Athena' : 'Athena · Writing studio';
  document.body.classList.remove('library-open'); $('toggle-library').setAttribute('aria-expanded', 'false');
}
function showCreate(navigate = true) { if (selected) chatDrafts.set(selected, $('chat-input').value); selected = null; showView('create', '/', navigate); notice(''); refresh(); }
function showSettings(navigate = true) { if (selected) chatDrafts.set(selected, $('chat-input').value); selected = null; showView('settings', '/settings', navigate); notice(''); refresh(); }
function applySettings(settings) {
  savedSettings = settings;
  $('provider').value = settings.provider; $('base-url').value = settings.base_url; $('model').value = settings.model;
  $('max-calls').value = settings.max_calls_per_job; $('max-tokens').value = settings.max_output_tokens; $('timeout').value = settings.timeout_seconds;
  connectionHelp();
  $('saved-model').textContent = settings.model ? `${settings.provider === 'lmstudio' ? 'LM Studio' : settings.provider === 'ollama' ? 'Ollama' : 'OpenRouter'} · ${settings.model}` : 'Choose your writing model in Settings to get started.';
  for (const [group] of MODEL_GROUPS) $(`role-${group}`).value = settings.role_models?.[group] || '';
  checkModelFit();
}
function initializeRoleInputs() {
  const root = $('role-models');
  for (const [group, name] of MODEL_GROUPS) {
    const wrap = el('div'), label = el('label', null, name), input = document.createElement('input'), note = el('small', 'hint');
    input.id = `role-${group}`; input.dataset.group = group; input.setAttribute('list', 'model-options');
    input.autocomplete = 'off'; input.placeholder = 'Use main model'; input.maxLength = 200;
    label.htmlFor = input.id; note.id = `fit-${group}`; note.textContent = 'Uses the main model';
    input.addEventListener('change', () => checkModelFit(input.value.trim(), note.id));
    wrap.append(label, input, note); root.append(wrap);
  }
}
async function checkModelFit(model = $('model').value.trim(), target = 'model-fit') {
  const node = $(target), request = ++fitRequest;
  if (!model) { node.textContent = target === 'model-fit' ? 'Choose a model to check its advertised limits.' : 'Uses the main model'; return; }
  node.textContent = 'Checking model limits…';
  try {
    const info = await api('/api/model-info', {...connection(), model});
    if (request !== fitRequest && target === 'model-fit') return;
    if (!info.available) { node.textContent = 'This server does not advertise model limits; Athena will use conservative defaults.'; return; }
    const details = [info.context_length ? `${formatNumber(info.context_length)} context` : '', info.max_output_tokens ? `${formatNumber(info.max_output_tokens)} max output` : ''].filter(Boolean).join(' · ');
    if (!details) { node.textContent = 'Model found; its context and output limits are not advertised.'; return; }
    const cap = target === 'model-fit' ? Number($('max-tokens').value) : 0;
    node.textContent = target === 'model-fit' && info.max_output_tokens && cap > info.max_output_tokens
      ? `${details}. Athena will cap responses to this model’s limit.` : details;
  } catch (error) { node.textContent = `Could not check model limits: ${error.message}`; }
}
function title(job) { return job.metadata?.title || job.concept.slice(0, 65); }
function label(step) { return (step || 'Preparing your book').replaceAll('_', ' ').replace(/^\w/, c => c.toUpperCase()); }
function elapsed(seconds) {
  const value = Math.max(0, Math.floor(seconds || 0));
  return value < 60 ? `${value}s` : `${Math.floor(value / 60)}m ${value % 60}s`;
}
async function selectBook(id, navigate = true) {
  if (selected) chatDrafts.set(selected, $('chat-input').value);
  selected = id; showView('detail', `/books/${id}`, navigate); $('reader').hidden = true;
  activitySignature = conversationSignature = '';
  inspectSignature = logSignature = ''; failureShown = false;
  $('activity-messages').replaceChildren(); $('chat-messages').replaceChildren();
  $('pipeline-view').replaceChildren(); $('log').textContent = 'Waiting for activity…';
  activeTab = 'writing'; showTab('writing');
  $('chat-input').value = chatDrafts.get(id) || '';
  $('book-title').textContent = 'Loading your book…'; notice(''); await refresh();
}
function renderMessages(job) {
  const scroller = $('thread-scroll');
  const nearBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 100;
  const activity = job.activity || [];
  const nextActivity = JSON.stringify(activity);
  if (activitySignature !== nextActivity) {
    $('activity-messages').replaceChildren();
    for (const update of activity) {
      const item = document.createElement('div'); item.className = `activity-message ${update.kind}`; item.textContent = update.text; $('activity-messages').append(item);
    }
    activitySignature = nextActivity;
  }
  const conversation = job.conversation || [], nextConversation = JSON.stringify(conversation);
  if (conversationSignature !== nextConversation) {
    $('chat-messages').replaceChildren();
    if (conversation.length) { const divider = document.createElement('p'); divider.className = 'chat-divider'; divider.textContent = 'OUR CONVERSATION'; $('chat-messages').append(divider); }
    for (const entry of conversation) {
      const message = document.createElement('article'), name = document.createElement('div'), body = document.createElement('div');
      message.className = 'message ' + (entry.role === 'user' ? 'user-message' : 'assistant-message') + (entry.role === 'error' ? ' chat-error' : '');
      name.className = 'message-label'; name.textContent = entry.role === 'user' ? 'You' : 'Athena';
      body.className = 'message-body'; body.textContent = entry.text; message.append(name, body); $('chat-messages').append(message);
    }
    conversationSignature = nextConversation;
  }
  $('chat-pending').hidden = !pendingReplies.has(job.id); $('send-chat').disabled = pendingReplies.has(job.id);
  if (nearBottom) scroller.scrollTop = scroller.scrollHeight;
}
function renderDetail(job) {
  $('book-title').textContent = title(job); $('book-concept').textContent = job.concept;
  $('status').textContent = job.status;
  const roleOverrides = Object.entries(job.role_models || {}).filter(([, model]) => model && model !== job.model);
  $('book-model').textContent = `${job.provider} / ${job.model}${roleOverrides.length ? ` · ${roleOverrides.length} role overrides` : ''}`;
  $('book-model').title = roleOverrides.map(([group, model]) => `${group}: ${model}`).join('\n');
  $('active-step').textContent = job.status === 'completed' ? 'Your manuscript is ready.' : label(job.active_step);
  const runningFor = job.status === 'running' && job.active_started_at ? (Date.now() / 1000 - job.active_started_at) : null;
  const stepTime = runningFor === null ? job.step_durations_seconds?.[job.active_step] : runningFor;
  const timing = stepTime === undefined || stepTime === null ? '' : ` · ${job.status === 'running' ? 'Running' : 'Last step'} ${elapsed(stepTime)}`;
  const attempt = job.status === 'running' && job.active_attempt > 1 ? ` · attempt ${job.active_attempt}/3` : '';
  $('progress-text').textContent = `${job.completed_steps.length} steps saved${timing}${attempt} · Last update ${new Date((job.updated_at || job.created_at) * 1000).toLocaleString()}`;
  $('metrics').replaceChildren();
  for (const [value, name] of [[`${job.pipeline.last_completed_chapter || 0} / ${job.pipeline.total_chapters || job.chapters || '?'}`, 'Chapters completed'], [job.usage.calls || 0, 'Writing requests'], [job.chat_usage?.calls || 0, 'Chat requests'], [(job.usage.prompt_tokens || 0) + (job.usage.completion_tokens || 0), 'Writing tokens']]) {
    const item = document.createElement('div'), number = document.createElement('strong'); number.textContent = value; item.append(number, document.createTextNode(name)); $('metrics').append(item);
  }
  $('resume').hidden = $('resume-current').hidden = job.status === 'completed' || job.status === 'running';
  $('resume-safer').hidden = job.status !== 'failed';
  $('continue-book').hidden = job.status !== 'completed';
  $('edit-book').disabled = $('delete-book').disabled = job.status === 'running';
  $('download').hidden = $('read').hidden = !job.download_ready;
  $('download').href = `/api/jobs/${job.id}/manuscript`;
  $('job-id').textContent = `Book ID: ${job.id}`;
  renderLog(job);
  // Switch a failed run to the Pipeline tab once, so the reason is on screen
  // without a click — then leave the tab alone and let the reader drive it.
  if (job.status === 'failed' && job.error && !failureShown) { failureShown = true; showTab('pipeline'); }
  if (activeTab === 'pipeline') loadInspector(job.id);
  renderMessages(job);
}
const LOG_ERROR = /Error|Warning|ESCALATION|\[RETRY|Job stopped|model-call limit/i;
const LOG_EVENT = /^(---\s|\[SRV-|Saved |Event emitted|Phase |Chapter |Intake |Voice |Rolling |Copy edit|ESCALATION|PIPELINE)/;
function renderLog(job) {
  const text = job.log || 'Waiting for activity…';
  if (text === logSignature) return;
  logSignature = text;
  const box = $('log');
  box.replaceChildren();
  for (const line of text.split('\n')) {
    const kind = LOG_ERROR.test(line) ? 'log-error' : LOG_EVENT.test(line) ? 'log-event' : '';
    box.append(el('span', kind ? `log-line ${kind}` : 'log-line', line));
  }
  box.scrollTop = box.scrollHeight;
}

const formatNumber = value => (value || 0).toLocaleString();
const kib = bytes => bytes >= 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${bytes} B`;
function section(title, note) {
  const wrap = el('section', 'pipe-section');
  const head = el('h3', 'pipe-heading', title);
  if (note) head.append(el('span', 'pipe-note', note));
  wrap.append(head);
  return wrap;
}
function definition(list, label, value) {
  list.append(el('dt', null, label), el('dd', null, value));
}
async function loadInspector(id) {
  if (inspecting === id) return;
  inspecting = id;
  try {
    const detail = await api(`/api/jobs/${id}/inspect`);
    if (selected !== id) return;
    const signature = JSON.stringify([detail.stages, detail.outline, detail.artifacts, detail.context, detail.budget, detail.chapter, detail.events.length]);
    if (signature !== inspectSignature) { inspectSignature = signature; renderInspector(detail); }
  } catch (error) {
    if (selected === id) { inspectSignature = ''; $('pipeline-view').replaceChildren(el('p', 'hint', error.message)); }
  } finally { inspecting = null; }
}
function renderInspector(detail) {
  const root = $('pipeline-view');
  root.replaceChildren();
  if (detail.error) {
    const banner = el('div', 'pipe-error');
    banner.append(el('strong', null, 'Stopped'), el('span', null, detail.error));
    root.append(banner);
  }

  // Stages
  const stages = section('Pipeline', `${detail.completed_steps.length} steps saved`);
  const rail = el('ol', 'stage-rail');
  for (const stage of detail.stages) {
    const row = el('li', `stage ${stage.status}`);
    row.append(el('span', 'stage-dot'));
    const body = el('div', 'stage-body');
    const title = el('div', 'stage-title');
    title.append(el('span', 'stage-label', stage.label), el('code', 'stage-service', stage.service));
    const duration = stage.duration_seconds === null || stage.duration_seconds === undefined ? '' : ` · ${elapsed(stage.duration_seconds)}`;
    body.append(title, el('p', 'stage-note', stage.note + duration), el('p', 'stage-artifact', stage.artifact));
    row.append(body);
    rail.append(row);
  }
  stages.append(rail);
  root.append(stages);

  // Context budget — the request that most often fails on a small local model.
  const context = detail.context;
  const ctx = section('Context budget', context.chapter ? `chapter ${context.chapter} draft request` : 'not yet measurable');
  const table = el('table', 'pipe-table');
  for (const row of context.rows) {
    const tr = el('tr');
    tr.append(el('td', null, row.label), el('td', 'num', formatNumber(row.tokens)), el('td', 'num muted', kib(row.bytes)));
    table.append(tr);
  }
  const promptTotal = el('tr', 'total');
  promptTotal.append(el('td', null, 'Prompt total'), el('td', 'num', formatNumber(context.prompt_tokens)), el('td', 'num muted', ''));
  const outputRow = el('tr', 'total');
  outputRow.append(el('td', null, 'Max output tokens'), el('td', 'num', formatNumber(context.output_tokens)), el('td', 'num muted', 'setting'));
  const neededRow = el('tr', 'grand');
  neededRow.append(el('td', null, 'Context needed'), el('td', 'num', formatNumber(context.context_needed)), el('td', 'num muted', 'tokens'));
  table.append(promptTotal, outputRow, neededRow);
  ctx.append(el('p', 'pipe-caption', 'What one prose request sends and expects back. Measured from the files on disk.'), table, el('p', 'pipe-advice', context.advice));
  if (context.preview?.length) {
    const preview = document.createElement('details'); preview.className = 'prompt-preview';
    preview.append(el('summary', null, 'Preview prompt inputs'));
    preview.append(el('p', 'pipe-caption', 'Read-only excerpts from the files used in the next chapter draft request. Long inputs are shortened here.'));
    for (const part of context.preview) {
      const item = document.createElement('details'); item.className = 'prompt-part';
      item.append(el('summary', null, `${part.label} · ${kib(part.bytes)}`));
      const pre = document.createElement('pre'); pre.textContent = part.text; item.append(pre); preview.append(item);
    }
    ctx.append(preview);
  }
  root.append(ctx);

  // Beat sheet
  if (detail.outline) {
    const beats = section('Beat sheet', `${detail.outline.acts.length} acts · ${detail.outline.chapters} chapters`);
    if (detail.outline.title) beats.append(el('p', 'pipe-title', detail.outline.title));
    for (const act of detail.outline.acts) {
      const block = el('div', 'act');
      block.append(el('h4', null, `Act ${act.act}${act.name ? ' · ' + act.name : ''}`));
      for (const beat of act.beats) {
        const row = el('div', `beat ${beat.status}`);
        row.append(el('span', 'beat-number', String(beat.chapter)));
        const text = el('div', 'beat-body');
        text.append(el('p', 'beat-goal', beat.goal));
        if (beat.conflict) text.append(el('p', 'beat-detail', `Conflict: ${beat.conflict}`));
        if (beat.outcome) text.append(el('p', 'beat-detail', `Outcome: ${beat.outcome}`));
        row.append(text);
        block.append(row);
      }
      beats.append(block);
    }
    root.append(beats);
  }

  // Chapter passes
  const chapter = detail.chapter;
  if (chapter && chapter.passed.length) {
    const passes = section(`Chapter ${context.chapter} passes`,
      chapter.attempt ? `attempt ${chapter.attempt.current} of ${chapter.attempt.of}` : 'from the worker log');
    const list = el('ul', 'pass-list');
    for (const pass of chapter.passed) {
      const item = el('li');
      item.append(el('span', 'pass-label', pass.label), el('code', 'stage-service', pass.service));
      if (pass.runs > 1) item.append(el('span', 'pass-runs', `×${pass.runs}`));
      list.append(item);
    }
    passes.append(list);
    if (chapter.retried) passes.append(el('p', 'pipe-advice', 'A pass ran more than once: the worker retried this chapter without advancing its revision attempt.'));
    root.append(passes);
  }

  // Call budget
  const budget = detail.budget;
  const calls = section('Model calls', `${formatNumber(budget.calls)} of ${formatNumber(budget.cap)} used`);
  const meter = el('progress', budget.warn ? 'meter warn' : 'meter');
  meter.max = budget.cap; meter.value = budget.calls;
  meter.setAttribute('aria-label', `${formatNumber(budget.calls)} of ${formatNumber(budget.cap)} model calls used`);
  calls.append(meter);
  const totals = el('dl', 'pipe-defs');
  definition(totals, 'Prompt tokens', formatNumber(budget.prompt_tokens));
  definition(totals, 'Completion tokens', formatNumber(budget.completion_tokens));
  definition(totals, 'Total tokens', formatNumber(budget.prompt_tokens + budget.completion_tokens));
  calls.append(totals);
  if (Object.keys(budget.by_service || {}).length) {
    const table = document.createElement('table'); table.className = 'pipe-table service-usage';
    const head = document.createElement('tr');
    for (const title of ['Service', 'Calls', 'Tokens', 'Response time']) head.append(el('th', null, title));
    table.append(head);
    for (const [service, row] of Object.entries(budget.by_service)) {
      const tr = document.createElement('tr');
      tr.append(el('td', null, service), el('td', 'num', formatNumber(row.calls)),
        el('td', 'num', formatNumber(row.prompt_tokens + row.completion_tokens)),
        el('td', 'num', elapsed(row.response_seconds)));
      table.append(tr);
    }
    calls.append(table);
  }
  if (budget.warn) calls.append(el('p', 'pipe-advice', 'This book is close to its per-book call limit. Raise it in Settings before resuming, or the worker will stop.'));
  root.append(calls);

  // Artifacts
  const files = detail.artifacts;
  const arts = section('Artifacts', `${files.length} saved`);
  const list = el('ul', 'artifact-list');
  for (const file of files) {
    const item = el('li', `artifact ${file.group}`);
    item.append(el('span', 'artifact-name', file.name), el('span', 'artifact-size', kib(file.bytes)));
    if (file.group !== 'raw') {
      const view = el('button', 'link-button', 'view');
      view.onclick = () => showArtifact(detail.id, file.name, view);
      item.append(view);
    }
    list.append(item);
  }
  arts.append(list);
  if (files.some(file => file.group === 'raw')) arts.append(el('p', 'pipe-advice', 'Files marked raw are the exact model output that failed to parse. They are kept for debugging.'));
  root.append(arts);

  // Events
  if (detail.events.length) {
    const log = section('Events', `${detail.events.length} in the recent log`);
    const lines = el('ul', 'event-list');
    for (const event of detail.events) lines.append(el('li', 'event-line', event.text));
    log.append(lines);
    if (detail.log_truncated) log.append(el('p', 'pipe-caption', 'Only the most recent part of the log is shown.'));
    root.append(log);
  }
}
let viewing = null;
async function showArtifact(id, name, button) {
  const viewer = $('artifact-viewer');
  if (viewing === name) { viewer.hidden = true; viewing = null; button.textContent = 'view'; return; }
  button.disabled = true; button.textContent = 'loading…';
  try {
    const response = await fetch(`/api/jobs/${id}/artifact/${encodeURIComponent(name)}`);
    if (!response.ok) throw new Error((await response.json()).error || 'That artifact could not be read.');
    viewer.textContent = await response.text();
    viewer.hidden = false; viewing = name; button.textContent = 'hide';
  } catch (error) { notice(error.message, true); button.textContent = 'view'; }
  finally { button.disabled = false; }
}
async function refresh() {
  if (polling) return;
  polling = true;
  try {
    const jobs = await api('/api/jobs'); $('book-count').textContent = jobs.length; $('books').replaceChildren();
    if (!jobs.length) { const empty = document.createElement('p'); empty.className = 'muted'; empty.textContent = 'Your stories will appear here.'; $('books').append(empty); }
    for (const job of jobs) {
      const button = document.createElement('button'); button.className = 'book-item' + (selected === job.id ? ' selected' : ''); button.textContent = title(job);
      const status = document.createElement('small'); status.textContent = job.status; button.append(status); button.onclick = () => selectBook(job.id); $('books').append(button);
    }
    const id = selected;
    if (id) { const job = await api(`/api/jobs/${id}`); if (selected === id) renderDetail(job); }
  } catch (error) { notice(error.message, true); } finally { polling = false; }
}
$('new-book').onclick = () => showCreate();
for (const tab of TABS) $(`tab-${tab}`).onclick = () => showTab(tab);
for (const id of ['settings-link', 'configure-model']) $(id).onclick = event => { event.preventDefault(); showSettings(); };
function route() {
  const book = location.pathname.match(/^\/books\/([0-9a-f]{32})$/);
  if (book) return selectBook(book[1], false);
  if (location.pathname === '/settings') showSettings(false); else showCreate(false);
}
window.onpopstate = route;
$('toggle-library').onclick = () => { const open = document.body.classList.toggle('library-open'); $('toggle-library').setAttribute('aria-expanded', String(open)); };
for (const button of document.querySelectorAll('[data-prompt]')) button.onclick = () => { $('concept').value = button.dataset.prompt; $('concept').focus(); };
for (const [input, form] of [['concept', 'book-form'], ['chat-input', 'chat-form']]) $(input).onkeydown = event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); if (form !== 'chat-form' || !pendingReplies.has(selected)) $(form).requestSubmit(); }
};
$('chat-form').onsubmit = async event => {
  event.preventDefault(); const id = selected, message = $('chat-input').value.trim();
  if (!id || !message || pendingReplies.has(id)) return;
  pendingReplies.add(id); $('send-chat').disabled = true; $('chat-pending').hidden = false;
  $('thread-scroll').scrollTop = $('thread-scroll').scrollHeight;
  try {
    await api(`/api/jobs/${id}/messages`, {message});
    chatDrafts.delete(id);
    if (selected === id) { $('chat-input').value = ''; await refresh(); }
  } catch (error) { if (selected === id) notice(error.message, true); }
  finally {
    pendingReplies.delete(id);
    if (selected === id) { $('send-chat').disabled = false; $('chat-pending').hidden = true; }
  }
};
function connectionHelp() {
  $('base-url').readOnly = $('provider').value === 'openrouter';
  $('openrouter-key-panel').hidden = $('provider').value !== 'openrouter';
  $('connection-help').textContent = $('provider').value === 'openrouter' ? 'Save your API key above, then find and choose a model. Cloud generation may incur charges.' : $('provider').value === 'lmstudio' ? 'Load a model and start the server in LM Studio’s Developer tab. If authentication is enabled, set LM_STUDIO_API_KEY before launching Athena.' : 'Start Ollama and download a model, then select Find models. Choose an installed local model for on-device generation.';
}
$('provider').onchange = () => {
  clearKeyInput();
  $('base-url').value = endpoints[$('provider').value]; $('model').value = ''; $('model-options').replaceChildren();
  for (const [group] of MODEL_GROUPS) $(`role-${group}`).value = '';
  connectionHelp();
  checkModelFit();
};
$('model').addEventListener('change', () => checkModelFit());
$('max-tokens').addEventListener('input', () => checkModelFit());
$('connect').onclick = async () => {
  $('connect').disabled = true; notice('Connecting to your model server…');
  try {
    const {models} = await api('/api/models', connection()); $('model-options').replaceChildren();
    for (const model of models) { const option = document.createElement('option'); option.value = model; $('model-options').append(option); }
    if (models.length && !$('model').value) $('model').value = models[0];
    notice(models.length ? `Connected. ${models.length} model${models.length === 1 ? '' : 's'} available. Choose one in the Model field.` : 'Connected, but no models were listed. Download or load a model in your server first.');
  } catch (error) { notice(`Could not connect. Check that your model server is running. ${error.message}`, true); } finally { $('connect').disabled = false; }
};
$('book-form').onsubmit = async event => {
  event.preventDefault(); $('start').disabled = true;
  try {
    if (!savedSettings?.model) { showSettings(); notice('Choose a writing model and save your settings first. Your story description is kept here.'); return; }
    const job = await api('/api/jobs', {concept: $('concept').value, chapters: $('chapters').value ? Number($('chapters').value) : null});
    await selectBook(job.id); notice('Your book worker has started. Progress updates automatically.');
  } catch (error) { notice(error.message, true); } finally { $('start').disabled = false; }
};
$('settings-form').onsubmit = async event => {
  event.preventDefault(); $('save-settings').disabled = true;
  try {
    if ($('provider').value === 'openrouter') await saveEnteredKey();
    const role_models = Object.fromEntries(MODEL_GROUPS.map(([group]) => [group, $(`role-${group}`).value.trim()]));
    const settings = await api('/api/settings', {...connection(), role_models, max_calls_per_job: Number($('max-calls').value), max_output_tokens: Number($('max-tokens').value), timeout_seconds: Number($('timeout').value)});
    applySettings(settings); notice('Settings saved. New books will use this configuration.');
  } catch (error) { notice(error.message, true); } finally { $('save-settings').disabled = false; }
};
$('toggle-key').onclick = () => {
  const show = $('openrouter-key').type === 'password';
  $('openrouter-key').type = show ? 'text' : 'password'; $('toggle-key').textContent = show ? 'Hide' : 'Show'; $('toggle-key').setAttribute('aria-pressed', String(show));
};
for (const [id, action] of [['save-key', 'save'], ['test-key', 'test'], ['remove-key', 'remove']]) {
  $(id).onclick = async () => {
    for (const button of ['save-key', 'test-key', 'remove-key']) $(button).disabled = true;
    try {
      if (action === 'save') {
        if (!$('openrouter-key').value.trim()) throw new Error('Paste your API key first.');
        await saveEnteredKey(); notice('API key saved securely. You can now find models.');
      } else if (action === 'test') {
        const result = await api('/api/openrouter-key', {action, key: $('openrouter-key').value.trim() || undefined});
        notice(result.message + ($('openrouter-key').value.trim() ? ' Select Save key to keep it.' : ''));
      } else {
        renderKeyStatus(await api('/api/openrouter-key', {action})); clearKeyInput();
        notice(keyStatus.configured ? `Saved key removed. Athena is using the key from ${keyStatus.source}.` : 'Saved API key removed from this computer.');
      }
    } catch (error) { notice(error.message, true); }
    finally { for (const button of ['save-key', 'test-key', 'remove-key']) $(button).disabled = false; }
  };
}
$('resume').onclick = async () => {
  $('resume').disabled = true;
  try { await api(`/api/jobs/${selected}/resume`, {}); notice('Resume requested. An already-running worker will continue unchanged.'); await refresh(); }
  catch (error) { notice(error.message, true); } finally { $('resume').disabled = false; }
};
let editorBook = null, editorContent = null, continuationBook = null;
for (const button of document.querySelectorAll('[data-close]')) button.onclick = () => $(button.dataset.close).close();
$('resume-current').onclick = async () => {
  const id = selected; $('resume-current').disabled = true;
  try { await api(`/api/jobs/${id}/resume`, {use_current_settings: true}); notice('Resuming with your saved Settings. Completed work is kept.'); await refresh(); }
  catch (error) { notice(error.message, true); } finally { $('resume-current').disabled = false; }
};
$('resume-safer').onclick = async () => {
  const id = selected; $('resume-safer').disabled = true;
  try { await api(`/api/jobs/${id}/resume`, {use_current_settings: true, safer_limits: true}); notice('Resuming with current Settings and a 4,096-token response cap. Completed work is kept.'); await refresh(); }
  catch (error) { notice(error.message, true); } finally { $('resume-safer').disabled = false; }
};
$('delete-book').onclick = async () => {
  const id = selected;
  if (!confirm('Move this book to Trash? You can restore it later.')) return;
  try { await api(`/api/jobs/${id}/delete`, {}); showCreate(); notice('Book moved to Trash.'); }
  catch (error) { notice(error.message, true); }
};
$('open-trash').onclick = async () => {
  try {
    const jobs = await api('/api/trash'); $('trash-books').replaceChildren();
    if (!jobs.length) $('trash-books').textContent = 'No deleted books.';
    for (const job of jobs) {
      const row = document.createElement('div'), name = document.createElement('p'), button = document.createElement('button');
      name.textContent = title(job); button.textContent = 'Restore'; button.className = 'secondary';
      button.onclick = async () => { try { await api(`/api/jobs/${job.id}/restore`, {}); $('trash-dialog').close(); await selectBook(job.id); } catch (error) { alert(error.message); } };
      row.append(name, button); $('trash-books').append(row);
    }
    $('trash-dialog').showModal();
  } catch (error) { notice(error.message, true); }
};
function loadEditorChapter() {
  $('edit-chapter').disabled = false;
  const brief = $('edit-chapter').value === 'brief';
  const chapter = editorContent.chapters.find(c => c.number === Number($('edit-chapter').value));
  $('edit-title').disabled = brief; $('edit-title').value = chapter?.title || '';
  $('edit-text').maxLength = brief ? 30000 : 500000;
  $('edit-text').value = brief ? editorContent.concept : chapter?.prose || '';
}
$('edit-book').onclick = async () => {
  const id = selected;
  try {
    const content = await api(`/api/jobs/${id}/editor`);
    if (id !== selected) return;
    if (!content.can_edit_brief && !content.chapters.length) throw new Error('There are no finished chapters to edit yet. Resume writing to finish the first chapter.');
    editorBook = id; editorContent = content; $('edit-chapter').replaceChildren();
    const choices = content.chapters.map(c => [c.number, `Chapter ${c.number}: ${c.title}`]);
    if (content.can_edit_brief) choices.unshift(['brief', 'Book description']);
    for (const [value, name] of choices) { const option = document.createElement('option'); option.value = value; option.textContent = name; $('edit-chapter').append(option); }
    loadEditorChapter(); $('editor-dialog').showModal();
  } catch (error) { notice(error.message, true); }
};
$('edit-chapter').onchange = loadEditorChapter;
for (const id of ['edit-text', 'edit-title']) $(id).oninput = () => { $('edit-chapter').disabled = true; };
$('editor-form').onsubmit = async event => {
  event.preventDefault(); $('save-edit').disabled = true;
  try {
    const brief = $('edit-chapter').value === 'brief';
    await api(`/api/jobs/${editorBook}/edit`, {kind: brief ? 'brief' : 'chapter', number: Number($('edit-chapter').value), title: $('edit-title').value, text: $('edit-text').value});
    $('editor-dialog').close(); $('reader').hidden = true; notice('Changes saved. An earlier version is kept in the book’s revisions folder.'); await refresh();
  } catch (error) { alert(error.message); } finally { $('save-edit').disabled = false; }
};
$('continue-book').onclick = () => { continuationBook = selected; $('continuation-text').value = ''; $('continue-dialog').showModal(); };
$('continue-form').onsubmit = async event => {
  event.preventDefault(); $('start-continuation').disabled = true;
  try { await api(`/api/jobs/${continuationBook}/continue`, {instructions: $('continuation-text').value, chapters: Number($('extra-chapters').value)}); $('continue-dialog').close(); notice('Athena is continuing your story.'); await refresh(); }
  catch (error) { alert(error.message); } finally { $('start-continuation').disabled = false; }
};
$('read').onclick = async () => {
  const id = selected; $('read').disabled = true;
  try { const response = await fetch(`/api/jobs/${id}/manuscript`); if (!response.ok) throw new Error('Manuscript is not available yet.'); const text = await response.text(); if (id === selected) { $('manuscript').textContent = text; $('reader').hidden = false; } }
  catch (error) { notice(error.message, true); } finally { $('read').disabled = false; }
};
(async () => { try { initializeRoleInputs(); const settings = await api('/api/bootstrap'); token = settings.token; endpoints = settings.endpoints; applySettings(await api('/api/settings')); renderKeyStatus(await api('/api/openrouter-key')); await route(); await refresh(); setInterval(refresh, 3000); } catch (error) { notice(error.message, true); } })();
