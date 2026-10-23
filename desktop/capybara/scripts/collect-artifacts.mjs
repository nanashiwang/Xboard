import {
    readdir,
    readFile,
    mkdir,
    copyFile,
    writeFile,
} from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
const root = path.resolve(import.meta.dirname, "..");
const target = process.argv[2];
const pkg = JSON.parse(await readFile(path.join(root, "package.json"), "utf8"));
const bundle = path.join(
    root,
    "src-tauri",
    "target",
    target,
    "release",
    "bundle",
);
async function files(dir) {
    const out = [];
    for (const f of await readdir(dir, { withFileTypes: true })) {
        if (f.isDirectory()) out.push(...(await files(path.join(dir, f.name))));
        else out.push(path.join(dir, f.name));
    }
    return out;
}
const wanted = target.includes("apple")
    ? [".dmg"]
    : target.includes("windows")
      ? [".exe"]
      : [".deb", ".AppImage"];
await mkdir(path.join(root, "artifacts"), { recursive: true });
const sums = [];
for (const extension of wanted) {
    const candidates = (await files(bundle)).filter((f) =>
        f.endsWith(extension),
    );
    if (candidates.length !== 1)
        throw new Error(
            `Expected one ${extension} installer, got ${candidates.length}`,
        );
    const name = `Capybara_${pkg.version}_${target}${extension}`;
    const data = await readFile(candidates[0]);
    await copyFile(candidates[0], path.join(root, "artifacts", name));
    sums.push(`${createHash("sha256").update(data).digest("hex")}  ${name}`);
}
await writeFile(
    path.join(root, "artifacts", `SHA256SUMS-${target}.txt`),
    sums.join("\n") + "\n",
);
console.log(`已核对 ${target} 的 ${sums.length} 个安装包`);
