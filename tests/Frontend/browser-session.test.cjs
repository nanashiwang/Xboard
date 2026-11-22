const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');
const userBundle = fs.readFileSync('theme/Xboard/assets/umi.js', 'utf8');
const adminRoot = 'public/assets/admin';
const entry = JSON.parse(fs.readFileSync(`${adminRoot}/manifest.json`))['index.html'];
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'xboard-session-'));
process.on('exit', () => fs.rmSync(temp, {recursive:true, force:true}));
fs.mkdirSync(path.join(temp, 'assets'));
for (const name of ['manifest.json', 'index.html', entry.file]) {
  fs.copyFileSync(`${adminRoot}/${name}`, path.join(temp, name));
}
const patch = () => execFileSync('php', ['scripts/frontend/patch-admin-session.php', temp], {stdio:'pipe'});
patch();
const patchedEntry = JSON.parse(fs.readFileSync(path.join(temp,'manifest.json')))['index.html'].file;
const adminBundle = fs.readFileSync(path.join(temp,patchedEntry),'utf8');

function storageFixture(bundle, admin) {
  let time = 1000000000;
  const values = new Map();
  const storage = {setItem:(k,v)=>values.set(k,v), getItem:k=>values.get(k)??null, removeItem:k=>values.delete(k), clear:()=>values.clear()};
  const FakeDate = class extends Date {constructor(){super(time)} static now(){return time}};
  const context = {localStorage:storage, sessionStorage:storage, Date:FakeDate, f:(o,k)=>o[k]=undefined};
  // Execute the distribution's real storage class and login/logout functions.
  const classStart = admin ? bundle.lastIndexOf('class ', bundle.indexOf('function Rf(')) : bundle.indexOf('class id{');
  const end = admin ? bundle.indexOf('const Ff=',classStart) : bundle.indexOf('function hd()',classStart);
  vm.runInNewContext(bundle.slice(classStart,end), context);
  const setter = admin ? 'function save(e){'+bundle.match(/Mf\.set\(Af,e,\d+\)/)[0]+'}' : bundle.match(/function PN\(e\)\{[^}]+\}/)[0]+';const save=PN;';
  vm.runInNewContext(setter+';this.api={save,read:'+(admin?'Pf':'dd')+',logout:'+(admin?'jf':'pd')+'};',context);
  return {api:context.api, advance:days=>time+=days*86400000};
}
for (const [name,bundle,admin] of [['user',userBundle,false],['admin',adminBundle,true]]) {
  test(`${name}: login survives reopen at 29 days and expires at 30 days`,()=>{
    const f=storageFixture(bundle,admin);f.api.save('test-token');
    f.advance(29);assert.equal(f.api.read().value,'test-token');
    f.advance(1);assert.equal(f.api.read().value,null);
  });
  test(`${name}: explicit logout removes token immediately`,()=>{
    const f=storageFixture(bundle,admin);f.api.save('test-token');f.api.logout();assert.equal(f.api.read().value,null);
  });
}
test('admin patch is idempotent, hashes entry, and fails closed on upstream changes',()=>{
  patch();assert.equal(JSON.parse(fs.readFileSync(path.join(temp,'manifest.json')))['index.html'].file,patchedEntry);
  const hash=require('node:crypto').createHash('sha256').update(adminBundle).digest('hex').slice(0,16);
  assert.ok(patchedEntry.includes(hash));assert.ok(fs.readFileSync(path.join(temp,'index.html'),'utf8').includes('./'+patchedEntry));
  fs.writeFileSync(path.join(temp,patchedEntry),adminBundle.replace('Mf.set(Af,e,2592000)','Mf.set(Af,e,123)'));
  assert.throws(patch, error => error.status !== 0 && /Admin login storage changed/.test(String(error.stdout)+String(error.stderr)));
});
const navigation = fs.readFileSync('theme/Xboard/patches/session-navigation.js','utf8').trim();
function guardFixture(error, hasToken=true) {
  const guards=[],next=[],removed=[],routes=[],messages=[];
  const router={beforeEach:f=>guards.push(f),afterEach(){},onError(){},hasRoute:()=>false,addRoute:r=>routes.push(r)};
  const user={role:[],getUserInfo:async()=>{if(error)throw error;user.userUUID='verified'}};
  const context={window:{$message:{error:e=>messages.push(e)}},BN:()=>user,$N:()=>({generateRoutes:()=>[{name:'dashboard'}]}),
    dd:()=>({value:hasToken?'test-token':null}),pd:()=>removed.push(true),_N:()=>({getConfig:async()=>{}}),UN:['/login'],bs:{name:'404'}};
  vm.runInNewContext(navigation+';VN(router)',{...context,router});
  return {run:()=>guards[1]({path:'/dashboard',query:{}},{},v=>next.push(v)),next,removed,routes,messages};
}
test('maintained navigation is in shipped bundle; HTTP status reaches guard',()=>{
  assert.ok(userBundle.includes(navigation));assert.ok(userBundle.includes('code:e.response?.status||r'));
});
for(const error of [{code:-1},{code:429},{code:502},{code:403,message:'Forbidden'}]) {
  test(`temporary or unrelated failure ${error.code} preserves login and cancels navigation`,async()=>{
    const f=guardFixture(error);await f.run();assert.equal(f.removed.length,0);assert.deepEqual(f.next,[false]);assert.equal(f.routes.length,0);
  });
}
for(const error of [{code:401},{code:403,message:'未登录或登陆已过期'}]) {
  test(`confirmed auth failure ${error.code} clears login and redirects once`,async()=>{
    const f=guardFixture(error);await f.run();assert.equal(f.removed.length,1);assert.equal(f.next.length,1);assert.equal(f.next[0].path,'/login');assert.equal(f.routes.length,0);
  });
}
test('verified account installs routes, missing token redirects',async()=>{
  const f=guardFixture();await f.run();assert.equal(f.routes.length,2);assert.equal(f.next[0].replace,true);
  const empty=guardFixture(null,false);await empty.run();assert.equal(empty.next[0].path,'/login');assert.equal(empty.routes.length,0);
});

const lineSource = fs.readFileSync('scripts/frontend/admin-node-lines.js', 'utf8');
const groupLines = vm.runInNewContext(lineSource + '\ngroupAdminNodeLines');
const node = (id, parent_id, show = 1, dedicated_exit_id = null) => ({id, parent_id, show, dedicated_exit_id});

test('the admin entry ships the line view and groups only by backend identity', () => {
  assert.ok(adminBundle.includes(lineSource));
  const backend = node(353, null, 0);
  const alias = node(348, 353, 1, 14);
  const entry = node(354, '353');
  const single = node(400, null);
  const otherBackend = node(403, null, 0);
  const otherEntry = node(404, 403);
  const groups = groupLines([alias, single, backend, entry, otherBackend, otherEntry]);
  assert.deepEqual(Array.from(groups.rows), [single, entry, otherEntry]);
  assert.equal(groups.details.get(354).backend, backend);
  assert.deepEqual(Array.from(groups.details.get(354).others), [alias]);
  assert.equal(groups.details.get(404).backend, otherBackend);
});

test('unpaired nodes, visible parents, cycles and deeper topologies stay editable', () => {
  const rows = [
    node(1, null, 0), node(2, 99), node(3, null), node(4, 3),
    node(5, null, 0), node(6, 5, 0), node(7, 6), node(8, 5),
    node(9, 10, 0), node(10, 9, 0), node(11, 11, 0),
  ];
  const groups = groupLines(rows);
  assert.deepEqual(Array.from(groups.rows), rows);
  assert.equal(groups.details.size, 0);
});
