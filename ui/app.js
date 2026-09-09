const $ = id => document.getElementById(id);
let token = '', selected = null, endpoints = {}, polling = false;
let savedSettings = null;
let keyStatus = {configured: false, saved: false};
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
}
function showCreate(navigate = true) { selected = null; showView('create', '/', navigate); notice(''); refresh(); }
function showSettings(navigate = true) { selected = null; showView('settings', '/settings', navigate); notice(''); refresh(); }
function applySettings(settings) {
  savedSettings = settings;
  $('provider').value = settings.provider; $('base-url').value = settings.base_url; $('model').value = settings.model;
  $('max-calls').value = settings.max_calls_per_job; $('max-tokens').value = settings.max_output_tokens; $('timeout').value = settings.timeout_seconds;
  connectionHelp();
  $('saved-model').textContent = settings.model ? `${settings.provider === 'lmstudio' ? 'LM Studio' : settings.provider === 'ollama' ? 'Ollama' : 'OpenRouter'} · ${settings.model}` : 'Choose your writing model in Settings to get started.';
}
function title(job) { return job.metadata?.title || job.concept.slice(0, 65); }
function label(step) { return (step || 'Preparing your book').replaceAll('_', ' ').replace(/^\w/, c => c.toUpperCase()); }
async function selectBook(id) {
  selected = id; showView('detail', '/'); $('reader').hidden = true;
  $('book-title').textContent = 'Loading your book…'; notice(''); await refresh();
}
function renderDetail(job) {
  $('book-title').textContent = title(job); $('book-concept').textContent = job.concept;
  $('status').textContent = job.status; $('book-model').textContent = `${job.provider} / ${job.model}`;
  $('active-step').textContent = job.status === 'completed' ? 'Your manuscript is ready.' : label(job.active_step);
  $('progress-text').textContent = `${job.completed_steps.length} steps saved · Last update ${new Date((job.updated_at || job.created_at) * 1000).toLocaleString()}`;
  $('metrics').replaceChildren();
  for (const [value, name] of [[`${job.pipeline.last_completed_chapter || 0} / ${job.pipeline.total_chapters || '?'}`, 'Chapters completed'], [job.usage.calls || 0, 'Model requests'], [(job.usage.prompt_tokens || 0) + (job.usage.completion_tokens || 0), 'Reported tokens']]) {
    const item = document.createElement('div'), number = document.createElement('strong'); number.textContent = value; item.append(number, document.createTextNode(name)); $('metrics').append(item);
  }
  $('job-error').hidden = !job.error; $('job-error').textContent = job.error || '';
  $('resume').hidden = job.status === 'completed';
  $('download').hidden = $('read').hidden = !job.download_ready;
  $('download').href = `/api/jobs/${job.id}/manuscript`;
  $('log').textContent = job.log || 'Waiting for activity…'; $('job-id').textContent = `Book ID: ${job.id}`;
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
for (const id of ['settings-link', 'configure-model']) $(id).onclick = event => { event.preventDefault(); showSettings(); };
window.onpopstate = () => location.pathname === '/settings' ? showSettings(false) : showCreate(false);
function connectionHelp() {
  $('base-url').readOnly = $('provider').value === 'openrouter';
  $('openrouter-key-panel').hidden = $('provider').value !== 'openrouter';
  $('connection-help').textContent = $('provider').value === 'openrouter' ? 'Save your API key above, then find and choose a model. Cloud generation may incur charges.' : $('provider').value === 'lmstudio' ? 'Load a model and start the server in LM Studio’s Developer tab. If authentication is enabled, set LM_STUDIO_API_KEY before launching Athena.' : 'Start Ollama and download a model, then select Find models. Choose an installed local model for on-device generation.';
}
$('provider').onchange = () => {
  clearKeyInput();
  $('base-url').value = endpoints[$('provider').value]; $('model').value = ''; $('model-options').replaceChildren();
  connectionHelp();
};
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
    const settings = await api('/api/settings', {...connection(), max_calls_per_job: Number($('max-calls').value), max_output_tokens: Number($('max-tokens').value), timeout_seconds: Number($('timeout').value)});
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
$('read').onclick = async () => {
  const id = selected; $('read').disabled = true;
  try { const response = await fetch(`/api/jobs/${id}/manuscript`); if (!response.ok) throw new Error('Manuscript is not available yet.'); const text = await response.text(); if (id === selected) { $('manuscript').textContent = text; $('reader').hidden = false; } }
  catch (error) { notice(error.message, true); } finally { $('read').disabled = false; }
};
(async () => { try { const settings = await api('/api/bootstrap'); token = settings.token; endpoints = settings.endpoints; applySettings(await api('/api/settings')); renderKeyStatus(await api('/api/openrouter-key')); showView(location.pathname === '/settings' ? 'settings' : 'create', location.pathname, false); await refresh(); setInterval(refresh, 3000); } catch (error) { notice(error.message, true); } })();
