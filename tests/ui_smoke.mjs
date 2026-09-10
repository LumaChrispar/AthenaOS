// Run against an active UI: node tests/ui_smoke.mjs [URL] [Chrome executable]
// Uses Chrome's debugging protocol and Node built-ins; no npm dependencies.
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, writeFile, mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import assert from 'node:assert/strict';

const url = process.argv[2] || 'http://127.0.0.1:8765';
assert.ok(['127.0.0.1', 'localhost'].includes(new URL(url).hostname), 'This smoke test only opens the local Athena UI');
const executable = process.argv[3] || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const profile = await mkdtemp(join(tmpdir(), 'athena-ui-smoke-'));
const chrome = spawn(executable, ['--headless=new', '--disable-gpu', '--in-process-gpu', '--no-sandbox', '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'], {windowsHide: true, stdio: ['ignore', 'ignore', 'pipe']});
// A temporary profile and local-only target isolate this test; --no-sandbox
// permits Chrome renderer startup inside restricted Windows agent environments.
let chromeDiagnostics = '';
chrome.stderr.on('data', data => { chromeDiagnostics += data.toString(); });
chrome.on('error', error => { console.error(error.message); process.exitCode = 1; });
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
let socket;
try {
  let port;
  for (let i = 0; i < 100; i++) {
    try { port = (await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; break; } catch { await sleep(100); }
  }
  assert.ok(port, 'Chrome debugging endpoint started');
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(pages.find(page => page.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let next = 1;
  const pending = new Map(), errors = [];
  socket.onclose = event => { for (const {reject} of pending.values()) reject(new Error(`Chrome connection closed: ${event.code} ${event.reason}`)); };
  socket.onmessage = event => {
    const value = JSON.parse(event.data);
    if (value.method === 'Runtime.exceptionThrown') errors.push(value.params.exceptionDetails.text);
    if (pending.has(value.id)) { const {resolve, reject} = pending.get(value.id); pending.delete(value.id); value.error ? reject(new Error(value.error.message)) : resolve(value.result); }
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = next++, timer = setTimeout(() => { pending.delete(id); reject(new Error(`Chrome timeout: ${method}`)); }, 10000);
    pending.set(id, {resolve: value => { clearTimeout(timer); resolve(value); }, reject: error => { clearTimeout(timer); reject(error); }});
    socket.send(JSON.stringify({id, method, params}));
  });
  const evaluate = async expression => {
    const result = await send('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  await send('Runtime.enable'); await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', {width: 1440, height: 1200, deviceScaleFactor: 1, mobile: false});
  await send('Page.navigate', {url});
  for (let i = 0; i < 50; i++) { if (await evaluate('typeof savedSettings !== "undefined" && savedSettings !== null')) break; await sleep(100); }
  assert.equal(await evaluate('typeof token !== "undefined" && token.length > 0'), true, 'UI session initialized');
  assert.equal(await evaluate('document.title'), 'Athena · Writing studio');
  assert.equal(await evaluate('document.getElementById("settings-view").hidden'), true);
  await evaluate('document.getElementById("concept").value="A lighthouse keeper receives letters from tomorrow."; document.getElementById("settings-link").click()');
  assert.equal(await evaluate('location.pathname'), '/settings');
  assert.equal(await evaluate('document.getElementById("create-view").hidden'), true);
  await evaluate('document.getElementById("provider").value="openrouter"; document.getElementById("provider").dispatchEvent(new Event("change"))');
  assert.equal(await evaluate('document.getElementById("openrouter-key-panel").hidden'), false);
  assert.equal(await evaluate('document.getElementById("openrouter-key").type'), 'password');
  await evaluate('document.getElementById("openrouter-key").value="dummy-ui-secret-not-saved"; document.getElementById("toggle-key").click()');
  assert.equal(await evaluate('document.getElementById("openrouter-key").type'), 'text');
  await evaluate('document.getElementById("toggle-key").click()');
  assert.equal(await evaluate('document.getElementById("openrouter-key").type'), 'password');
  await evaluate('document.getElementById("provider").value="lmstudio"; document.getElementById("provider").dispatchEvent(new Event("change"))');
  assert.equal(await evaluate('document.getElementById("base-url").value'), 'http://127.0.0.1:1234/v1');
  assert.equal(await evaluate('document.getElementById("openrouter-key-panel").hidden'), true);
  assert.equal(await evaluate('document.getElementById("openrouter-key").value'), '');
  assert.equal(await evaluate('document.getElementById("settings-form").checkValidity()'), false);
  await evaluate('document.getElementById("concept").value="A lighthouse keeper receives letters from tomorrow."; document.getElementById("model").value="my-local-model"; document.getElementById("chapters").value="3"');
  assert.equal(await evaluate('document.getElementById("book-form").checkValidity()'), true);
  await mkdir('artifacts', {recursive: true});
  const desktop = await send('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true});
  await writeFile('artifacts/athena-ui-desktop.png', Buffer.from(desktop.data, 'base64'));
  await evaluate('document.getElementById("new-book").click()');
  assert.equal(await evaluate('location.pathname'), '/');
  assert.equal(await evaluate('document.getElementById("concept").value'), 'A lighthouse keeper receives letters from tomorrow.');
  const home = await send('Page.captureScreenshot', {format: 'png'});
  await writeFile('artifacts/athena-chat-home.png', Buffer.from(home.data, 'base64'));
  const jobs = await (await fetch(url + '/api/jobs')).json();
  if (jobs.length) {
    await evaluate(`selectBook(${JSON.stringify(jobs[0].id)})`);
    for (let i = 0; i < 50; i++) { if (await evaluate('document.getElementById("activity-messages").children.length > 0')) break; await sleep(100); }
    assert.equal(await evaluate('document.getElementById("detail-view").hidden'), false);
    assert.equal(await evaluate('document.getElementById("book-concept").textContent'), jobs[0].concept);
    assert.ok(await evaluate('document.getElementById("activity-messages").children.length > 0'));
    assert.equal(await evaluate('document.querySelector(".technical-log").open'), false);
    await evaluate('document.getElementById("chat-input").value="A draft question, not sent."; showSettings();');
    await evaluate(`selectBook(${JSON.stringify(jobs[0].id)})`);
    assert.equal(await evaluate('document.getElementById("chat-input").value'), 'A draft question, not sent.');
    const thread = await send('Page.captureScreenshot', {format: 'png'});
    await writeFile('artifacts/athena-chat-thread.png', Buffer.from(thread.data, 'base64'));
  }
  await evaluate('document.getElementById("settings-link").click()');
  await send('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
  await sleep(100);
  assert.equal(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), true, 'Mobile layout fits the viewport');
  const mobile = await send('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true});
  await writeFile('artifacts/athena-ui-mobile.png', Buffer.from(mobile.data, 'base64'));
  await evaluate('showCreate(); document.getElementById("toggle-library").click()');
  assert.equal(await evaluate('document.body.classList.contains("library-open")'), true);
  await evaluate('document.getElementById("new-book").click()');
  assert.equal(await evaluate('document.body.classList.contains("library-open")'), false);
  if (jobs.length) {
    await evaluate(`selectBook(${JSON.stringify(jobs[0].id)})`);
    await sleep(150);
    assert.equal(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), true);
    const mobileThread = await send('Page.captureScreenshot', {format: 'png'});
    await writeFile('artifacts/athena-chat-mobile.png', Buffer.from(mobileThread.data, 'base64'));
  }
  assert.deepEqual(errors, [], 'No browser JavaScript exceptions');
  // Exercise the new editor without saving or touching any user's book.
  await evaluate(`editorContent = {concept: 'Fixture idea', chapters: [{number: 1, title: 'Opening', prose: 'Fixture chapter text.'}]};
    document.getElementById('edit-chapter').replaceChildren(new Option('Chapter 1', '1'));
    loadEditorChapter(); document.getElementById('editor-dialog').showModal();`);
  assert.equal(await evaluate('document.getElementById("edit-text").value'), 'Fixture chapter text.');
  await evaluate('document.getElementById("edit-text").value="Unsaved change"; document.getElementById("edit-text").dispatchEvent(new Event("input"))');
  assert.equal(await evaluate('document.getElementById("edit-chapter").disabled'), true);
  assert.equal(await evaluate('document.getElementById("editor-dialog").getBoundingClientRect().width <= innerWidth'), true);
  await evaluate('document.querySelector("[data-close=editor-dialog]").click()');
  assert.equal(await evaluate('document.getElementById("editor-dialog").open'), false);
  await evaluate('document.getElementById("continue-dialog").showModal()');
  assert.equal(await evaluate('document.getElementById("continue-form").checkValidity()'), false);
  await evaluate('document.getElementById("continuation-text").value="Follow the next generation"');
  assert.equal(await evaluate('document.getElementById("continue-form").checkValidity()'), true);
  await evaluate('document.querySelector("[data-close=continue-dialog]").click()');
  assert.deepEqual(errors, [], 'New book controls have no JavaScript exceptions');
  console.log('Browser checks passed: page loads, provider selection, form validation, mobile layout. Screenshots in artifacts/. No generation started.');
} finally {
  socket?.close();
  chrome.kill();
}
