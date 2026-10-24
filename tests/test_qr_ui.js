const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
const source = html.slice(html.indexOf('async function qrLogin()'), html.indexOf('\nfunction renderDeviceList'));
let timers = [], pendingPoll, searches = 0;
const elements = new Map();
const context = {
  document: { getElementById(id) {
    if (!elements.has(id)) elements.set(id, {style:{},textContent:''});
    return elements.get(id);
  }},
  showAlert(){}, searchDevices(){ searches++; },
  setTimeout(fn, delay){ const item = {fn,delay}; timers.push(item); return item; },
  clearTimeout(item){ timers = timers.filter(t => t !== item); },
  async fetch(url) {
    if (url === '/api/qr/login') return {json: async()=>({ok:true,qr_url:'synthetic-private-qr'})};
    return new Promise(resolve => { pendingPoll = data => resolve({json:async()=>data}); });
  },
};
vm.createContext(context);
vm.runInContext('let qrPollTimer=null, qrGeneration=0, qrStarting=false;\n'+source, context);
async function tick() { const item=timers.shift(); assert.ok(item); return item.fn(); }
(async()=>{
  await context.qrLogin();
  assert.equal(timers.length,1);
  const inFlight=tick();
  assert.equal(timers.length,0,'No next poll is scheduled while a request is pending');
  pendingPoll({ok:true,done:false,msg:'waiting'});
  await inFlight;
  assert.equal(timers.length,1);
  const expired=tick();
  pendingPoll({ok:false,done:false,terminal:true,msg:'expired'});
  await expired;
  assert.equal(timers.length,0,'Expired QR stops polling');
  await context.qrLogin();
  const old=tick();
  const finishOld=pendingPoll;
  await context.qrLogin();
  finishOld({ok:true,done:true,msg:'stale success'});
  await old;
  assert.equal(searches,0,'Old QR response must not affect a new QR session');
  assert.equal(timers.length,1);
  const success=tick();
  pendingPoll({ok:true,done:true,msg:'success'});
  await success;
  assert.equal(searches,1);
  assert.equal(timers.length,0);
  console.log('QR UI scheduling tests passed (3 scenarios).');
})().catch(error=>{console.error(error);process.exitCode=1;});
