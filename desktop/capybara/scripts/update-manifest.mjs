import { readFile, writeFile } from "node:fs/promises";
import { createPublicKey, verify, createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Tauri stores a base64-encoded minisign public key and detached signature.
// Verify the payload and trusted comment before publishing the update index.
export function verifySignature(data, encodedSignature, encodedKey) {
    const keyLines = Buffer.from(encodedKey.trim(), "base64")
        .toString()
        .trim()
        .split(/\r?\n/);
    const sigLines = Buffer.from(encodedSignature.trim(), "base64")
        .toString()
        .trim()
        .split(/\r?\n/);
    const key = Buffer.from(keyLines[1] || "", "base64");
    const sig = Buffer.from(sigLines[1] || "", "base64");
    if (
        key.length !== 42 ||
        sig.length !== 74 ||
        !key.subarray(2, 10).equals(sig.subarray(2, 10)) ||
        !sigLines[2]?.startsWith("trusted comment: ")
    )
        throw new Error("Invalid signature/key format");
    const publicKey = createPublicKey({
        key: Buffer.concat([
            Buffer.from("302a300506032b6570032100", "hex"),
            key.subarray(10),
        ]),
        format: "der",
        type: "spki",
    });
    const payload =
        sig.subarray(0, 2).toString() === "ED"
            ? createHash("blake2b512").update(data).digest()
            : sig.subarray(0, 2).toString() === "Ed"
              ? data
              : null;
    if (!payload || !verify(null, payload, publicKey, sig.subarray(10)))
        throw new Error("Update payload signature mismatch");
    const comment = sigLines[2].slice("trusted comment: ".length);
    if (
        !verify(
            null,
            Buffer.concat([sig.subarray(10), Buffer.from(comment)]),
            publicKey,
            Buffer.from(sigLines[3] || "", "base64"),
        )
    )
        throw new Error("Update comment signature mismatch");
}
export const targets = {
    "darwin-aarch64": ["aarch64-apple-darwin", ".app.tar.gz"],
    "darwin-x86_64": ["x86_64-apple-darwin", ".app.tar.gz"],
    "windows-x86_64": ["x86_64-pc-windows-msvc", ".exe"],
    "linux-x86_64": ["x86_64-unknown-linux-gnu", ".AppImage"],
};
export async function generate(directory) {
    const root = path.resolve(import.meta.dirname, "..");
    const { version } = JSON.parse(
        await readFile(path.join(root, "package.json"), "utf8"),
    );
    const config = JSON.parse(
        await readFile(path.join(root, "src-tauri/tauri.conf.json"), "utf8"),
    );
    const result = {
        version,
        notes: await readFile(path.join(root, "RELEASE_NOTES.md"), "utf8"),
        pub_date: new Date().toISOString(),
        platforms: {},
    };
    for (const [platform, [target, extension]] of Object.entries(targets)) {
        const name = `Capybara_${version}_${target}${extension}`;
        const signature = (
            await readFile(path.join(directory, name + ".sig"), "utf8")
        ).trim();
        const data = await readFile(path.join(directory, name));
        verifySignature(data, signature, config.plugins.updater.pubkey);
        result.platforms[platform] = {
            signature,
            url: `https://taige.us/downloads/${name}`,
        };
    }
    await writeFile(
        path.join(directory, "capybara-latest.json"),
        JSON.stringify(result, null, 2) + "\n",
    );
    console.log(
        `已验证 ${Object.keys(result.platforms).length} 个目标的更新签名并生成索引`,
    );
}
if (
    process.argv[1] &&
    path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
)
    await generate(path.resolve(process.argv[2] || "artifacts"));
