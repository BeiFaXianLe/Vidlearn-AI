"""SQLite 数据库层（S3-01）。

表设计遵循 PRD §4 与 V2.0 冻结数据模型：
  videos / media_assets / source_captions / transcript_segments
使用外键 + 索引 + 简单版本迁移（PRAGMA user_version）。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 8

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS videos (
    id                TEXT PRIMARY KEY,
    platform          TEXT NOT NULL,                 -- bilibili | douyin | local
    platform_video_id TEXT NOT NULL,
    source_url        TEXT,
    title             TEXT NOT NULL DEFAULT '',
    author            TEXT,
    cover_url         TEXT,
    duration_ms       INTEGER NOT NULL DEFAULT 0,
    media_status      TEXT NOT NULL DEFAULT 'pending',   -- pending/downloaded/uploaded/unavailable/failed
    transcript_status TEXT NOT NULL DEFAULT 'missing',   -- complete/partial/missing/unknown/failed
    content_scope     TEXT NOT NULL DEFAULT 'unknown',   -- full/partial/unknown
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(platform, platform_video_id)
);

CREATE TABLE IF NOT EXISTS media_assets (
    id                TEXT PRIMARY KEY,
    video_id          TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    asset_type        TEXT NOT NULL,                 -- original_media / audio / subtitle / thumbnail
    storage_path      TEXT NOT NULL,
    original_filename TEXT,
    mime_type         TEXT,
    container         TEXT,
    video_codec       TEXT,
    audio_codec       TEXT,
    width             INTEGER,
    height            INTEGER,
    size_bytes        INTEGER NOT NULL DEFAULT 0,
    duration_ms       INTEGER NOT NULL DEFAULT 0,
    sha256            TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending',   -- pending/verified/likely/partial/invalid
    retention_policy  TEXT NOT NULL DEFAULT 'keep',      -- keep / delete_after_process
    acquired_from     TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(video_id, sha256)
);
CREATE INDEX IF NOT EXISTS idx_media_video ON media_assets(video_id);
CREATE INDEX IF NOT EXISTS idx_media_sha ON media_assets(sha256);

CREATE TABLE IF NOT EXISTS source_captions (
    id                  TEXT PRIMARY KEY,
    video_id            TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    media_asset_id      TEXT REFERENCES media_assets(id) ON DELETE SET NULL,
    source_type         TEXT NOT NULL,               -- bilibili_ai / bilibili_human / embedded / user / asr
    language            TEXT,
    format              TEXT,                        -- srt/vtt/json
    source_path         TEXT,
    raw_text_hash       TEXT,
    is_ai_generated     INTEGER NOT NULL DEFAULT 0,
    completeness_status TEXT NOT NULL DEFAULT 'unknown',  -- complete/partial/missing/unknown
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_captions_video ON source_captions(video_id);

CREATE TABLE IF NOT EXISTS transcript_segments (
    id                TEXT PRIMARY KEY,
    video_id          TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    source_caption_id TEXT REFERENCES source_captions(id) ON DELETE CASCADE,
    start_ms          INTEGER NOT NULL,
    end_ms            INTEGER NOT NULL,
    text              TEXT NOT NULL,
    source_type       TEXT NOT NULL,
    language          TEXT,
    confidence        REAL,
    segment_index     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_seg_video ON transcript_segments(video_id, start_ms);
"""

