const $ = id => document.getElementById(id);
let token = '', selected = null, endpoints = {}, polling = false;
let savedSettings = null;
let activitySignature = '', conversationSignature = '';
const pendingReplies = new Set(), chatDrafts = new Map();
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
}
function title(job) { return job.metadata?.title || job.concept.slice(0, 65); }
function label(step) { return (step || 'Preparing your book').replaceAll('_', ' ').replace(/^\w/, c => c.toUpperCase()); }
async function selectBook(id, navigate = true) {
  if (selected) chatDrafts.set(selected, $('chat-input').value);
  selected = id; showView('detail', `/books/${id}`, navigate); $('reader').hidden = true;
  activitySignature = conversationSignature = '';
  $('activity-messages').replaceChildren(); $('chat-messages').replaceChildren();
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
  $('status').textContent = job.status; $('book-model').textContent = `${job.provider} / ${job.model}`;
  $('active-step').textContent = job.status === 'completed' ? 'Your manuscript is ready.' : label(job.active_step);
  $('progress-text').textContent = `${job.completed_steps.length} steps saved · Last update ${new Date((job.updated_at || job.created_at) * 1000).toLocaleString()}`;
  $('metrics').replaceChildren();
  for (const [value, name] of [[`${job.pipeline.last_completed_chapter || 0} / ${job.pipeline.total_chapters || job.chapters || '?'}`, 'Chapters completed'], [job.usage.calls || 0, 'Writing requests'], [job.chat_usage?.calls || 0, 'Chat requests'], [(job.usage.prompt_tokens || 0) + (job.usage.completion_tokens || 0), 'Writing tokens']]) {
    const item = document.createElement('div'), number = document.createElement('strong'); number.textContent = value; item.append(number, document.createTextNode(name)); $('metrics').append(item);
  }
  $('resume').hidden = $('resume-current').hidden = job.status === 'completed' || job.status === 'running';
  $('continue-book').hidden = job.status !== 'completed';
  $('edit-book').disabled = $('delete-book').disabled = job.status === 'running';
  $('download').hidden = $('read').hidden = !job.download_ready;
  $('download').href = `/api/jobs/${job.id}/manuscript`;
  $('log').textContent = job.log || 'Waiting for activity…'; $('job-id').textContent = `Book ID: ${job.id}`;
  renderMessages(job);
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
let editorBook = null, editorContent = null, continuationBook = null;
for (const button of document.querySelectorAll('[data-close]')) button.onclick = () => $(button.dataset.close).close();
$('resume-current').onclick = async () => {
  const id = selected; $('resume-current').disabled = true;
  try { await api(`/api/jobs/${id}/resume`, {use_current_settings: true}); notice('Resuming with your saved Settings. Completed work is kept.'); await refresh(); }
  catch (error) { notice(error.message, true); } finally { $('resume-current').disabled = false; }
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
(async () => { try { const settings = await api('/api/bootstrap'); token = settings.token; endpoints = settings.endpoints; applySettings(await api('/api/settings')); renderKeyStatus(await api('/api/openrouter-key')); await route(); await refresh(); setInterval(refresh, 3000); } catch (error) { notice(error.message, true); } })();
