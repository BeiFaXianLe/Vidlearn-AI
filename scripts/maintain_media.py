"""维护脚本：清理孤儿数据 + 非可播容器转 MP4（幂等，可重复运行）。

用法：.venv\\Scripts\\python.exe scripts\\maintain_media.py
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB = ROOT / "data" / "database" / "vidlearn.db"
PLAYABLE = {".mp4", ".webm", ".m4a", ".mp3", ".ogg"}
MEDIA_EXT = (".mp4", ".webm", ".mkv", ".m4a", ".mp3", ".wav", ".mov", ".avi")


def main():
    if not DB.exists():
        print("数据库不存在，跳过")
        return
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")   # 必须开启，级联删除才生效

    # 1) 文件已不存在的资产
    removed = 0
    for r in conn.execute("SELECT id, storage_path FROM media_assets").fetchall():
        if not Path(r["storage_path"]).exists():
            conn.execute("DELETE FROM media_assets WHERE id=?", (r["id"],))
            removed += 1
            print("删除孤儿资产:", Path(r["storage_path"]).name)

    # 2) 孤儿记录（父视频已不存在）
    orphans = 0
    for table in ("source_captions", "transcript_segments", "media_assets",
                  "learning_progress", "notes", "summaries", "chapters",
                  "knowledge_points"):
        orphans += conn.execute(
            f"DELETE FROM {table} WHERE video_id NOT IN (SELECT id FROM videos)").rowcount
    if orphans:
        print("清理孤儿记录:", orphans)

    # 3) 同一视频下 mp4 与 mkv 并存时，保留 mp4
    dup = 0
    for vid, items in {
        v: list(conn.execute("SELECT id, storage_path FROM media_assets WHERE video_id=?", (v,)))
        for v in [r[0] for r in conn.execute("SELECT DISTINCT video_id FROM media_assets")]
    }.items():
        mp4_stems = {Path(i["storage_path"]).stem for i in items
                     if Path(i["storage_path"]).suffix.lower() == ".mp4"}
        for i in items:
            p = Path(i["storage_path"])
            if p.suffix.lower() not in PLAYABLE and p.stem in mp4_stems:
                conn.execute("DELETE FROM media_assets WHERE id=?", (i["id"],))
                p.unlink(missing_ok=True)
                dup += 1
                print("删除重复非可播资产:", p.name)

    # 4) media 目录下未被引用的媒体文件
    referenced = {Path(r["storage_path"]).name
                  for r in conn.execute("SELECT storage_path FROM media_assets")}
    junk = 0
    for f in (ROOT / "data" / "media").rglob("*"):
        if f.is_file() and f.suffix.lower() in MEDIA_EXT and f.name not in referenced:
            f.unlink(missing_ok=True)
            junk += 1
            print("删除未引用媒体文件:", f.name)

    # 5) ASR 临时音频
    tmp = 0
    for f in (ROOT / "data" / "media").rglob("*.asr16k.wav"):
        f.unlink(missing_ok=True)
        tmp += 1

    # 6) 残留的 job_* 临时目录
    job_n = 0
    try:
        from apps.core.acquire import purge_stale_job_dirs
        job_n = purge_stale_job_dirs(ROOT / 'data' / 'media' / 'temp')
    except Exception:
        pass

    # 7) Cookie 临时文件（凭证安全，任何残留都清掉）
    cookie_dirs = [ROOT / 'data' / 'media' / 'temp' / 'cookies']
    cookie_n = 0
    try:
        from apps.adapters.bilibili import BilibiliAdapter
        for d in cookie_dirs:
            cookie_n += BilibiliAdapter.purge_stale_cookie_files(d, 0)
    except Exception:
        pass
    # 兼容历史版本：项目根目录下泄漏的 tmp*.txt（Netscape Cookie 头）
    legacy_n = 0
    for f in ROOT.glob('tmp*.txt'):
        try:
            head = f.read_text(encoding='utf-8', errors='ignore')[:60]
            if 'Netscape HTTP Cookie File' in head:
                f.unlink()
                legacy_n += 1
        except OSError:
            pass

    conn.commit()
    conn.close()
    print(f'完成：孤儿资产 {removed}，孤儿记录 {orphans}，重复 {dup}，'
          f'未引用文件 {junk}，临时音频 {tmp}，Cookie 临时文件 {cookie_n + legacy_n}，临时目录 {job_n}')


if __name__ == "__main__":
    main()
