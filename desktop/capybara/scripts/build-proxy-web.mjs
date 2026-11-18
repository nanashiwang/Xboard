import {build} from 'esbuild';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
await build({entryPoints:['src/proxies-web.tsx'],bundle:true,minify:true,format:'iife',globalName:'CapybaraResidentialProxies',target:'es2022',define:{'process.env.NODE_ENV':'"production"'},outfile:'../../public/assets/residential-proxy/app.js',legalComments:'none'});
let patch=await readFile('../../theme/Xboard/patches/proxy-route.js','utf8');
for(const [placeholder,file] of [['__PROXY_CSS__','app.css'],['__PROXY_JS__','app.js']]){
  const hash=createHash('sha256').update(await readFile('../../public/assets/residential-proxy/'+file)).digest('hex');
  patch=patch.replace(placeholder,'/assets/residential-proxy/'+file+'?v='+hash);
}
const target='../../theme/Xboard/assets/umi.js';
const source=await readFile(target,'utf8');
const route=/"\/src\/views\/residential-proxy\/route.ts":[\s\S]*?,"\/src\/views\/profile\/route.ts":/g;
if([...source.matchAll(route)].length!==1||!source.includes('function li(e,t,n){const o=arguments.length'))throw new Error('Theme host changed; review Vue integration before building.');
await writeFile(target,source.replace(route,()=> '"/src/views/residential-proxy/route.ts":'+patch.trim()+',"/src/views/profile/route.ts":'));
