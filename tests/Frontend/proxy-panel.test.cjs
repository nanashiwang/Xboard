const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('theme/Xboard/patches/proxy-route.js','utf8');
async function setup(ready=true){
  const calls=[],elements=[];const window={};
  const mount=(element,options)=>{calls.push(['mount',element]);window.options=options;return ()=>calls.push(['unmount'])};
  if(ready)window.CapybaraResidentialProxies={mount};
  const route=vm.runInNewContext('('+source+')',{window,cs:{component:{}},li:()=>{},pd:()=>calls.push(['logout']),setTimeout,clearTimeout,document:{
    createElement:tag=>({tag,remove(){calls.push(['remove',tag])}}),head:{append(...items){elements.push(...items)}}
  }}).default;
  const definition=await route.children[0].component();
  const instance={...definition.data(),$refs:{proxyContent:{}},$router:{replace:value=>calls.push(['route',value.path])}};
  for(const [name,method]of Object.entries(definition.methods))instance[name]=method.bind(instance);
  return {calls,elements,window,mount,instance,definition,route};
}
test('panel uses the existing layout, mounts once and clears content when leaving',async()=>{
  const x=await setup();assert.equal(x.route.children[0].meta.title,'家宽代理');
  await x.instance.startProxy();await x.instance.startProxy();assert.equal(x.calls.length,1);
  x.definition.deactivated.call(x.instance);x.definition.beforeUnmount.call(x.instance);
  assert.equal(x.calls.filter(c=>c[0]==='unmount').length,1);
  await x.instance.startProxy();assert.equal(x.calls.filter(c=>c[0]==='mount').length,2);
  x.window.options.onLogin();assert.deepEqual(x.calls.slice(-2),[['logout'],['route','/login']]);
});
test('leaving during asset loading never mounts stale private content; returning works',async()=>{
  const x=await setup(false);const pending=x.instance.startProxy();x.instance.stopProxy();
  x.window.CapybaraResidentialProxies={mount:x.mount};x.elements[0].onload();x.elements[1].onload();await pending;
  assert.equal(x.calls.filter(c=>c[0]==='mount').length,0);
  await x.instance.startProxy();assert.equal(x.calls.filter(c=>c[0]==='mount').length,1);
});
test('failed assets are removed and a later attempt can retry',async()=>{
  const x=await setup(false);const pending=x.instance.startProxy();x.elements[1].onerror();await pending;
  assert.equal(x.instance.proxyError,true);assert.equal(x.window.__capybaraProxyLoading,null);
  x.instance.stopProxy();const retry=x.instance.startProxy();x.window.CapybaraResidentialProxies={mount:x.mount};
  x.elements[2].onload();x.elements[3].onload();await retry;assert.equal(x.instance.proxyError,false);
  assert.equal(x.calls.filter(c=>c[0]==='mount').length,1);
});
test('shipped theme embeds the readable route and content-addressed assets',()=>{
  const crypto=require('node:crypto');let expected=source.trim();
  for(const [name,file]of [['__PROXY_CSS__','app.css'],['__PROXY_JS__','app.js']]){
    expected=expected.replace(name,'/assets/residential-proxy/'+file+'?v='+crypto.createHash('sha256').update(fs.readFileSync('public/assets/residential-proxy/'+file)).digest('hex'));
  }
  assert.ok(fs.readFileSync('theme/Xboard/assets/umi.js','utf8').includes(expected));
  assert.ok(!source.includes('location.assign'));
});
