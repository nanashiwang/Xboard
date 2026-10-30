const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(require('node:path').join(__dirname, '../../public/assets/residential-capacity.js'), 'utf8');
const pageHash = '#/?page=residential-capacity';
function boot(hash = pageHash) {
  let interval, value = 'admin-test', current, closed = 0;
  const events = {}, requests = [], elements = [];
  const element = () => {
    const attrs = {}, classes = new Set();
    const el = {innerHTML:'', textContent:'', className:'', disabled:false, isConnected:false, children:{},
    classList:{add:c=>classes.add(c), remove:c=>classes.delete(c), contains:c=>classes.has(c)},
    setAttribute(n,v){attrs[n]=v;},removeAttribute(n){delete attrs[n];},getAttribute(n){return attrs[n];},
    querySelector(s){return this.children[s] ||= element();}, addEventListener(n, f){this[n] = f;},
    append(child){child.isConnected=true;child.parentElement=this;},
    after(child){child.isConnected=true;},
    replaceChildren(){this.innerHTML = '';}, remove(){this.isConnected = false;}};
    elements.push(el); return el;
  };
  const host=element(), heading=element(), home=element(), body=element();
  heading.parentElement=element();body.dataset={adminPath:'admin'};
  home.className='nav-link bg-secondary shadow-sm';home.setAttribute('aria-current','page');
  host.append=el=>{current=el;el.isConnected=true;};
  const location = {hash};
  const context = {document:{body, title:'Xboard', hidden:false, createElement:element,
    getElementById:id=>elements.find(el=>el.id===id && el.isConnected),
    querySelector:s=>s.startsWith('nav ') ? home : s.startsWith('main h1') ? heading : s.startsWith('button[') ? {click:()=>closed++} : host}, location, Date, AbortController, encodeURIComponent, URLSearchParams,
    localStorage:{getItem:()=>JSON.stringify(value ? {value} : null)}, addEventListener:(n,f)=>events[n]=f,
    setInterval:f=>interval=f, setTimeout:()=>1, clearTimeout(){},
    fetch:(url, options)=>new Promise(resolve=>requests.push({url, options, resolve}))};
  vm.runInNewContext(source, context);
  return {requests, location, events, host, body, home, heading, document:context.document, closed:()=>closed,
    nav:()=>context.document.getElementById('residential-capacity-nav'), tick:()=>interval(), setToken:t=>value=t, panel:()=>current};
}
const data = {checked_at:123, plans:[{name:'<img onerror=alert(1)>', selling:true, subscribers:1, assigned_subscribers:1,
  unassigned_subscribers:0, reserved:1, occupied:2, available_slots:3, capacity_limit:5, primary_capacity:5,
  exits:[{name:'节点',public_ip:'203.0.113.1',enabled:true,healthy:true,standby:false,capacity:5,subscribers:1,reserved:1,occupied:2,free_slots:3,allocatable_slots:3}]}], shared_nodes:[{name:'共享家宽',subscribers:9}]};
const flush = () => new Promise(resolve=>setImmediate(resolve));
test('dedicated page uses admin API and escapes names while separating shared permissions', async()=>{
  const s=boot(); assert.equal(s.requests.length,1);
  assert.equal(s.requests[0].options.headers.Authorization,'admin-test');
  s.requests[0].resolve({ok:true,json:async()=>({data})}); await flush();
  const html=s.panel().querySelector('.rc-data').innerHTML;
  assert.ok(html.includes('&lt;img')); assert.ok(!html.includes('<img'));
  assert.ok(html.includes('9 人有使用权限')); assert.ok(html.includes('订单预留'));
});
test('home and other routes have a sidebar link without a capacity card or request', ()=>{
  for(const hash of ['','#/','#/users','#/?page=node-quality','#/users?page=residential-capacity']) {
    const s=boot(hash); assert.equal(s.requests.length,0); assert.equal(s.panel(),undefined);
    assert.equal(s.nav().href,pageHash);assert.equal(s.nav().getAttribute('aria-current'),undefined);
    assert.equal(s.host.classList.contains('rc-page-host'),false);
  }
});
test('sidebar highlights only the dedicated page and closes the mobile menu on ordinary click',()=>{
  const s=boot();assert.equal(s.nav().getAttribute('aria-current'),'page');assert.equal(s.home.getAttribute('aria-current'),undefined);
  assert.ok(s.host.classList.contains('rc-page-host'));assert.equal(s.document.title,'家宽订阅与容量 · Xboard');
  s.nav().click({button:0});assert.equal(s.closed(),1);
  s.nav().click({button:0,ctrlKey:true});assert.equal(s.closed(),1);
  s.location.hash='#/';s.events.hashchange();
  assert.equal(s.home.getAttribute('aria-current'),'page');assert.equal(s.document.title,'Xboard');
  assert.equal(s.host.classList.contains('rc-page-host'),false);assert.equal(s.heading.parentElement.classList.contains('rc-page-heading'),false);
});
test('logout aborts pending request and late response cannot repopulate old card', async()=>{
  const s=boot(), old=s.panel(); s.setToken('');s.tick();
  assert.ok(s.requests[0].options.signal.aborted); assert.equal(old.isConnected,false);
  assert.equal(s.nav(),undefined);assert.equal(s.host.classList.contains('rc-page-host'),false);
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
  s.location.hash=pageHash;s.events.hashchange();assert.equal(s.requests.length,2);
  s.setToken('new-admin');s.tick();assert.equal(s.requests.length,3);assert.equal(s.requests[2].options.headers.Authorization,'new-admin');
  s.requests[1].resolve({ok:true,json:async()=>({data})});await flush();assert.equal(s.panel().querySelector('.rc-data').innerHTML,'');
});
