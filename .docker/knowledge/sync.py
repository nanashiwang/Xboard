#!/usr/bin/env python3
"""Preview or apply reviewed knowledge articles to an existing SQLite database."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sync(args):
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    articles = manifest["articles"]
    if len({item["id"] for item in articles}) != len(articles):
        raise ValueError("清单包含重复文章 ID")
    mode = "rw" if args.apply else "ro"
    uri = Path(args.database).resolve().as_uri() + "?mode=" + mode
    with sqlite3.connect(uri, uri=True, timeout=30) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE" if args.apply else "BEGIN")
        pending = []
        for item in articles:
            source = (root / item["file"]).resolve()
            if root not in source.parents or source.suffix != ".md":
                raise ValueError("文章源文件必须位于脚本目录内")
            body = source.read_text(encoding="utf-8")
            if not body.strip():
                raise ValueError("文章内容不能为空")
            row = db.execute("SELECT * FROM v2_knowledge WHERE id = ?", (item["id"],)).fetchone()
            if row is None or row["title"] != item["title"]:
                raise ValueError(f"文章 {item['id']} 不存在或标题已变化，请重新审阅")
            if row["body"] == body:
                print(f"文章 {item['id']}: 已同步")
                continue
            if digest(row["body"]) != item["expected_body_sha256"]:
                raise ValueError(f"文章 {item['id']} 正文已变化，拒绝覆盖未审阅的修改")
            pending.append((dict(row), body))
            print(f"文章 {item['id']}: {'待更新' if args.apply else '预览'} {item['title']}")

        if args.apply and pending:
            timestamp = int(time.time())
            backup_dir = Path(args.backup_dir)
            backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            backup = backup_dir / f"knowledge-before-client-guides-{timestamp}-{os.getpid()}.json"
            snapshot = {
                "created_at": timestamp,
                "articles": [
                    {"before": row, "after_body_sha256": digest(body)}
                    for row, body in pending
                ],
            }
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(snapshot, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            for row, body in pending:
                db.execute("UPDATE v2_knowledge SET body = ?, updated_at = ? WHERE id = ?",
                           (body, timestamp, row["id"]))
            db.commit()
            print(f"备份: {backup}")
        else:
            db.rollback()
        print(f"{'已更新' if args.apply else '将更新'} {len(pending)} 篇文章；其他字段及文章保持不变")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, help="现有 SQLite 数据库路径")
    parser.add_argument("--apply", action="store_true", help="执行写入；默认仅预览")
    parser.add_argument("--backup-dir", help="执行写入时的备份目录")
    args = parser.parse_args()
    if args.apply and not args.backup_dir:
        parser.error("--apply 必须同时提供 --backup-dir")
    try:
        sync(args)
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        parser.exit(1, f"同步失败: {error}\n")


if __name__ == "__main__":
    main()
