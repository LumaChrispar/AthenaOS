// Read-only check of the running book UI: node tests/progress_smoke.mjs JOB_ID
import {spawn} from 'node:child_process';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import assert from 'node:assert/strict';
const id=process.argv[2];
assert.match(id || '', /^[a-f0-9]{32}$/);
const profile=await mkdtemp(join(tmpdir(),'athena-progress-'));
const chrome=spawn('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', ['--headless=new','--disable-gpu','--in-process-gpu','--no-sandbox','--no-first-run','--no-default-browser-check','--remote-debugging-port=0',`--user-data-dir=${profile}`,'about:blank'],{windowsHide:true,stdio:'ignore'});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let socket, seq=0;
const pending=new Map();
try {
  let port;
  for(let i=0;i<100;i++){try{port=(await readFile(join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];break;}catch{await sleep(100);}}
  assert.ok(port);
  const pages=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);
  await new Promise(resolve=>socket.addEventListener('open',resolve,{once:true}));
  socket.addEventListener('message',event=>{const msg=JSON.parse(event.data);if(msg.id){const p=pending.get(msg.id);pending.delete(msg.id);msg.error?p.reject(msg.error):p.resolve(msg.result);}});
  const send=(method,params={})=>new Promise((resolve,reject)=>{const key=++seq;pending.set(key,{resolve,reject});socket.send(JSON.stringify({id:key,method,params}));});
  const evaluate=async expression=>(await send('Runtime.evaluate',{expression,returnByValue:true})).result.value;
  await send('Page.navigate',{url:`http://127.0.0.1:8765/books/${id}`});
  for(let i=0;i<100;i++){if(await evaluate('document.getElementById("metrics")?.textContent.includes("Chapters drafted")'))break;await sleep(100);}
  const job=await(await fetch(`http://127.0.0.1:8765/api/jobs/${id}`)).json();
  assert.equal(await evaluate('document.getElementById("metrics").children[0].querySelector("strong").textContent'),`${job.chapter_progress.drafted} / ${job.pipeline.total_chapters}`);
  const before=await evaluate('document.getElementById("progress-text").textContent');
  await sleep(4100);
  if(job.status==='running')assert.notEqual(await evaluate('document.getElementById("progress-text").textContent'),before,'Running time refreshes automatically');
  console.log('Live progress browser passed: drafted count and automatic polling.');
} finally {socket?.close();chrome.kill();}
