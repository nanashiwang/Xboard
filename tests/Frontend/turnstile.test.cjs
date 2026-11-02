const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('theme/Xboard/patches/turnstile-component.js', 'utf8');
function fixture(api) {
  const events=[], timers=new Map(), scripts=[]; let id=0;
  const context={window:{turnstile:api}, GY:undefined, KY:'cfTurnstileOnLoad',
    setTimeout(fn){timers.set(++id,fn);return id}, clearTimeout(n){timers.delete(n)},
    document:{createElement(){return {remove(){this.removed=true}}},head:{appendChild(s){scripts.push(s)}}}};
  const component=vm.runInNewContext(source,context);
  const instance={...component.data(),$emit:(...args)=>events.push(args),$refs:{turnstile:{}},resetInterval:295000,renderOnMount:true,active:true};
  for(const [key,value] of Object.entries(component.methods))instance[key]=value.bind(instance);
  instance.turnstileOptions=component.computed.turnstileOptions.call(instance);
  return {context,component,instance,events,timers,scripts};
}
test('errors and expiry clear token without automatic reset loops',()=>{
  let resets=0;const f=fixture({reset(){resets++}});
  f.instance.callback('token-a');f.instance.callback('token-b');assert.equal(f.timers.size,1);
  f.instance.errorCallback('network');assert.equal(f.timers.size,0);assert.equal(resets,0);
  f.instance.expiredCallback();assert.equal(resets,0);assert.ok(f.events.some(e=>e[0]==='expired'));
  assert.equal(f.instance.turnstileOptions.retry,'never');assert.equal(f.instance.turnstileOptions['refresh-expired'],'manual');
});
test('retry resets only owned widget and unmount removes it',()=>{
  const calls=[];const f=fixture({reset:id=>calls.push(['reset',id]),remove:id=>calls.push(['remove',id])});
  f.instance.widgetId=0;f.instance.reset();f.component.beforeUnmount.call(f.instance);
  assert.deepEqual(calls,[['reset',0],['remove',0]]);assert.equal(f.instance.active,false);
});
test('script error is visible and explicit retry loads a fresh script',async()=>{
  const f=fixture();const attempt=f.instance.load();assert.equal(f.scripts.length,1);
  f.scripts[0].onerror();await attempt;assert.equal(f.scripts[0].removed,true);
  assert.ok(f.events.some(e=>e[0]==='error'));assert.equal(f.context.GY,undefined);
  const retry=f.instance.load();assert.equal(f.scripts.length,2);
  f.context.window.turnstile={render:()=> 'fresh-widget'};f.context.window.cfTurnstileOnLoad();await retry;
  assert.equal(f.instance.widgetId,'fresh-widget');assert.equal(f.timers.size,0);
});
test('script timeout is bounded and late load after unmount cannot render',async()=>{
  const f=fixture();let attempt=f.instance.load();[...f.timers.values()][0]();await attempt;
  assert.ok(f.events.some(e=>e[0]==='error'));
  attempt=f.instance.load();f.component.beforeUnmount.call(f.instance);
  f.context.window.turnstile={render(){throw Error('must not render after unmount')}};
  f.context.window.cfTurnstileOnLoad();await attempt;assert.equal(f.instance.widgetId,undefined);
});
test('vendored component matches maintained source and form clears pending action on failure',()=>{
  const bundle=fs.readFileSync('theme/Xboard/assets/umi.js','utf8');
  assert.ok(bundle.includes('const YY=zn('+source.trim()+'),QY='));
  assert.ok(bundle.includes('function _(){f.value="",m.value="",y.value="",h.value=!1,'));
  assert.ok(bundle.includes('function A(e){return v(this,null,(function*(){return!!w.value&&(f.value="",y.value=e,'));
});
