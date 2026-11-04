export interface Video {
  id: string;
  platform: string;
  platform_video_id: string;
  source_url?: string;
  title: string;
  author?: string;
  cover_url?: string;
  duration_ms: number;
  media_status: string;
  transcript_status: string;
  content_scope: string;
  favorite?: number;
  size_bytes?: number;
  collection_ids?: string | null;
  created_at: string;
}

export interface Collection {
  id: string;
  name: string;
  color?: string | null;
  count?: number;
}

export interface MediaAsset {
  id: string;
  asset_type: string;
  storage_path: string;
  duration_ms: number;
  width?: number;
  height?: number;
  video_codec?: string;
  status: string;
}

export interface Segment {
  id: string;
  start_ms: number;
  end_ms: number;
  text: string;
  source_type: string;
}

export interface Chapter {
  id: string;
  title: string;
  start_ms: number | null;
  end_ms: number | null;
  description?: string;
}

const BASE = "";

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const b = await r.json();
      detail = b.detail || JSON.stringify(b);
    } catch {}
    throw new Error(detail);
  }
  return r.json();
}

export const api = {
  async listVideos(collection?: string): Promise<Video[]> {
    const q = collection ? `?collection=${encodeURIComponent(collection)}` : "";
    return (await j<any>(await fetch(`${BASE}/api/videos${q}`))).videos;
  },
  async detail(id: string): Promise<{
    video: Video;
    media_assets: MediaAsset[];
    caption_tracks: any[];
    primary_caption: any;
    segments: Segment[];
  }> {
    return j(await fetch(`${BASE}/api/videos/${id}`));
  },
  async transcript(id: string): Promise<Segment[]> {
    return (await j<any>(await fetch(`${BASE}/api/videos/${id}/transcript`))).segments;
  },
  async probe(source: string) {
    return j<any>(
      await fetch(`${BASE}/api/probe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source }),
      })
    );
  },
  async intake(source: string, opts: any = {}) {
    return j<any>(
      await fetch(`${BASE}/api/intake`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source, ...opts }),
      })
    );
  },
  async getTask(taskId: string) {
    return j<any>(await fetch(`${BASE}/api/tasks/${taskId}`));
  },
  async runAsr(videoId: string) {
    return j<any>(
      await fetch(`${BASE}/api/asr`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_id: videoId }),
      })
    );
  },
  async reimportVideo(videoId: string) {
    return j<any>(
      await fetch(`${BASE}/api/videos/${videoId}/reimport`, { method: "POST" })
    );
  },
  async asrStatus() {
    return j<any>(await fetch(`${BASE}/api/asr/status`));
  },
  async punctuate(videoId: string) {
    return j<any>(
      await fetch(`${BASE}/api/analysis/punctuate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_id: videoId }),
      })
    );
  },
  // ---- 磁盘容量 ----
  async storage() {
    return j<any>(await fetch(`${BASE}/api/storage`));
  },
  async setThreshold(threshold: number) {
    return j<any>(
      await fetch(`${BASE}/api/storage/threshold`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ threshold }),
      })
    );
  },
  // ---- 收藏 ----
  async setFavorite(videoId: string, favorite: boolean) {
    return j<any>(
      await fetch(`${BASE}/api/videos/${videoId}/favorite`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ favorite }),
      })
    );
  },
  // ---- 自定义收藏夹 ----
  async collections() {
    return j<any>(await fetch(`${BASE}/api/collections`));
  },
  async createCollection(name: string) {
    return j<any>(
      await fetch(`${BASE}/api/collections`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      })
    );
  },
  async renameCollection(id: string, name: string) {
    return j<any>(
      await fetch(`${BASE}/api/collections/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      })
    );
  },
  async deleteCollection(id: string) {
    return j<any>(await fetch(`${BASE}/api/collections/${id}`, { method: "DELETE" }));
  },
  async toggleVideoCollection(videoId: string, collectionId: string) {
    return j<any>(
      await fetch(`${BASE}/api/videos/${videoId}/collections/${collectionId}/toggle`, {
        method: "POST",
      })
    );
  },
  async videoCollections(videoId: string) {
    return j<any>(await fetch(`${BASE}/api/videos/${videoId}/collections`));
  },
  // ---- 批量导入 ----
  async uploadFiles(files: File[]) {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    const r = await fetch(`${BASE}/api/upload`, { method: "POST", body: fd });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || "上传失败");
    return d;
  },
  async intakeBatch(sources: string[], opts: any = {}) {
    const r = await fetch(`${BASE}/api/intake/batch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sources, ...opts }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || "批量导入失败");
    return data;
  },
  // ---- 任务控制 ----
  async taskControl(taskId: string, action: "pause" | "resume" | "cancel" | "retry") {
    return j<any>(await fetch(`${BASE}/api/tasks/${taskId}/${action}`, { method: "POST" }));
  },
  async taskDelete(taskId: string) {
    return j<any>(await fetch(`${BASE}/api/tasks/${taskId}`, { method: "DELETE" }));
  },
  async tasksBatchDelete(ids: string[]) {
    return j<any>(await fetch(`${BASE}/api/tasks/batch-delete`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    }));
  },
  async tasks(limit = 20) {
    return j<any>(await fetch(`${BASE}/api/tasks?limit=${limit}`));
  },
  async verifyCredential(platform = "bilibili") {
    return j<any>(await fetch(`${BASE}/api/credentials/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ platform }),
    }));
  },
  async credentialStatus(platform = "bilibili") {
    return j<any>(await fetch(`${BASE}/api/credentials/${platform}`));
  },
  async clearCredential(platform = "bilibili") {
    return j<any>(await fetch(`${BASE}/api/credentials/${platform}`, { method: "DELETE" }));
  },
  async setCredential(raw: string, platform = "bilibili") {
    return j<any>(
      await fetch(`${BASE}/api/credentials`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform, raw }),
      })
    );
  },
  // ---- 抖音 CDP（浏览器自己解密 Cookie，绕开 SQLite 锁与 v20 加密）----
  async douyinCdpLogin(port?: number) {
    return j<any>(await fetch(`${BASE}/api/credentials/douyin/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ port }),
    }));
  },
  async douyinCdpCookie(port?: number) {
    return j<any>(await fetch(`${BASE}/api/credentials/douyin/cdp`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ port }),
    }));
  },
  // ---- 应用设置：个人职业档案 ----
  async getProfile() {
    return j<any>(await fetch(`${BASE}/api/settings/profile`));
  },
  async saveProfile(profile: {
    career: string; tags: string[]; goal: string; industry: string;
  }) {
    return j<any>(await fetch(`${BASE}/api/settings/profile`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    }));
  },
  // ---- B站收藏夹（登录态批量导入） ----
  async biliFavFolders() {
    return j<any>(await fetch(`${BASE}/api/bilibili/fav/folders`));
  },
  async biliFavItems(mediaId: string, page = 1, pageSize = 20) {
    const q = `?media_id=${encodeURIComponent(mediaId)}&page=${page}&page_size=${pageSize}`;
    return j<any>(await fetch(`${BASE}/api/bilibili/fav/items${q}`));
  },
  mediaUrl(videoId: string, assetId?: string) {
    return `${BASE}/api/videos/${videoId}/media${assetId ? `?asset_id=${assetId}` : ""}`;
  },
  async chapters(videoId: string) {
    // 章节由分析生成；这里从 detail 里没有，单独读取
    return j<any>(
      await fetch(`${BASE}/api/videos/${videoId}`)
    );
  },
  async saveProgress(videoId: string, position_ms: number, duration_ms: number) {
    return fetch(`${BASE}/api/videos/${videoId}/progress`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ position_ms, duration_ms }),
    });
  },
  async getProgress(videoId: string) {
    return j<any>(await fetch(`${BASE}/api/videos/${videoId}/progress`));
  },
  async saveNote(videoId: string, content: string) {
    return j<any>(
      await fetch(`${BASE}/api/videos/${videoId}/notes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      })
    );
  },
  async deleteVideo(videoId: string, deleteMedia = true, deleteKnowledge = true) {
    return fetch(
      `${BASE}/api/videos/${videoId}?delete_media=${deleteMedia}&delete_knowledge=${deleteKnowledge}`,
      { method: "DELETE" }
    );
  },
  exportUrl(videoId: string) {
    return `${BASE}/api/videos/${videoId}/export.md`;
  },
};

/** 流式问答：逐段回调 delta。返回时给出引用列表。 */
export async function askQa(
  videoId: string,
  question: string,
  onDelta: (t: string) => void,
  signal?: AbortSignal
): Promise<string[]> {
  let resp: Response;
  try {
    resp = await fetch(`${BASE}/api/videos/${videoId}/qa`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
      signal,
    });
  } catch (e: any) {
    // 网络层失败（后端未启动 / 跨域 / 断网）时 fetch 只抛 "Failed to fetch"，这里翻译成可操作提示
    if (e?.name === "AbortError") throw e;
    throw new Error(
      "无法连接后端服务，请确认已通过 run.cmd 启动并访问 http://127.0.0.1:8000（而不是直接打开 dist/index.html）"
    );
  }
  if (!resp.ok || !resp.body) {
    let detail = `问答失败（HTTP ${resp.status}）`;
    try {
      const b = await resp.json();
      detail = b.detail || detail;
    } catch {}
    throw new Error(detail);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buf = "";
  let citations: string[] = [];
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop() || "";
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data:")) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      try {
        const obj = JSON.parse(payload);
        if (obj.delta) onDelta(obj.delta);
        if (obj.done && Array.isArray(obj.citations)) citations = obj.citations;
        if (obj.error) throw new Error(obj.error);
      } catch (e) {
        if (e instanceof Error && e.message && !e.message.startsWith("Unexpected")) throw e;
      }
    }
  }
  return citations;
}

export function fmtSize(bytes: number): string {
  if (!bytes || bytes < 0) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let n = bytes;
  while (n >= 1024 && i < u.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n >= 100 ? Math.round(n) : n.toFixed(1)} ${u[i]}`;
}

export function fmtTime(ms: number): string {
  if (!ms && ms !== 0) return "--:--";
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`;
}

const SENTENCE_END = "。！？!?…；;";

/** 把逐句字幕合并为段落（与后端 textnorm.merge_cues 规则一致）。 */
export function mergeCues(
  cues: Segment[],
  opts: { maxGapMs?: number; maxChars?: number; maxDurationMs?: number } = {}
) {
  const maxGap = opts.maxGapMs ?? 700;
  const maxChars = opts.maxChars ?? 70;
  const maxDur = opts.maxDurationMs ?? 20000;
  if (!cues.length) return [] as Segment[];

  const ordered = [...cues].sort((a, b) => a.start_ms - b.start_ms);
  const out: Segment[] = [];
  let cur: Segment | null = null;
  let curLen = 0;

  for (const c of ordered) {
    const text = (c.text || "").trim();
    if (!text) continue;
    if (!cur) {
      cur = { ...c, text };
      curLen = text.length;
      continue;
    }
    const gap = c.start_ms - cur.end_ms;
    const prev = cur.text;
    const wouldLen = curLen + text.length;
    const wouldDur = c.end_ms - cur.start_ms;
    const endsSentence = prev.length > 0 && SENTENCE_END.includes(prev[prev.length - 1]);
    const canMerge =
      gap <= maxGap && gap >= -500 && wouldLen <= maxChars && wouldDur <= maxDur && !endsSentence;
    if (canMerge) {
      cur.text = prev + text;
      cur.end_ms = c.end_ms;
      curLen = wouldLen;
    } else {
      out.push(cur);
      cur = { ...c, text };
      curLen = text.length;
    }
  }
  if (cur) out.push(cur);
  return out;
}