SCHEMA_V2_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS summaries (
    id             TEXT PRIMARY KEY,
    video_id       TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    mode           TEXT NOT NULL,                    -- quick / deep
    content_json   TEXT NOT NULL,                    -- 结构化 JSON
    plain_text     TEXT,
    content_scope  TEXT NOT NULL DEFAULT 'unknown',  -- full / partial / unknown
    model          TEXT,
    provider       TEXT,
    prompt_version TEXT,
    transcript_hash TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_summaries_video ON summaries(video_id);

CREATE TABLE IF NOT EXISTS chapters (
    id               TEXT PRIMARY KEY,
    video_id         TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    title            TEXT NOT NULL,
    start_ms         INTEGER,
    end_ms           INTEGER,
    description      TEXT,
    timestamp_source TEXT,                           -- subtitle / asr / manual
    confidence       REAL,
    sort_order       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_chapters_video ON chapters(video_id, sort_order);

CREATE TABLE IF NOT EXISTS knowledge_points (
    id              TEXT PRIMARY KEY,
    video_id        TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    content         TEXT,
    start_ms        INTEGER,
    end_ms          INTEGER,
    source_refs_json TEXT,
    tags_json       TEXT
);
CREATE INDEX IF NOT EXISTS idx_kp_video ON knowledge_points(video_id);
"""

SCHEMA_V3_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS learning_progress (
    video_id        TEXT PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,
    position_ms     INTEGER NOT NULL DEFAULT 0,
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    completed       INTEGER NOT NULL DEFAULT 0,
    last_watched_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notes (
    id         TEXT PRIMARY KEY,
    video_id   TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    chapter_id TEXT,
    start_ms   INTEGER,
    content    TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_notes_video ON notes(video_id);
"""

SCHEMA_V5_SQL = """
PRAGMA foreign_keys = ON;

-- 自定义收藏夹
CREATE TABLE IF NOT EXISTS collections (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    color      TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_collections_name ON collections(name);

-- 视频 ↔ 收藏夹（多对多）
CREATE TABLE IF NOT EXISTS video_collections (
    video_id      TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (video_id, collection_id)
);
CREATE INDEX IF NOT EXISTS idx_vc_video ON video_collections(video_id);
CREATE INDEX IF NOT EXISTS idx_vc_collection ON video_collections(collection_id);
"""

SCHEMA_V6_SQL = """
PRAGMA foreign_keys = ON;

-- 后台任务持久化（重启后仍可查看/重试）
CREATE TABLE IF NOT EXISTS jobs (
    id         TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);
"""

SCHEMA_V7_SQL = """
PRAGMA foreign_keys = ON;

-- 术语表：用于 ASR 热词注入与拼音同音纠错
CREATE TABLE IF NOT EXISTS glossary (
    id         TEXT PRIMARY KEY,
    scope      TEXT NOT NULL DEFAULT 'global',      -- global / video
    video_id   TEXT REFERENCES videos(id) ON DELETE CASCADE,
    term       TEXT NOT NULL,                        -- 正确写法
    variants   TEXT,                                 -- 已知错误写法（JSON 数组）
    category   TEXT,                                 -- 品牌/人名/术语/产品
    weight     INTEGER NOT NULL DEFAULT 0,
    enabled    INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_glossary_term
    ON glossary(scope, COALESCE(video_id, ''), term);

-- 字幕校准变更日志（M2：复核与回退）
CREATE TABLE IF NOT EXISTS caption_changes (
    id            TEXT PRIMARY KEY,
    video_id      TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    caption_id    TEXT NOT NULL REFERENCES source_captions(id) ON DELETE CASCADE,
    segment_index INTEGER,
    start_ms      INTEGER,
    before        TEXT NOT NULL,
    after         TEXT NOT NULL,
    reason        TEXT NOT NULL,                     -- pinyin / llm / align / manual
    time_from_ms  INTEGER,
    time_to_ms    INTEGER,
    confidence    REAL,
    accepted      INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_changes_caption ON caption_changes(caption_id);
CREATE INDEX IF NOT EXISTS idx_changes_video ON caption_changes(video_id);

-- 字幕质量报告（每轨每次校准一条）
CREATE TABLE IF NOT EXISTS caption_qc (
    caption_id   TEXT PRIMARY KEY REFERENCES source_captions(id) ON DELETE CASCADE,
    video_id     TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    score        REAL NOT NULL,
    report_json  TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


SCHEMA_V8_SQL = """
PRAGMA foreign_keys = ON;

-- 文档资料明细（V8）：条目本身复用 videos(platform='document')，
-- 正文由解析器生成后存于此表；不写 media_assets，避免污染媒体/占用统计。
CREATE TABLE IF NOT EXISTS documents (
    video_id    TEXT PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,
    format      TEXT NOT NULL,                       -- html / markdown / txt
    source_path TEXT,                                -- 保存到 data/documents 的源文件
    size_bytes  INTEGER NOT NULL DEFAULT 0,
    sha256      TEXT NOT NULL,
    char_count  INTEGER NOT NULL DEFAULT 0,
    content     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_documents_sha ON documents(sha256);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI 的同步路由在线程池执行，连接需允许跨线程；并发写入用锁保护
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    cur = conn.cursor()
    ver = cur.execute("PRAGMA user_version").fetchone()[0]
    if ver < 1:
        conn.executescript(SCHEMA_SQL)
        ver = 1
    if ver < 2:
        conn.executescript(SCHEMA_V2_SQL)
        ver = 2
    if ver < 3:
        conn.executescript(SCHEMA_V3_SQL)
        ver = 3
    if ver < 4:
        # ALTER TABLE ADD COLUMN 不幂等，需先判断列是否存在
        cols = {r[1] for r in conn.execute("PRAGMA table_info(videos)").fetchall()}
        if "favorite" not in cols:
            conn.execute("ALTER TABLE videos ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        ver = 4
    if ver < 5:
        conn.executescript(SCHEMA_V5_SQL)
        # 把旧的 favorite=1 迁移到「默认收藏」收藏夹
        try:
            n_fav = conn.execute("SELECT COUNT(*) c FROM videos WHERE favorite=1").fetchone()[0]
            if n_fav:
                import uuid as _uuid
                row = conn.execute("SELECT id FROM collections WHERE name='默认收藏'").fetchone()
                cid = row[0] if row else _uuid.uuid4().hex
                if not row:
                    conn.execute("INSERT INTO collections(id, name, sort_order) VALUES(?,?,0)",
                                 (cid, "默认收藏"))
                conn.execute(
                    "INSERT OR IGNORE INTO video_collections(video_id, collection_id)"
                    " SELECT id, ? FROM videos WHERE favorite=1", (cid,))
        except Exception:
            pass
        ver = 5
    if ver < 6:
        conn.executescript(SCHEMA_V6_SQL)
        ver = 6
    if ver < 7:
        conn.executescript(SCHEMA_V7_SQL)
        ver = 7
    if ver < 8:
        conn.executescript(SCHEMA_V8_SQL)
        ver = 8
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    return SCHEMA_VERSION


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = connect(db_path)
    migrate(conn)
    return conn
