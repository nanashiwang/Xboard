import {
    readFile,
    mkdir,
    writeFile,
    chmod,
    mkdtemp,
    readdir,
    rm,
} from "node:fs/promises";
import { gunzipSync } from "node:zlib";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import path from "node:path";
const root = path.resolve(import.meta.dirname, "..");
const manifest = JSON.parse(
    await readFile(path.join(root, "core-assets.json"), "utf8"),
);
const target =
    process.argv[2] ||
    execFileSync("rustc", ["-vV"], { encoding: "utf8" }).match(
        /^host: (.+)$/m,
    )[1];
const asset = manifest.assets[target];
if (!asset) throw new Error(`不支持的构建目标: ${target}`);
let archive;
if (process.env.CAPYBARA_CORE_ARCHIVE)
    archive = await readFile(process.env.CAPYBARA_CORE_ARCHIVE);
else {
    const response = await fetch(asset.browser_download_url, {
        signal: AbortSignal.timeout(120000),
    });
    if (!response.ok) throw new Error(`内核下载失败 HTTP ${response.status}`);
    archive = Buffer.from(await response.arrayBuffer());
}
if (
    `sha256:${createHash("sha256").update(archive).digest("hex")}` !==
    asset.digest
)
    throw new Error("内核下载摘要不匹配");
let binary;
if (asset.name.endsWith(".gz")) binary = gunzipSync(archive);
else {
    const temp = await mkdtemp(path.join(tmpdir(), "capybara-core-"));
    try {
        await writeFile(path.join(temp, "core.zip"), archive);
        if (process.platform === "win32")
            execFileSync(
                "powershell",
                [
                    "-NoProfile",
                    "-Command",
                    "Expand-Archive -LiteralPath core.zip -DestinationPath unpack",
                ],
                { cwd: temp },
            );
        else
            execFileSync("unzip", ["-q", "core.zip", "-d", "unpack"], {
                cwd: temp,
            });
        const exe = (await readdir(path.join(temp, "unpack"))).find((f) =>
            f.endsWith(".exe"),
        );
        if (!exe) throw new Error("内核压缩包缺少可执行文件");
        binary = await readFile(path.join(temp, "unpack", exe));
    } finally {
        await rm(temp, { recursive: true, force: true });
    }
}
const destination = path.join(
    root,
    "src-tauri",
    "binaries",
    `mihomo-${target}${target.includes("windows") ? ".exe" : ""}`,
);
await mkdir(path.dirname(destination), { recursive: true });
await writeFile(destination, binary);
await chmod(destination, 0o755);
console.log(`Mihomo ${manifest.version} / ${target}：摘要已验证`);
