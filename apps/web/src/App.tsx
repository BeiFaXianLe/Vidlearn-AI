import { useEffect, useMemo, useRef, useState } from "react";
import { api, askQa, fmtSize, fmtTime, mergeCues, type Video, type MediaAsset, type Segment, type Collection } from "./api";

type View = { name: "home" } | { name: "detail"; id: string };

export default function App() {
  const [view, setView] = useState<View>({ name: "home" });
  const [videos, setVideos] = useState<Video[]>([]);
  const [toast, setToast] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [favMode, setFavMode] = useState(false);
  const [favCount, setFavCount] = useState(0);
  const [collections, setCollections] = useState<Collection[]>([]);

  const show = (m: string) => {
    setToast(m);
    window.clearTimeout((show as any)._t);
    (show as any)._t = window.setTimeout(() => setToast(""), 2400);
  };

  async function refresh() {
    try {
      setVideos(await api.listVideos());
      const c = await fetch("/api/favorites/count").then((r) => r.json()).catch(() => null);
      if (c) setFavCount(c.count || 0);
      const col = await api.collections().catch(() => null);
      if (col) setCollections(col.collections || []);
    } catch (e: any) {
      show("加载视频列表失败: " + e.message);
    }
  }
  useEffect(() => {
    refresh();
  }, []);

  const openDetail = (id: string) => {
    window.history.pushState({ name: "detail", id }, "");
    setView({ name: "detail", id });
  };

  // 支持浏览器/鼠标回退键在「详情 ↔ 首页」之间切换
  useEffect(() => {
    window.history.replaceState({ name: "home" }, "");
    const onPop = (e: PopStateEvent) => {
      const st = e.state as { name?: string; id?: string } | null;
      if (st && st.name === "detail" && st.id) {
        setView({ name: "detail", id: st.id });
      } else {
        setView({ name: "home" });
        refresh();
      }
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="logo">V</div>
          <span>VidLearn AI</span>
        </div>
        <div className="navlabel">工作空间</div>
        <button
          className={"nav" + (view.name === "home" && !favMode ? " active" : "")}
          onClick={() => { setFavMode(false); setView({ name: "home" }); }}
        >
          <span className="ico">▦</span>
          <span className="navtext">视频首页</span>
        </button>
        <button
          className={"nav" + (view.name === "home" && favMode ? " active" : "")}
          onClick={() => { setFavMode(true); setView({ name: "home" }); }}
        >
          <span className="ico">★</span>
          <span className="navtext">我的收藏</span>
          {favCount > 0 && <span className="count">{favCount}</span>}
        </button>
        <button className="nav" onClick={() => show("知识库将在后续版本开放")}>
          <span className="ico">▤</span>
          <span className="navtext">我的知识库</span>
        </button>
        <button className="nav" onClick={() => show("学习记录将在后续版本开放")}>
          <span className="ico">◷</span>
          <span className="navtext">学习记录</span>
        </button>
        <div className="navlabel">管理</div>
        <button className="nav" onClick={() => show("设置原型入口")}>
          <span className="ico">⚙</span>
          <span className="navtext">设置</span>
        </button>
        <div className="side-bottom">
          <div className="profile">
            <div className="avatar">Y</div>
            <div>
              <b style={{ fontSize: 12 }}>我的学习空间</b>
              <small>本地知识库 · 私有部署</small>
            </div>
          </div>
        </div>
      </aside>

      <main className="main">
        <div className="topbar">
          <div className="crumb">
            工作空间　/　<span>{view.name === "home" ? "视频首页" : "学习工作台"}</span>
          </div>
          <div className="top-actions">
            <button className="btn primary" onClick={() => setImportOpen(true)}>
              ＋ 导入视频
            </button>
          </div>
        </div>

        {view.name === "home" ? (
          <Home
            videos={videos}
            favMode={favMode}
            collections={collections}
            onOpen={openDetail}
            onRefresh={refresh}
            show={show}
          />
        ) : (
          <Detail id={view.id} onBack={() => window.history.back()} show={show} />
        )}
      </main>

      {importOpen && (
        <ImportModal
          onClose={() => setImportOpen(false)}
          onDone={() => {
            setImportOpen(false);
            refresh();
          }}
          show={show}
        />
      )}
      <div className={"toast" + (toast ? " show" : "")}>{toast}</div>
    </div>
  );
}

function Home({
  videos,
  favMode,
  collections,
  onOpen,
  onRefresh,
  show,
}: {
  videos: Video[];
  favMode: boolean;
  collections: Collection[];
  onOpen: (id: string) => void;
  onRefresh: () => void;
  show: (m: string) => void;
}) {
  const [q, setQ] = useState("");
  const [pf, setPf] = useState("all");
  const [activeCol, setActiveCol] = useState<string>("all");
  const [pickerVideo, setPickerVideo] = useState<Video | null>(null);
  const [storage, setStorage] = useState<any>(null);
  const [tasks, setTasks] = useState<any[]>([]);
  const timerRef = useRef<number | null>(null);

  const colIds = (v: Video) => (v.collection_ids || "").split(",").filter(Boolean);
  const inFav = (v: Video) => colIds(v).length > 0;
  const base = favMode ? videos.filter(inFav) : videos;
  const filtered = base.filter(
    (v) =>
      (pf === "all" || v.platform === pf) &&
      (activeCol === "all" || colIds(v).includes(activeCol)) &&
      (v.title.toLowerCase().includes(q.toLowerCase()) ||
        (v.author || "").toLowerCase().includes(q.toLowerCase()))
  );
  const totalMin = Math.round(videos.reduce((a, v) => a + v.duration_ms, 0) / 60000);

  const loadStorage = async () => {
    try {
      setStorage(await api.storage());
    } catch {}
  };
  const loadTasks = async () => {
    try {
      const r = await api.tasks(30);
      setTasks(r.tasks || []);
    } catch {}
  };

  useEffect(() => {
    loadStorage();
    loadTasks();
    timerRef.current = window.setInterval(async () => {
      await loadTasks();
      await loadStorage();
    }, 2000);
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
  }, []);

  const pct = storage ? storage.used_pct : 0;
  const warnThreshold = storage ? storage.threshold : 85;
  const isWarn = storage ? storage.warn : false;
  const isDanger = storage ? storage.danger : false;
  const activeTasks = tasks.filter((t) => t.status === "running" || t.status === "queued" || t.status === "paused");

  function openPicker(v: Video, e: React.MouseEvent) {
    e.stopPropagation();
    setPickerVideo(v);
  }

  async function cycleThreshold() {
    if (!storage) return;
    const next = storage.threshold >= 95 ? 80 : storage.threshold + 5;
    try {
      await api.setThreshold(next);
      await loadStorage();
      show(`告警阈值已调整为 ${next}%`);
    } catch {}
  }

  async function taskAction(id: string, action: "pause" | "resume" | "cancel" | "retry") {
    try {
      await api.taskControl(id, action);
      await loadTasks();
      const label = { pause: "已暂停", resume: "已继续", cancel: "已取消", retry: "已重新排队" }[action];
      show(label);
    } catch (e: any) {
      show("操作失败: " + e.message);
    }
  }

  const coverPalette = ["linear-gradient(130deg,#23415e,#6c8da7)", "linear-gradient(130deg,#392d66,#a47ec4)",
    "linear-gradient(130deg,#205d5a,#75aaa0)", "linear-gradient(130deg,#254a81,#6e9cce)",
    "linear-gradient(130deg,#7c3d4f,#ce8d8a)", "linear-gradient(130deg,#755a29,#c7a45e)"];

  return (
    <div className={favMode ? "favmode" : ""}>
      <div className="pagehead">
        <div>
          <div className="eyebrow">YOUR PERSONAL VIDEO LIBRARY</div>
          <h1>把看过的视频，变成自己的知识</h1>
          <p className="sub">集中管理视频内容，用 AI 总结、章节和笔记构建可搜索的知识库。</p>
        </div>
        <button className="btn" onClick={onRefresh}>刷新</button>
      </div>

      <div className="stats">
        <div className="stat"><div className="label">已收录视频</div><strong>{videos.length}</strong><em>本地媒体库</em></div>
        <div className="stat"><div className="label">累计时长</div><strong>{totalMin}m</strong><em>本地保存</em></div>
        <div className="stat"><div className="label">字幕就绪</div><strong>{videos.filter((v) => v.transcript_status === "complete").length}</strong><em>可生成总结</em></div>
        <div className="stat"><div className="label">待处理任务</div><strong>{activeTasks.length}</strong><em style={{ color: "var(--orange)" }}>{activeTasks.length ? "处理中" : "暂无排队"}</em></div>
      </div>

      {storage && (
        <div className="storage">
          <div className="scard">
            <div className="sectionline">
              <h2>磁盘容量</h2>
              <span className="muted">
                本地磁盘
                <button className="threshold" onClick={cycleThreshold}>告警阈值 {storage.threshold}%</button>
              </span>
            </div>
            {isWarn && (
              <div className={"storage-warn" + (isDanger ? " danger" : "")}>
                <span>⚠</span>
                <div><b>磁盘使用率 {pct}%</b>，已超过告警阈值 {warnThreshold}%，建议清理旧视频或扩容。</div>
              </div>
            )}
            <div className="sfig">
              <b>{fmtSize(storage.used_bytes)}</b>
              <span className="muted">已用 / 共 {fmtSize(storage.total_bytes)}</span>
              <span className="pct">{pct}% 已用</span>
            </div>
            <div className="sbar">
              <i className="s1" style={{ width: `${Math.min(100, (storage.breakdown.video / storage.used_bytes) * 100 * (pct / 100))}%` }} />
              <i className="s2" style={{ width: `${Math.min(100, (storage.breakdown.subtitle / storage.used_bytes) * 100 * (pct / 100))}%` }} />
              <i className="s3" style={{ width: `${Math.min(100, (storage.breakdown.ai / storage.used_bytes) * 100 * (pct / 100))}%` }} />
              <i className="s4" style={{ width: `${Math.min(100, (storage.breakdown.other / storage.used_bytes) * 100 * (pct / 100))}%` }} />
            </div>
            <div className="slegend">
              <span><i className="sdot" style={{ background: "#536dfe" }} />视频文件 {fmtSize(storage.breakdown.video)}</span>
              <span><i className="sdot" style={{ background: "#8b9bff" }} />字幕与转写 {fmtSize(storage.breakdown.subtitle)}</span>
              <span><i className="sdot" style={{ background: "#b9c3ff" }} />AI 总结与索引 {fmtSize(storage.breakdown.ai)}</span>
              <span><i className="sdot" style={{ background: "#d8dffb" }} />缩略图与其他 {fmtSize(storage.breakdown.other)}</span>
            </div>
            <div className="meta" style={{ marginTop: 13 }}>
              剩余可用 <span>{fmtSize(storage.free_bytes)}</span>　·　空间不足时新导入任务会被暂停
            </div>
          </div>

          <div className="scard">
            <div className="sectionline"><h2>占用空间最多的视频</h2><span className="muted">Top 5</span></div>
            <div className="slist">
              {(storage.top_videos || []).length === 0 && <div className="muted" style={{ padding: "10px 0" }}>暂无媒体文件</div>}
              {(storage.top_videos || []).map((t: any) => {
                const max = storage.top_videos[0]?.size_bytes || 1;
                return (
                  <div key={t.id} className="srow" onClick={() => onOpen(t.id)} style={{ cursor: "pointer" }}>
                    <b title={t.title}>{t.title}</b>
                    <div className="smini"><i style={{ width: `${Math.max(4, (t.size_bytes / max) * 100)}%` }} /></div>
                    <span className="ssize">{fmtSize(t.size_bytes)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {tasks.length > 0 && (
        <div className="taskpanel">
          <div className="thead">
            <h2>后台处理任务</h2>
            <span className="muted">
              {activeTasks.length ? `${activeTasks.length} 个进行中` : "全部完成"} · 共 {tasks.length} 个
            </span>
          </div>
          {tasks.slice(0, 8).map((t) => {
            const done = t.status === "done", failed = t.status === "error" || t.status === "failed";
            const cancelled = t.status === "cancelled" || t.control === "cancelled";
            const paused = !cancelled && !failed && (t.control === "paused" || t.status === "paused");
            let label = done ? "已完成" : failed ? `失败：${t.error?.message || "未知原因"}` :
              cancelled ? "已取消" : paused ? "已暂停" : `${t.stage || ""}`;
            const name = t.title || t.result?.video?.title || t.payload?.source || t.payload?.source_url || "导入任务";
            const progress = t.progress || 0;
            return (
              <div key={t.id} className={"task" + (done ? " done" : "") + (failed ? " failed" : "") + (paused ? " paused" : "")}>
                <div className="tinfo">
                  <div className="tname" title={name}>{name.length > 56 ? name.slice(0, 56) + "…" : name}</div>
                  <div className="tstep">{label}</div>
                </div>
                <div className="tbar"><i style={{ width: `${done ? 100 : progress}%` }} /></div>
                <div className="tstate">{done ? "完成" : failed ? "失败" : cancelled ? "取消" : paused ? "暂停" : `${progress}%`}</div>
                <div className="tbtns">
                  {!done && (failed || cancelled) && (
                    <button className="tbtn warn" onClick={() => taskAction(t.id, "retry")}>重试</button>
                  )}
                  {!done && !cancelled && !failed && (
                    paused ? (
                      <button className="tbtn" onClick={() => taskAction(t.id, "resume")}>继续</button>
                    ) : (
                      <button className="tbtn" onClick={() => taskAction(t.id, "pause")}>暂停</button>
                    )
                  )}
                  {!done && !cancelled && !failed && (
                    <button className="tbtn" onClick={() => taskAction(t.id, "cancel")}>取消</button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {favMode && (
        <div className="chiprow" style={{ marginTop: 4 }}>
          <button className={"chip" + (activeCol === "all" ? " active" : "")} onClick={() => setActiveCol("all")}>
            全部收藏 <b>{videos.filter(inFav).length}</b>
          </button>
          {collections.map((col) => (
            <span key={col.id} className="colwrap">
              <button
                className={"chip" + (activeCol === col.id ? " active" : "")}
                style={{ borderLeft: `3px solid ${col.color || "#536dfe"}` }}
                onClick={() => setActiveCol(col.id)}
              >
                {col.name} <b>{col.count ?? 0}</b>
              </button>
              <button className="coledit" title="重命名" onClick={async () => {
                const name = prompt("重命名收藏夹", col.name);
                if (!name || name === col.name) return;
                try { await api.renameCollection(col.id, name); onRefresh(); show("已重命名"); }
                catch (e: any) { show("重命名失败: " + e.message); }
              }}>✎</button>
              <button className="coledit danger" title="删除收藏夹" onClick={async () => {
                if (!confirm(`删除收藏夹「${col.name}」？视频本身不会被删除。`)) return;
                try {
                  await api.deleteCollection(col.id);
                  if (activeCol === col.id) setActiveCol("all");
                  onRefresh(); show("已删除收藏夹");
                } catch (e: any) { show("删除失败: " + e.message); }
              }}>×</button>
            </span>
          ))}
          <button className="chip" onClick={async () => {
            const name = prompt("新建收藏夹名称");
            if (!name) return;
            try { const r = await api.createCollection(name); onRefresh(); setActiveCol(r.collection.id); show("已创建：" + name); }
            catch (e: any) { show("创建失败: " + e.message); }
          }}>＋ 新建收藏夹</button>
        </div>
      )}

      <div className="sectionline" style={favMode ? { marginTop: 0 } : undefined}>
        <h2>{favMode ? "我的收藏" : "我的视频"}</h2>
        <span className="muted">共 {filtered.length} 个</span>
      </div>
      <div className="toolbar">
        <div className="search">
          <span>⌕</span>
          <input placeholder="搜索视频标题、作者..." value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {["all", "bilibili", "local"].map((p) => (
          <button key={p} className={"chip" + (pf === p ? " selected" : "")} onClick={() => setPf(p)}>
            {p === "all" ? "全部" : p === "bilibili" ? "B站" : "本地"}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="empty">{favMode ? "还没有收藏的视频。在卡片右上角点 ☆ 收藏。" : "还没有视频。点击右上角「导入视频」开始。"}</div>
      ) : (
        <div className="grid">
          {filtered.map((v, i) => (
            <article key={v.id} className={"video-card" + (v.favorite ? " faved" : "")} onClick={() => onOpen(v.id)}>
              <div className="cover" style={{ background: coverPalette[i % coverPalette.length] }}>
                <span className="platform">{v.platform === "bilibili" ? "B站" : "本地"}</span>
                <span>{v.title.slice(0, 28)}</span>
                <span className="duration">{fmtTime(v.duration_ms)}</span>
                <button
                  className={"favbtn" + (v.favorite ? " on" : "")}
                  title={v.favorite ? "取消收藏" : "加入收藏"}
                  onClick={(e) => openPicker(v, e)}
                >
                  {v.favorite ? "★" : "☆"}
                </button>
              </div>
              <div className="cardbody">
                <h3>{v.title}</h3>
                <div className="meta">
                  {v.author || "未知作者"}　·　{fmtTime(v.duration_ms)}
                  {v.size_bytes ? `　·　${fmtSize(v.size_bytes)}` : ""}
                </div>
                <div className="tags">
                  <span className={"tag" + (v.transcript_status === "complete" ? " ai" : " warn")}>
                    字幕 {v.transcript_status}
                  </span>
                  <span className="tag">媒体 {v.media_status}</span>
                </div>
              </div>
              <button
                className="card-del"
                title="删除视频"
                onClick={async (e) => {
                  e.stopPropagation();
                  if (!confirm(`确定删除「${v.title}」？将同时删除本地媒体与知识资产。`)) return;
                  try {
                    await api.deleteVideo(v.id, true, true);
                    onRefresh();
                  } catch (err: any) {
                    alert("删除失败: " + err.message);
                  }
                }}
              >
                ×
              </button>
            </article>
          ))}
        </div>
      )}

      {pickerVideo && (
        <CollectionPicker
          video={pickerVideo}
          collections={collections}
          onClose={() => setPickerVideo(null)}
          onChanged={async () => { await onRefresh(); }}
          show={show}
        />
      )}
    </div>
  );
}

function Detail({ id, onBack, show }: { id: string; onBack: () => void; show: (m: string) => void }) {
  const [data, setData] = useState<any>(null);
  const [tab, setTab] = useState<"summary" | "chapters" | "qa" | "notes">("summary");
  const [summary, setSummary] = useState<any>(null);
  const [chapters, setChapters] = useState<any[]>([]);
  const [points, setPoints] = useState<any[]>([]);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [busy, setBusy] = useState("");
  const [asrBusy, setAsrBusy] = useState(false);
  const [asrStage, setAsrStage] = useState("");
  const [punctBusy, setPunctBusy] = useState(false);
  const [punctStage, setPunctStage] = useState("");
  const [qaMsgs, setQaMsgs] = useState<any[]>([
    { role: "bot", text: "你好，我已经看完了这段视频。可以问我里面的概念、配置细节，或让我对比不同方案——回答会附上对应时间点，点一下就能跳到原片。" },
  ]);
  const [qaInput, setQaInput] = useState("");
  const [qaBusy, setQaBusy] = useState(false);
  const qaListRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (qaListRef.current) qaListRef.current.scrollTop = qaListRef.current.scrollHeight;
  }, [qaMsgs]);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [now, setNow] = useState(0);
  const [note, setNote] = useState("");
  const [reimportBusy, setReimportBusy] = useState(false);
  const [reimportStage, setReimportStage] = useState("");
  const [mediaError, setMediaError] = useState(false);

  async function loadDetail() {
    try {
      const d = await api.detail(id);
      setData(d);
      setMediaError(false);
      // 字幕取全量（detail 接口只返回前 200 条做摘要）
      try {
        const all = await api.transcript(id);
        setSegments(all || []);
      } catch {
        setSegments(d.segments || []);
      }
      const [s, c, p] = await Promise.all([
        fetch(`/api/videos/${id}/summary`).then((r) => r.json()).catch(() => null),
        fetch(`/api/videos/${id}/chapters`).then((r) => r.json()).catch(() => null),
        fetch(`/api/videos/${id}/knowledge-points`).then((r) => r.json()).catch(() => null),
      ]);
      setSummary(s?.summary || null);
      setChapters(c?.chapters || []);
      setPoints(p?.knowledge_points || []);
      setNote(localStorage.getItem("note:" + id) || "");
    } catch (e: any) {
      show("加载详情失败: " + e.message);
    }
  }

  useEffect(() => {
    loadDetail();
  }, [id]);

  // 媒体资产按创建时间升序返回，取最新一条（重新导入后旧资产仍在）
  const media: MediaAsset | undefined = data?.media_assets?.length
    ? data.media_assets[data.media_assets.length - 1]
    : undefined;
  const lastSave = useRef(0);
  const [startAt, setStartAt] = useState(0);

  useEffect(() => {
    (async () => {
      try {
        const p = await api.getProgress(id);
        if (p?.progress?.position_ms) setStartAt(p.progress.position_ms);
      } catch {}
    })();
  }, [id]);

  const onLoadedMeta = (e: React.SyntheticEvent<HTMLVideoElement>) => {
    const v = e.currentTarget;
    if (startAt > 0 && startAt < (v.duration * 1000) - 3000) v.currentTime = startAt / 1000;
  };

  const onTimeUpdate = (e: React.SyntheticEvent<HTMLVideoElement>) => {
    const v = e.currentTarget;
    setNow(v.currentTime * 1000);
    const t = Date.now();
    if (t - lastSave.current > 5000) {
      lastSave.current = t;
      api.saveProgress(id, Math.round(v.currentTime * 1000), Math.round((v.duration || 0) * 1000)).catch(() => {});
    }
  };

  const activeIdx = useMemo(() => {
    let idx = -1;
    for (let i = 0; i < segments.length; i++) {
      if (segments[i].start_ms <= now && now < segments[i].end_ms) idx = i;
    }
    return idx;
  }, [now, segments]);

  // 展示用：逐句合并成段（库中仍保留细粒度，用于精确定位）
  const paragraphs = useMemo(() => mergeCues(segments), [segments]);
  const activePara = useMemo(() => {
    let idx = -1;
    for (let i = 0; i < paragraphs.length; i++) {
      if (paragraphs[i].start_ms <= now && now < paragraphs[i].end_ms) idx = i;
    }
    return idx;
  }, [now, paragraphs]);

  // 章节分组：把字幕按章节切分（无章节时整段归入第一组）
  const chapterGroups = useMemo(() => {
    if (!paragraphs.length) return [];
    if (!chapters.length) {
      return [{ id: "all", title: "全部字幕", start_ms: paragraphs[0].start_ms, cues: paragraphs }];
    }
    const sorted = [...chapters]
      .filter((c: any) => c.start_ms != null)
      .sort((a: any, b: any) => a.start_ms - b.start_ms);
    if (!sorted.length) {
      return [{ id: "all", title: "全部字幕", start_ms: paragraphs[0].start_ms, cues: paragraphs }];
    }
    const groups: any[] = [];
    sorted.forEach((ch: any, i: number) => {
      const next = sorted[i + 1];
      const end = next ? next.start_ms : Infinity;
      const cues = paragraphs.filter((p) => p.start_ms >= ch.start_ms && p.start_ms < end);
      groups.push({ id: ch.id, title: ch.title, start_ms: ch.start_ms, cues });
    });
    // 早于第一个章节的字幕并入首章
    if (groups.length && paragraphs.some((p) => p.start_ms < groups[0].start_ms)) {
      const head = paragraphs.filter((p) => p.start_ms < groups[0].start_ms);
      groups[0] = { ...groups[0], cues: [...head, ...groups[0].cues] };
    }
    return groups;
  }, [chapters, paragraphs]);

  // 当前播放位置对应的章节
  const activeChapter = useMemo(() => {
    let idx = -1;
    for (let i = 0; i < chapterGroups.length; i++) {
      const g = chapterGroups[i];
      const next = chapterGroups[i + 1];
      if (now >= g.start_ms && (next ? now < next.start_ms : true)) idx = i;
    }
    return idx;
  }, [now, chapterGroups]);

  // 点击章节：跳转视频 + 滚动到对应字幕块
  const jumpChapter = (gi: number) => {
    const g = chapterGroups[gi];
    if (!g) return;
    seek(g.start_ms);
    const el = document.getElementById("tsec-" + gi);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const seek = (ms: number | null) => {
    if (ms == null || !videoRef.current) return;
    videoRef.current.currentTime = ms / 1000;
    videoRef.current.play().catch(() => {});
  };

  async function runAsr() {
    setAsrBusy(true);
    setAsrStage("提交 ASR 任务…");
    try {
      const r = await api.runAsr(id);
      if (!r.task_id) throw new Error(r.detail || "提交失败");
      const taskId = r.task_id;
      for (;;) {
        await new Promise((res) => setTimeout(res, 1000));
        const t = await api.getTask(taskId);
        setAsrStage(`${t.stage || ""} ${t.progress || 0}%`);
        if (t.status === "done") {
          show(`字幕已生成：${t.result?.asr?.cues ?? 0} 段`);
          const segs = await api.transcript(id);
          setSegments(segs);
          setAsrBusy(false);
          return;
        }
        if (t.status === "error") {
          throw new Error(t.error?.message || "ASR 失败");
        }
      }
    } catch (e: any) {
      show("ASR 失败: " + e.message);
      setAsrBusy(false);
    }
  }

  async function runPunctuate() {
    setPunctBusy(true);
    setPunctStage("提交标点恢复任务…");
    try {
      const r = await api.punctuate(id);
      if (!r.task_id) throw new Error(r.detail || "提交失败");
      const taskId = r.task_id;
      for (;;) {
        await new Promise((res) => setTimeout(res, 1000));
        const t = await api.getTask(taskId);
        setPunctStage(`${t.stage || ""} ${t.progress || 0}%`);
        if (t.status === "done") {
          show(`标点已补齐：${t.result?.changed}/${t.result?.total} 条`);
          const segs = await api.transcript(id);
          setSegments(segs);
          setPunctBusy(false);
          return;
        }
        if (t.status === "error") {
          throw new Error(t.error?.message || "标点恢复失败");
        }
      }
    } catch (e: any) {
      show("标点恢复失败: " + e.message);
      setPunctBusy(false);
    }
  }

  async function reimport() {
    if (reimportBusy) return;
    setReimportBusy(true);
    setReimportStage("提交重新导入任务…");
    try {
      const r = await api.reimportVideo(id);
      if (!r.task_id) throw new Error(r.detail || "提交失败");
      for (;;) {
        await new Promise((res) => setTimeout(res, 1000));
        const t = await api.getTask(r.task_id);
        setReimportStage(`${t.stage || ""} ${t.progress || 0}%`);
        if (t.status === "done") {
          show("重新导入完成");
          await loadDetail();
          setReimportBusy(false);
          setReimportStage("");
          return;
        }
        if (t.status === "error") throw new Error(t.error?.message || "重新导入失败");
      }
    } catch (e: any) {
      show("重新导入失败: " + e.message);
      setReimportBusy(false);
    }
  }

  async function ask(question?: string) {
    const q = (question ?? qaInput).trim();
    if (!q || qaBusy) return;
    setQaInput("");
    setQaBusy(true);
    setQaMsgs((prev) => [...prev, { role: "me", text: q }, { role: "bot", text: "", streaming: true }]);
    try {
      let acc = "";
      const citations = await askQa(id, q, (delta) => {
        acc += delta;
        setQaMsgs((prev) => {
          const next = [...prev];
          // 更新最后一条 bot 消息
          for (let i = next.length - 1; i >= 0; i--) {
            if (next[i].role === "bot" && next[i].streaming) {
              next[i] = { ...next[i], text: acc };
              break;
            }
          }
          return next;
        });
      });
      setQaMsgs((prev) => {
        const next = [...prev];
        for (let i = next.length - 1; i >= 0; i--) {
          if (next[i].role === "bot" && next[i].streaming) {
            next[i] = { role: "bot", text: acc || "（没有返回内容）", citations };
            break;
          }
        }
        return next;
      });
    } catch (e: any) {
      setQaMsgs((prev) => {
        const next = [...prev];
        for (let i = next.length - 1; i >= 0; i--) {
          if (next[i].role === "bot" && next[i].streaming) {
            next[i] = { role: "bot", text: "回答失败：" + e.message, error: true };
            break;
          }
        }
        return next;
      });
    } finally {
      setQaBusy(false);
    }
  }

  function renderAnswerText(text: string) {
    // 把【mm:ss】渲染为可点击时间点
    const parts: any[] = [];
    const re = /【(\d{1,3}):([0-5]\d)】/g;
    let last = 0, m: RegExpExecArray | null, key = 0;
    while ((m = re.exec(text))) {
      if (m.index > last) parts.push(text.slice(last, m.index));
      const ms = (parseInt(m[1]) * 60 + parseInt(m[2])) * 1000;
      parts.push(
        <button key={"c" + key++} className="cite" onClick={() => seek(ms)}>{m[1]}:{m[2]}</button>
      );
      last = m.index + m[0].length;
    }
    if (last < text.length) parts.push(text.slice(last));
    return parts;
  }

  async function analyze(kind: "summary" | "chapters" | "points") {    setBusy(kind);
    try {
      const url =
        kind === "summary" ? "/api/analysis/summary" : kind === "chapters" ? "/api/analysis/chapters" : "/api/analysis/points";
      const body = kind === "summary" ? { video_id: id, mode: "deep", content_scope: data?.video?.content_scope || "unknown" } : { video_id: id };
      const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || "分析失败");
      if (kind === "summary") setSummary(j.summary);
      if (kind === "chapters") setChapters(j.chapters);
      if (kind === "points") setPoints(j.knowledge_points);
      show("生成完成");
    } catch (e: any) {
      show("生成失败: " + e.message + "（需配置 LLM API Key）");
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <div className="detail-head">
        <button className="back" onClick={onBack}>
          ← 返回视频库
        </button>
        <span className="detail-title">{data?.video?.title || "加载中..."}</span>
        <span className="detail-meta">
          {data?.video?.platform === "bilibili" ? "B站" : "本地"} · {fmtTime(data?.video?.duration_ms || 0)}
        </span>
      </div>

      <div className="workspace">
        <div className="leftcol">
          <div className="player">
            {media && !mediaError ? (
              <video
                ref={videoRef}
                controls
                src={api.mediaUrl(id, media.id)}
                onLoadedMetadata={onLoadedMeta}
                onTimeUpdate={onTimeUpdate}
                onError={() => setMediaError(true)}
              />
            ) : (
              <div className="player-empty" style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
                <div>{media ? "本地媒体文件已失效，无法播放" : "暂无本地媒体，无法本地播放"}</div>
                <button className="btn soft" disabled={reimportBusy} onClick={reimport}>
                  {reimportBusy ? <span className="spin" /> : "重新导入"}
                </button>
                {reimportBusy && reimportStage && <div className="meta">{reimportStage}</div>}
              </div>
            )}
          </div>
          <div className="source-note">
            ⓘ 本地播放（HTTP Range 支持拖动）· 编码 {media?.video_codec || "?"} {media ? `${media.width}x${media.height}` : ""}
          </div>

          <div className="sectionline">
            <h2>学习信息</h2>
            <span className="muted">自动保存学习进度</span>
          </div>
          <div className="panel">
            <div className="panelcontent">
              <div className="meta">
                媒体资产 {data?.media_assets?.length || 0} 个 · 字幕轨 {data?.caption_tracks?.length || 0} 条
              </div>
              <div className="right-actions">
                <button className="btn soft" onClick={() => show("已加入收藏")}>
                  ☆ 收藏
                </button>
                <button
                  className="btn"
                  onClick={() => {
                    const url = data?.video?.source_url;
                    if (!url) {
                      show("该视频没有可跳转的原平台链接");
                      return;
                    }
                    const w = window.open(url, "_blank", "noopener,noreferrer");
                    if (!w) show("浏览器拦截了新窗口，请允许弹窗后重试");
                  }}
                >
                  ↗ 原平台
                </button>
                <button
                  className="btn"
                  onClick={async () => {
                    if (!confirm("确定删除该视频？（将同时删除媒体与知识资产）")) return;
                    await api.deleteVideo(id, true, true);
                    show("已删除");
                    onBack();
                  }}
                >
                  删除
                </button>
              </div>
            </div>
          </div>
          <div className="sectionline">
            <h2>学习笔记</h2>
            <span className="muted">自动保存到本地</span>
          </div>
          <div className="panel">
            <div className="panelcontent">
              <textarea
                className="notearea"
                value={note}
                placeholder="记录你的理解、疑问、命令或代码片段……"
                onChange={(e) => setNote(e.target.value)}
              />
              <div className="right-actions">
                <button
                  className="btn primary"
                  onClick={async () => {
                    try {
                      if (note.trim()) await api.saveNote(id, note.trim());
                      localStorage.setItem("note:" + id, note);
                      show("笔记已保存到数据库");
                    } catch (e: any) {
                      show("保存失败: " + e.message);
                    }
                  }}
                >
                  保存笔记
                </button>
                <a className="btn" href={api.exportUrl(id)} target="_blank" rel="noreferrer">
                  导出 Markdown
                </a>
              </div>
            </div>
          </div>
        </div>

        <div className="rightcol">
          <div className="panel">
            <div className="tabs">
              {(
                [
                  ["summary", "AI 总结"],
                  ["chapters", "章节与字幕"],
                  ["qa", "AI 问答"],
                  ["notes", "笔记"],
                ] as const
              ).map(([k, label]) => (
                <button key={k} className={"tab" + (tab === k ? " active" : "")} onClick={() => setTab(k as any)}>
                  {label}
                </button>
              ))}
            </div>

            <div className="panelcontent">
              {tab === "summary" && (
                <div>
                  <div className="summary-top">
                    <h3>核心内容总结</h3>
                    <span className="mode">{summary?.mode || "未生成"}</span>
                  </div>
                  {summary ? (
                    <>
                      <div className="summary-intro">
                        <strong>一句话概括</strong>
                        <br />
                        {summary.content?.one_liner}
                      </div>
                      <div className="content-block">
                        <h4>核心要点</h4>
                        <ul>
                          {(summary.content?.key_points || []).map((p: string, i: number) => (
                            <li key={i}>{p}</li>
                          ))}
                        </ul>
                      </div>
                      {summary.content?.terms?.length ? (
                        <div className="content-block">
                          <h4>关键术语</h4>
                          <div className="tags">
                            {summary.content.terms.map((t: string, i: number) => (
                              <span key={i} className="tag">
                                {t}
                              </span>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </>
                  ) : (
                    <div className="empty">尚未生成总结</div>
                  )}
                  <div className="right-actions">
                    <button className="btn soft" disabled={!!busy} onClick={() => analyze("summary")}>
                      {busy === "summary" ? <span className="spin" /> : "生成总结"}
                    </button>
                  </div>
                </div>
              )}

              {tab === "chapters" && (
                <div>
                  <div className="summary-top">
                    <h3>章节与字幕</h3>
                    <span className="mode">
                      {chapters.length} 个章节 · {paragraphs.length} 段字幕
                    </span>
                  </div>

                  {segments.length > 0 && (
                    <div className="right-actions" style={{ marginTop: 0, marginBottom: 12 }}>
                      <button className="btn soft" disabled={punctBusy} onClick={() => runPunctuate()}>
                        {punctBusy ? <span className="spin" /> : "补标点"}
                      </button>
                      {punctBusy && <span className="meta">{punctStage}</span>}
                    </div>
                  )}

                  {/* 章节 chip 行：点击跳转并定位到对应字幕块 */}
                  {chapterGroups.length > 0 && (
                    <div className="chiprow">
                      {chapterGroups.map((g, gi) => (
                        <button
                          key={g.id || gi}
                          className={"chip" + (activeChapter === gi ? " active" : "")}
                          onClick={() => jumpChapter(gi)}
                        >
                          {fmtTime(g.start_ms)} {g.title}
                        </button>
                      ))}
                    </div>
                  )}

                  {chapters.length === 0 && (
                    <div className="right-actions" style={{ marginTop: 0, marginBottom: 12 }}>
                      <button className="btn soft" disabled={!!busy} onClick={() => analyze("chapters")}>
                        {busy === "chapters" ? <span className="spin" /> : "生成章节"}
                      </button>
                    </div>
                  )}

                  {segments.length === 0 && (
                    <div className="empty">
                      暂无字幕
                      <div style={{ marginTop: 12 }}>
                        <button className="btn soft" disabled={asrBusy} onClick={() => runAsr()}>
                          {asrBusy ? <span className="spin" /> : "运行本地 ASR 生成字幕"}
                        </button>
                      </div>
                      {asrBusy && <div className="meta" style={{ marginTop: 8 }}>{asrStage}</div>}
                    </div>
                  )}

                  {/* 按章节分组展示字幕 */}
                  {chapterGroups.map((g, gi) => (
                    <div key={g.id || gi} id={"tsec-" + gi} className={"tsec" + (activeChapter === gi ? " active" : "")}>
                      <button className="tsec-head" onClick={() => jumpChapter(gi)}>
                        <span className="time">{fmtTime(g.start_ms)}</span>
                        <b>{g.title}</b>
                        <small className="muted">{g.cues.length} 段</small>
                      </button>
                      <div className="tsec-body">
                        {g.cues.map((p, i) => (
                          <p
                            key={p.id || i}
                            onClick={() => seek(p.start_ms)}
                            style={{
                              cursor: "pointer",
                              color: paragraphs[activePara]?.id === p.id ? "var(--blue)" : undefined,
                            }}
                          >
                            <span className="time">{fmtTime(p.start_ms)}</span> {p.text}
                          </p>
                        ))}
                      </div>
                    </div>
                  ))}

                  {chapterGroups.length === 0 && segments.length > 0 && (
                    <div className="transcript">
                      {paragraphs.map((p, i) => (
                        <button
                          key={p.id || i}
                          className={"line" + (paragraphs[activePara]?.id === p.id ? " active" : "")}
                          onClick={() => seek(p.start_ms)}
                        >
                          <span className="time">{fmtTime(p.start_ms)}</span> {p.text}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {tab === "qa" && (
                <div>
                  <div className="summary-top">
                    <h3>视频问答</h3>
                    <span className="mode">基于本视频内容 · 会标注时间点</span>
                  </div>
                  <div className="qa-list" ref={qaListRef}>
                    {qaMsgs.map((m, i) => (
                      <div key={i} className={"qa " + (m.role === "me" ? "me" : "bot")}>
                        <div className="qa-av">{m.role === "me" ? "我" : "AI"}</div>
                        <div className="qa-bub">
                          {m.role === "me" ? m.text : (
                            m.streaming && !m.text
                              ? <span className="qa-thinking"><i /><i /><i /></span>
                              : <>
                                  {renderAnswerText(m.text)}
                                  {m.streaming && <span className="typing-cursor" />}
                                </>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="qa-sugs">
                    {["这个视频主要讲了什么？", "有没有关键结论或数据？", "有哪些值得注意的坑？", "总结一下核心观点"].map((s) => (
                      <button key={s} className="chip" disabled={qaBusy} onClick={() => ask(s)}>{s}</button>
                    ))}
                  </div>
                  <div className="qa-input">
                    <input
                      placeholder="输入你的问题，回车发送…"
                      value={qaInput}
                      disabled={qaBusy}
                      onChange={(e) => setQaInput(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") ask(); }}
                    />
                    <button className="btn primary" disabled={qaBusy} onClick={() => ask()}>
                      {qaBusy ? <span className="spin" /> : "发送"}
                    </button>
                  </div>
                  {segments.length === 0 && (
                    <p className="muted" style={{ marginTop: 10 }}>该视频还没有字幕，问答不可用。请先在「章节与字幕」里生成字幕。</p>
                  )}
                </div>
              )}

              {tab === "notes" && (
                <div>
                  <div className="summary-top"><h3>知识点与来源</h3><span className="mode">{points.length} 条</span></div>
                  <div className="right-actions" style={{ marginTop: 0, marginBottom: 12 }}>
                    <button className="btn soft" disabled={!!busy} onClick={() => analyze("points")}>
                      {busy === "points" ? <span className="spin" /> : "生成知识点"}
                    </button>
                  </div>
                  {points.length === 0 && <div className="empty">尚未生成知识点</div>}
                  {points.map((p) => (
                    <div key={p.id} className="kp" onClick={() => seek(p.start_ms)}>
                      <b>{p.title}</b>
                      <p>{p.content}</p>
                    </div>
                  ))}
                  <div className="content-block" style={{ marginTop: 18 }}>
                    <h4>来源与状态</h4>
                    <p className="muted">来源：{data?.video?.source_url || "本地文件"}</p>
                    <p className="muted">媒体：{data?.video?.media_status}　字幕：{data?.video?.transcript_status}</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function ImportModal({ onClose, onDone, show }: { onClose: () => void; onDone: () => void; show: (m: string) => void }) {
  const [text, setText] = useState("");
  const [maxHeight, setMaxHeight] = useState<number | "">("");
  const [cookie, setCookie] = useState("");
  const [autoAsr, setAutoAsr] = useState(true);
  const [autoPunct, setAutoPunct] = useState(true);
  const [bg, setBg] = useState(true);
  const [busy, setBusy] = useState(false);

  const sources = text.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);

  // ---- B站收藏夹（登录态） ----
  const [favUser, setFavUser] = useState("");
  const [favFolders, setFavFolders] = useState<any[]>([]);
  const [favLoading, setFavLoading] = useState(false);
  const [activeFolder, setActiveFolder] = useState<any | null>(null);
  const [favItems, setFavItems] = useState<any[]>([]);
  const [favSel, setFavSel] = useState<string[]>([]);
  const [favPage, setFavPage] = useState(1);
  const [favHasMore, setFavHasMore] = useState(false);

  async function loadFavFolders() {
    if (!cookie.trim()) return show("请先在上方粘贴 B站 Cookie（需含 SESSDATA）");
    setFavLoading(true);
    try {
      await api.setCredential(cookie.trim());
      const r = await api.biliFavFolders();
      if (!r.ok) throw new Error(r.error?.message || "读取失败");
      setFavUser(r.uname || "");
      setFavFolders(r.folders || []);
      if (!(r.folders || []).length) show("该账号没有收藏夹");
    } catch (e: any) {
      show("读取收藏夹失败: " + e.message);
    } finally {
      setFavLoading(false);
    }
  }

  async function openFolder(f: any, page = 1) {
    setActiveFolder(f);
    setFavPage(page);
    setFavLoading(true);
    try {
      const r = await api.biliFavItems(String(f.id), page);
      if (!r.ok) throw new Error(r.error?.message || "读取失败");
      setFavItems(page === 1 ? r.items : [...favItems, ...r.items]);
      setFavHasMore(!!r.has_more);
    } catch (e: any) {
      show("读取收藏夹内容失败: " + e.message);
    } finally {
      setFavLoading(false);
    }
  }

  function toggleFavItem(bvid: string) {
    setFavSel((prev) => (prev.includes(bvid) ? prev.filter((x) => x !== bvid) : [...prev, bvid]));
  }

  function importFavSelected() {
    const list = favSel.map((b) => `https://www.bilibili.com/video/${b}`);
    if (!list.length) return show("请先勾选要导入的视频");
    submit(false, list);
  }

  async function submit(force = false, explicit?: string[]) {
    const list = explicit && explicit.length ? explicit : sources;
    if (!list.length) return show("请至少粘贴一个链接或文件路径");
    if (list.length > 20) return show("单次最多 20 条，请分批导入");
    setBusy(true);
    try {
      if (cookie.trim()) {
        await api.setCredential(cookie.trim());
        show("Cookie 已加密保存");
      }
      const opts: any = {
        max_height: maxHeight === "" ? undefined : maxHeight,
        auto_asr: autoAsr,
        auto_punctuate: autoPunct,
        allow_over_threshold: force,
      };
      const r = await api.intakeBatch(list, opts);
      show(`已加入后台队列：${r.count} 个视频`);
      onDone();
    } catch (e: any) {
      const msg = String(e.message || "");
      if (msg.includes("超过阈值")) {
        if (confirm(msg + "\n\n仍要强制导入吗？")) {
          setBusy(false);
          return submit(true);
        }
      } else {
        show("导入失败: " + msg);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modalback" onClick={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="modal">
        <h2>批量导入视频</h2>
        <p>粘贴 Bilibili / 抖音链接或本地文件路径，<b>每行一个</b>。提交后在后台排队处理，可以离开当前页面。</p>
        <textarea
          className="importarea"
          placeholder={"https://www.bilibili.com/video/BV1xx411c7mD\nhttps://www.bilibili.com/video/BV1yy411c7mE\nD:\\\\videos\\\\local.mp4"}
          value={text}
          disabled={busy}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="meta" style={{ marginBottom: 8 }}>
          已识别 <b>{sources.length}</b> 条（单次最多 20 条）　·　最高清晰度：
          <select
            value={maxHeight}
            disabled={busy}
            onChange={(e) => setMaxHeight(e.target.value === "" ? "" : Number(e.target.value))}
            style={{ width: "auto", display: "inline-block", padding: "6px 10px", margin: 0 }}
          >
            <option value="">自动</option>
            <option value={1080}>1080P</option>
            <option value={720}>720P</option>
            <option value={480}>480P</option>
            <option value={360}>360P</option>
          </select>
        </div>
        <textarea
          className="importarea"
          style={{ minHeight: 60 }}
          placeholder="（可选）粘贴 B站 SESSDATA 或完整 Cookie，用于获取平台字幕/高清。仅本地加密保存。"
          value={cookie}
          disabled={busy}
          onChange={(e) => setCookie(e.target.value)}
        />
        <div style={{ border: "1px solid #e3e6ee", borderRadius: 10, padding: 10, marginBottom: 10 }}>
          <div className="meta" style={{ marginBottom: 8 }}>
            <b>从 B站收藏夹导入</b>　·　先粘贴含 SESSDATA 的 Cookie，再读取你的收藏夹
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <button className="btn" onClick={loadFavFolders} disabled={busy || favLoading}>
              {favLoading ? <span className="spin" /> : "读取我的收藏夹"}
            </button>
            {favUser && <span className="meta">已登录：{favUser}</span>}
          </div>
          {favFolders.length > 0 && (
            <div className="chiprow" style={{ marginTop: 10 }}>
              {favFolders.map((f) => (
                <button
                  key={f.id}
                  className={"chip" + (activeFolder?.id === f.id ? " active" : "")}
                  onClick={() => { setFavSel([]); openFolder(f, 1); }}
                >
                  {f.title} <b>{f.count ?? 0}</b>
                </button>
              ))}
            </div>
          )}
          {activeFolder && (
            <div style={{ marginTop: 10 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 6 }}>
                <span className="meta">共 {activeFolder.count ?? favItems.length} 个　·　已选 {favSel.length}</span>
                <button className="chip" onClick={() => setFavSel(favItems.map((x) => x.bvid))}>全选本页</button>
                <button className="chip" onClick={() => setFavSel([])}>清空</button>
                <button className="btn primary" disabled={busy || !favSel.length} onClick={importFavSelected}>
                  导入选中（{favSel.length}）
                </button>
              </div>
              <div style={{ maxHeight: 200, overflowY: "auto" }}>
                {favItems.map((it) => (
                  <label key={it.bvid} className="checkline" title={it.title}>
                    <input
                      type="checkbox"
                      checked={favSel.includes(it.bvid)}
                      disabled={busy}
                      onChange={() => toggleFavItem(it.bvid)}
                    />
                    <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {it.title}
                    </span>
                    <span className="meta" style={{ marginLeft: 8 }}>{fmtTime((it.duration_s || 0) * 1000)}</span>
                  </label>
                ))}
                {favItems.length === 0 && <div className="muted" style={{ padding: "6px 0" }}>该收藏夹为空</div>}
              </div>
              {favHasMore && (
                <button className="chip" disabled={favLoading} onClick={() => openFolder(activeFolder, favPage + 1)}>
                  {favLoading ? "加载中…" : "加载更多"}
                </button>
              )}
            </div>
          )}
        </div>
        <label className="checkline">
          <input type="checkbox" checked={bg} disabled={busy} onChange={(e) => setBg(e.target.checked)} />
          提交后立即在后台执行（可离开页面）
        </label>
        <label className="checkline">
          <input type="checkbox" checked={autoAsr} disabled={busy} onChange={(e) => setAutoAsr(e.target.checked)} />
          无字幕时自动用本地 faster-whisper 识别
        </label>
        <label className="checkline">
          <input type="checkbox" checked={autoPunct} disabled={busy} onChange={(e) => setAutoPunct(e.target.checked)} />
          为识别出的字幕自动补标点（云端 AI，仅发送字幕文本）
        </label>
        <div className="modalfoot">
          <button className="btn" onClick={onClose} disabled={busy}>取消</button>
          <button className="btn primary" onClick={() => submit(false)} disabled={busy}>
            {busy ? <span className="spin" /> : `开始导入${sources.length ? "（" + sources.length + "）" : ""}`}
          </button>
        </div>
      </div>
    </div>
  );
}

function CollectionPicker({ video, collections, onClose, onChanged, show }: {
  video: Video;
  collections: Collection[];
  onClose: () => void;
  onChanged: () => Promise<void> | void;
  show: (m: string) => void;
}) {
  const initial = (video.collection_ids || "").split(",").filter(Boolean);
  const [selected, setSelected] = useState<string[]>(initial);
  const [busy, setBusy] = useState(false);
  const [list, setList] = useState<Collection[]>(collections);

  async function reload() {
    const r = await api.collections().catch(() => null);
    if (r) setList(r.collections || []);
  }

  async function toggle(id: string) {
    setBusy(true);
    try {
      await api.toggleVideoCollection(video.id, id);
      const r = await api.videoCollections(video.id);
      setSelected(r.collection_ids || []);
      await reload();
      await onChanged();
    } catch (e: any) {
      show("操作失败: " + e.message);
    } finally {
      setBusy(false);
    }
  }

  async function createNew() {
    const name = prompt("新建收藏夹名称");
    if (!name) return;
    try {
      const r = await api.createCollection(name);
      await reload();
      await toggle(r.collection.id);
    } catch (e: any) {
      show("创建失败: " + e.message);
    }
  }

  return (
    <div className="modalback" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ width: "min(460px,100%)" }}>
        <h2>加入收藏夹</h2>
        <p style={{ marginBottom: 12 }}>{video.title}</p>
        <div className="collist">
          {list.length === 0 && <div className="muted" style={{ padding: "8px 0" }}>还没有收藏夹，点下方新建。</div>}
          {list.map((col) => {
            const on = selected.includes(col.id);
            return (
              <label key={col.id} className="colitem">
                <input type="checkbox" checked={on} disabled={busy} onChange={() => toggle(col.id)} />
                <span className="coldot" style={{ background: col.color || "#536dfe" }} />
                <span className="colname">{col.name}</span>
                <span className="muted">{col.count ?? 0}</span>
              </label>
            );
          })}
        </div>
        <div className="modalfoot" style={{ marginTop: 14 }}>
          <button className="btn" onClick={createNew} disabled={busy}>＋ 新建收藏夹</button>
          <button className="btn primary" onClick={onClose} disabled={busy}>完成</button>
        </div>
      </div>
    </div>
  );
}

