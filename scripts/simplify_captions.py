"""迁移：把库中已有字幕统一转为简体（时间戳不变）。

用法：.venv\\Scripts\\python.exe scripts\\simplify_captions.py
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB = ROOT / "data" / "database" / "vidlearn.db"


def main():
    if not DB.exists():
        print("数据库不存在，跳过")
        return
    from apps.core.textnorm import simplify_cues

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    total = changed = 0
    for cap in conn.execute("SELECT id FROM source_captions").fetchall():
        segs = [dict(r) for r in conn.execute(
            "SELECT id, start_ms, end_ms, text FROM transcript_segments"
            " WHERE source_caption_id=? ORDER BY segment_index", (cap["id"],)).fetchall()]
        if not segs:
            continue
        total += len(segs)
        new = simplify_cues(segs)
        diff = sum(1 for a, b in zip(segs, new) if a["text"] != b["text"])
        if diff:
            for r in new:
                conn.execute("UPDATE transcript_segments SET text=? WHERE id=?", (r["text"], r["id"]))
            changed += diff
            print(f'  字幕轨 {cap["id"][:8]}: 转换 {diff}/{len(segs)} 段')

    conn.commit()
    print(f"完成：共 {total} 段，转换 {changed} 段")
    conn.close()


if __name__ == "__main__":
    main()
