// Replaced by build.py with the reviewed manifest. Never accept a caller URL.
const assets = __CAPYBARA_RELEASE_ASSETS__;
const redirectHosts = new Set(['github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com']);

export async function handle(request, env, fetcher = fetch) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith('/downloads/')) return env.ASSETS.fetch(request);
    if (!['GET', 'HEAD'].includes(request.method)) return new Response(null, {status: 405});
    if (['/downloads/capybara-hub.json', '/downloads/capybara-entrypoints.json'].includes(url.pathname)) {
        const response = await env.ASSETS.fetch(request);
        const headers = new Headers(response.headers);
        headers.set('Cache-Control', 'no-store');
        return new Response(response.body, {status: response.status, headers});
    }
    const source = assets[url.pathname.slice('/downloads/'.length)];
    if (!source || url.search) return new Response(null, {status: 404});
    const headers = new Headers({'User-Agent': 'Capybara-Hub-Download/1'});
    const range = request.headers.get('Range');
    if (range && !/^bytes=\d+-\d*$/.test(range)) return new Response(null, {status: 416});
    if (range) headers.set('Range', range);
    // No client Authorization, Cookie or forwarding headers leave this service.
    let upstream = source;
    try {
        for (let attempt = 0; attempt < 4; attempt++) {
            const target = new URL(upstream);
            if (target.protocol !== 'https:' || !redirectHosts.has(target.hostname)
                || target.username || target.password || target.port) break;
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), 15000);
            let response;
            try {
                response = await fetcher(target.href, {
                    method: request.method, headers, redirect: 'manual', signal: controller.signal,
                });
            } finally { clearTimeout(timer); }
            if ([301, 302, 303, 307, 308].includes(response.status)) {
                const location = response.headers.get('Location');
                if (!location) break;
                upstream = new URL(location, target).href;
                continue;
            }
            if (![200, 206].includes(response.status)) break;
            const output = new Headers({
                'Content-Type': 'application/octet-stream',
                'Cache-Control': 'public, max-age=86400, immutable',
                'X-Content-Type-Options': 'nosniff',
                'Referrer-Policy': 'no-referrer',
            });
            for (const name of ['Content-Length', 'Content-Range', 'Accept-Ranges', 'ETag']) {
                if (response.headers.has(name)) output.set(name, response.headers.get(name));
            }
            return new Response(request.method === 'HEAD' ? null : response.body, {status: response.status, headers: output});
        }
    } catch { /* No upstream signed URLs or exception text in public errors. */ }
    return new Response('备用下载暂时不可用，请稍后重试。', {status: 502, headers: {'Cache-Control': 'no-store'}});
}
export default { fetch: handle };
