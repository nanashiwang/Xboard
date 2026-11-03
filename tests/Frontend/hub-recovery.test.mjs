import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const name='Capybara_0.1.14_x86_64-pc-windows-msvc.exe';
const source=await readFile(new URL('../../.docker/hub/worker.mjs',import.meta.url),'utf8');
const {handle,default:worker}=await import('data:text/javascript;base64,'+Buffer.from(source.replace('__CAPYBARA_RELEASE_ASSETS__',JSON.stringify({[name]:`https://github.com/nanashiwang/Xboard/releases/download/capybara-v0.1.14/${name}`}))).toString('base64'));
test('Cloudflare entrypoint does not mistake ExecutionContext for the upstream fetch function',async()=>{
 const original=globalThis.fetch;let called=0;
 globalThis.fetch=async()=>{called++;return new Response('signed-package');};
 try {
  const response=await worker.fetch(new Request(`https://capybarahub.fyi/downloads/${name}`),{}, {waitUntil(){}});
  assert.equal(response.status,200);assert.equal(await response.text(),'signed-package');assert.equal(called,1);
 } finally {globalThis.fetch=original;}
});
test('recovery metadata is independent static content and never cached',async()=>{
 const env={ASSETS:{fetch:async()=>new Response('{"version":"0.1.14"}')}};
 for(const file of ['capybara-hub.json','capybara-entrypoints.json']){
  const response=await handle(new Request(`https://capybarahub.fyi/downloads/${file}?check=1`),env,()=>{throw new Error('must not use Go or GitHub')});
  assert.equal(response.status,200); assert.equal(response.headers.get('cache-control'),'no-store');
 }
});
test('approved package streams ranges through Hub with no user credentials or Go dependency',async()=>{
 const calls=[];
 const response=await handle(new Request(`https://capybarahub.fyi/downloads/${name}`,{headers:{Range:'bytes=0-3',Authorization:'Bearer private',Cookie:'secret=value'}}),{},async(url,options)=>{
  calls.push(url);assert.equal(options.headers.get('Authorization'),null);assert.equal(options.headers.get('Cookie'),null);
  assert.equal(options.headers.get('Range'),'bytes=0-3');
  return calls.length===1?new Response(null,{status:302,headers:{Location:'https://release-assets.githubusercontent.com/fixed?signature=internal'}}):new Response('test',{status:206,headers:{'Content-Range':'bytes 0-3/4','Set-Cookie':'upstream=secret'}});
 });
 assert.equal(await response.text(),'test');assert.equal(response.status,206);assert.equal(response.headers.get('set-cookie'),null);
 assert.equal(response.headers.get('location'),null);assert.ok(calls.every(url=>!url.includes('capybarago')));
});
test('unknown paths, methods and multi-range requests cannot turn Hub into an open proxy',async()=>{
 let calls=0;const fetcher=()=>{calls++;throw new Error('unexpected')};
 for(const [path,options,status] of [
  ['/downloads/private',{},404], [`/downloads/${name}?url=https://evil.invalid`,{},404],
  [`/downloads/${name}`,{method:'POST'},405], [`/downloads/${name}`,{headers:{Range:'bytes=0-1,2-3'}},416],
 ])assert.equal((await handle(new Request('https://capybarahub.fyi'+path,options),{},fetcher)).status,status);
 assert.equal(calls,0);
});
test('unexpected upstream redirect is rejected without contacting its destination',async()=>{
 let calls=0;
 const response=await handle(new Request(`https://capybarahub.fyi/downloads/${name}`),{},async()=>{calls++;return new Response(null,{status:302,headers:{Location:'https://evil.invalid/private'}})});
 assert.equal(response.status,502);assert.equal(calls,1);assert.ok(!(await response.text()).includes('evil'));
});
