import { readFile, writeFile, unlink } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { verifySignature } from './update-manifest.mjs';

// The original updater private key stays in the existing GitHub Actions secret.
const directory = path.resolve(process.argv[2] || 'artifacts');
const root = path.resolve(import.meta.dirname, '..');
const payload = await readFile(path.join(root, 'service-entrypoints.json'));
const value = JSON.parse(payload);
const now = Math.floor(Date.now() / 1000);
if (value.kind !== 'capybara-service-origins-v1' || !Number.isSafeInteger(value.sequence)
    || value.sequence < 1 || value.issued_at > now + 300 || value.expires_at <= now
    || value.expires_at - value.issued_at > 366 * 86400
    || !Array.isArray(value.origins) || !value.origins.length || value.origins.length > 4
    || value.origins.some(origin => {
        const url = new URL(origin);
        return url.protocol !== 'https:' || url.origin !== origin || url.username || url.password;
    })) throw new Error('Invalid service entrypoint policy');
const temporary = path.join(directory, '.service-entrypoints.payload');
await writeFile(temporary, payload);
try {
    execFileSync(path.join(root, 'node_modules/.bin/tauri'), ['signer', 'sign', temporary], {
        env: { ...process.env, TAURI_PRIVATE_KEY: process.env.TAURI_SIGNING_PRIVATE_KEY,
            TAURI_PRIVATE_KEY_PASSWORD: '' }, stdio: 'pipe',
    });
    const signature = (await readFile(temporary + '.sig', 'utf8')).trim();
    const config = JSON.parse(await readFile(path.join(root, 'src-tauri/tauri.conf.json')));
    verifySignature(payload, signature, config.plugins.updater.pubkey);
    await writeFile(path.join(directory, 'capybara-entrypoints.json'), JSON.stringify({
        payload: payload.toString('base64'), signature,
    }) + '\n');
    console.log('入口清单已用现有发行公钥验证');
} finally {
    await unlink(temporary).catch(() => {});
    await unlink(temporary + '.sig').catch(() => {});
}
