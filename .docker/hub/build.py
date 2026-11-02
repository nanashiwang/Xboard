#!/usr/bin/env python3
"""Build the independent Hub from the approved layout and release manifest."""
import argparse
import html
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = "https://capybarago.uk"


def build(destination):
    destination.mkdir(parents=True, exist_ok=True)
    preview = ROOT / "docs/previews/capybara-entry"
    index = (preview / "index.html").read_text()
    index = index.replace("卡皮巴拉导航 · 页面预览", "卡皮巴拉导航")
    index = index.replace("卡皮巴拉双域入口方案：导航页交互预览。", "卡皮巴拉应用入口与客户端下载。")
    index = index.replace('href="go.html"', 'href="' + APP + '/"')
    (destination / "index.html").write_text(index)
    shutil.copyfile(preview / "style.css", destination / "style.css")
    (destination / "assets").mkdir(exist_ok=True)
    shutil.copyfile(preview / "assets/icon.webp", destination / "assets/icon.webp")

    manifest = json.loads((ROOT / ".docker/downloads/manifest.json").read_text())
    feed = next(item for item in manifest if item["name"] == "capybara-latest.json")
    match = re.fullmatch(r"https://github\.com/nanashiwang/Xboard/releases/download/capybara-v(\d+\.\d+\.\d+)/capybara-latest\.json", feed["url"])
    if not match:
        raise ValueError("Only a verified stable release can be offered by the Hub")
    version = match[1]
    platforms = [
        ("Windows", "x86_64-pc-windows-msvc.exe"),
        ("macOS · Apple 芯片", "aarch64-apple-darwin.dmg"),
        ("macOS · Intel 芯片", "x86_64-apple-darwin.dmg"),
        ("Linux · AppImage", "x86_64-unknown-linux-gnu.AppImage"),
        ("Linux · Debian", "x86_64-unknown-linux-gnu.deb"),
    ]
    rows, checksums = [], []
    for label, suffix in platforms:
        name = f"Capybara_{version}_{suffix}"
        asset = next(item for item in manifest if item["name"] == name)
        expected = f"https://github.com/nanashiwang/Xboard/releases/download/capybara-v{version}/{name}"
        if asset["url"] != expected or not re.fullmatch(r"[a-f0-9]{64}", asset["sha256"]):
            raise ValueError("Unexpected release asset")
        rows.append(f'''<article><div><h2>{html.escape(label)}</h2><p>版本 {version} · {asset['size'] / 1048576:.1f} MB</p></div>
<div class="download-actions"><a href="{APP}/downloads/{name}">下载</a><a href="{expected}">备用下载</a></div></article>''')
        checksums.append(asset["sha256"] + "  " + name)
    (destination / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n")
    downloads = '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><title>卡皮巴拉 · 客户端下载</title>
<link rel="icon" href="assets/icon.webp"><link rel="stylesheet" href="style.css">
<style>.download-actions{display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end}.download-actions a{padding:10px 12px;border:1px solid #dce5d3;border-radius:7px;text-decoration:none;font-size:12px;color:#507046;background:#eff4e9;white-space:nowrap}.download-list h2{font-size:16px}.download-list article{flex-wrap:wrap}.download-help{font-size:12px;line-height:1.8;color:#788371}</style>
</head><body class="hub-page"><main class="hub-shell downloads-shell"><a class="back-link" href="/">← 返回导航</a>
<header class="hub-heading"><img src="assets/icon.webp" width="64" height="64" alt="卡皮巴拉"><p class="eyebrow">CAPYBARA DOWNLOADS</p><h1>选择你的设备</h1></header>
<section class="download-list" aria-label="客户端下载">''' + "\n".join(rows) + '''</section>
<p class="download-help">下载没有开始时，可尝试备用下载。<a href="SHA256SUMS.txt">查看文件校验值</a></p>
</main></body></html>'''
    (destination / "downloads.html").write_text(downloads)
    (destination / "_headers").write_text("/*\n  Referrer-Policy: no-referrer\n  X-Content-Type-Options: nosniff\n  X-Frame-Options: DENY\n  Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'\n  Cache-Control: public, max-age=300\n")
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print("Built Hub with release " + build(args.destination))
