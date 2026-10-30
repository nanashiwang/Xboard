const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(require('node:path').join(__dirname, '../../public/assets/residential-capacity.js'), 'utf8');
function boot(hash = '#/') {
  let interval, value = 'admin-test', current;
  const events = {}, requests = [];
  const element = () => ({innerHTML:'', textContent:'', disabled:false, isConnected:false, children:{}, setAttribute(){},
    querySelector(s){return this.children[s] ||= element();}, addEventListener(n, f){this[n] = f;},
    replaceChildren(){this.innerHTML = '';}, remove(){this.isConnected = false;}});
  const host = {prepend(el){current = el; el.isConnected = true;}};
  const location = {hash};
  const context = {document:{body:{dataset:{adminPath:'admin'}}, hidden:false, createElement:element,
    querySelector:s => s.startsWith('nav ') ? {} : host}, location, Date, AbortController, encodeURIComponent,
    localStorage:{getItem:()=>JSON.stringify(value ? {value} : null)}, addEventListener:(n,f)=>events[n]=f,
    setInterval:f=>interval=f, setTimeout:()=>1, clearTimeout(){},
    fetch:(url, options)=>new Promise(resolve=>requests.push({url, options, resolve}))};
  vm.runInNewContext(source, context);
  return {requests, location, events, tick:()=>interval(), setToken:t=>value=t, panel:()=>current};
}
const data = {checked_at:123, plans:[{name:'<img onerror=alert(1)>', selling:true, subscribers:1, assigned_subscribers:1,
  unassigned_subscribers:0, reserved:1, occupied:2, available_slots:3, capacity_limit:5, primary_capacity:5,
  exits:[{name:'节点',public_ip:'203.0.113.1',enabled:true,healthy:true,standby:false,capacity:5,subscribers:1,reserved:1,occupied:2,free_slots:3,allocatable_slots:3}]}], shared_nodes:[{name:'共享家宽',subscribers:9}]};
const flush = () => new Promise(resolve=>setImmediate(resolve));
test('home card uses admin API and escapes names while separating shared permissions', async()=>{
  const s=boot(); assert.equal(s.requests.length,1);
  assert.equal(s.requests[0].options.headers.Authorization,'admin-test');
  s.requests[0].resolve({ok:true,json:async()=>({data})}); await flush();
  const html=s.panel().querySelector('.rc-data').innerHTML;
  assert.ok(html.includes('&lt;img')); assert.ok(!html.includes('<img'));
  assert.ok(html.includes('9 人有使用权限')); assert.ok(html.includes('订单预留'));
});
test('non-home routes do not mount or fetch', ()=>{const s=boot('#/?page=node-quality'); assert.equal(s.requests.length,0); assert.equal(s.panel(),undefined);});
test('logout aborts pending request and late response cannot repopulate old card', async()=>{
  const s=boot(), old=s.panel(); s.setToken('');s.tick();
  assert.ok(s.requests[0].options.signal.aborted); assert.equal(old.isConnected,false);
  s.requests[0].resolve({ok:true,json:async()=>({data})});await flush();assert.equal(old.querySelector('.rc-data').innerHTML,'');
});
test('failed refresh clears stale capacity and permits retry',async()=>{
  const s=boot();s.requests[0].resolve({ok:true,json:async()=>({data})});await flush();
  s.panel().querySelector('button').click();s.requests[1].resolve({ok:false,status:500});await flush();
  assert.equal(s.panel().querySelector('.rc-data').innerHTML,'');assert.ok(s.panel().querySelector('.rc-status').textContent.includes('加载失败'));
  assert.equal(s.panel().querySelector('button').disabled,false);
});
test('route return and identity switch mount fresh cards without accepting stale data',async()=>{
  const s=boot(), old=s.panel();s.location.hash='#/users';s.events.hashchange();assert.equal(old.isConnected,false);
  s.location.hash='#/';s.events.hashchange();assert.equal(s.requests.length,2);
  s.setToken('new-admin');s.tick();assert.equal(s.requests.length,3);assert.equal(s.requests[2].options.headers.Authorization,'new-admin');
  s.requests[1].resolve({ok:true,json:async()=>({data})});await flush();assert.equal(s.panel().querySelector('.rc-data').innerHTML,'');
});
