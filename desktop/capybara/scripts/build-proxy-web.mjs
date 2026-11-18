import {build} from 'esbuild';
await build({entryPoints:['src/proxies-web.tsx'],bundle:true,minify:true,format:'iife',target:'es2022',define:{'process.env.NODE_ENV':'"production"'},outfile:'../../public/assets/residential-proxy/app.js',legalComments:'none'});
