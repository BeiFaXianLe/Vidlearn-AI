import { useEffect, useState } from "react";
import { api } from "./api";

/**
 * 设置页：身份认证门户 + 个人职业档案。
 *
 * 设计意图：设置是「配置层」，不该抢主内容区的戏。左侧锚点导航，右侧单列窄栏；
 * 认证渠道用「状态点」表达通没通，而不是堆卡片。
 */

type CredInfo = { ok?: boolean; status?: string; keys?: string[]; backend?: string };

type Profile = { career: string; tags: string[]; goal: string; industry: string };

const CHANNELS = [
  {
    id: "bilibili" as const,
    name: "哔哩哔哩",
    mark: "B",
    hint: "关注列表、收藏夹、1080P 高清等需要登录状态。",
    placeholder: "粘贴 SESSDATA 或完整 Cookie",
  },
  {
    id: "douyin" as const,
    name: "抖音",
    mark: "抖",
    hint: "私密作品、部分高清需要登录态；公开视频不登录也能下载。",
    placeholder: "ttwid / s_v_web_id / odin_tt …（可点右侧扫码）",
  },
];

export default function SettingsPage({ show }: { show: (m: string) => void }) {
  const [section, setSection] = useState<"auth" | "career">("auth");
  const [cred, setCred] = useState<Record<string, CredInfo>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [tab, setTab] = useState<"bilibili" | "douyin">("bilibili");
  const [pending, setPending] = useState<Record<string, string>>({});

  const [profile, setProfile] = useState<Profile>({ career: "", tags: [], goal: "", industry: "" });
  const [careerTags, setCareerTags] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  async function loadCreds() {
    for (const c of CHANNELS) {
      try {
        const r = await api.credentialStatus(c.id);
        setCred((s) => ({ ...s, [c.id]: r }));
      } catch {}
    }
  }
  async function loadProfile() {
    try {
      const r = await api.getProfile();
      if (r?.ok) {
        setProfile({
          career: r.profile?.career || "",
          tags: r.profile?.tags || [],
          goal: r.profile?.goal || "",
          industry: r.profile?.industry || "",
        });
        setCareerTags(r.career_tags || []);
      }
    } catch {}
  }
  useEffect(() => {
    loadCreds();
    loadProfile();
  }, []);

  async function saveCookie(pf: "bilibili" | "douyin") {
    const raw = (drafts[pf] || "").trim();
    if (!raw) return show("请先粘贴 Cookie");
    setPending((s) => ({ ...s, [pf]: "save" }));
    try {
      await api.setCredential(raw, pf);
      const st = await api.credentialStatus(pf);
      setCred((s) => ({ ...s, [pf]: st }));
      setDrafts((s) => ({ ...s, [pf]: "" }));
      show("已加密保存");
    } catch (e: any) {
      show("保存失败: " + e.message);
    } finally {
      setPending((s) => ({ ...s, [pf]: "" }));
    }
  }
  async function verifyCookie(pf: "bilibili" | "douyin") {
    setPending((s) => ({ ...s, [pf]: "verify" }));
    try {
      const r = await api.verifyCredential(pf);
      show(r.ok ? (r.uname ? "登录有效：" + r.uname : r.message || "检测通过") : "未通过：" + (r.message || ""));
      const st = await api.credentialStatus(pf);
      setCred((s) => ({ ...s, [pf]: st }));
    } catch (e: any) {
      show("检测失败: " + e.message);
    } finally {
      setPending((s) => ({ ...s, [pf]: "" }));
    }
  }
  async function clearCookie(pf: "bilibili" | "douyin") {
    try {
      await api.clearCredential(pf);
      const st = await api.credentialStatus(pf);
      setCred((s) => ({ ...s, [pf]: st }));
      show("已清除");
    } catch (e: any) {
      show("清除失败: " + e.message);
    }
  }
  async function douyinLogin() {
    setPending((s) => ({ ...s, douyin: "login" }));
    try {
      const r = await api.douyinCdpLogin();
      show(r?.ok ? r.message : "启动失败: " + (r?.message || ""));
    } catch (e: any) {
      show("启动浏览器失败: " + e.message);
    } finally {
      setPending((s) => ({ ...s, douyin: "" }));
    }
  }
  async function douyinFetch() {
    setPending((s) => ({ ...s, douyin: "fetch" }));
    try {
      const r = await api.douyinCdpCookie();
      if (r?.ok) {
        setCred((s) => ({ ...s, douyin: r }));
        show(`已采集 ${r.count} 项登录信息`);
      } else show("获取失败：" + (r?.message || ""));
    } catch (e: any) {
      show("获取失败: " + e.message);
    } finally {
      setPending((s) => ({ ...s, douyin: "" }));
    }
  }

  function toggleTag(t: string) {
    setProfile((p) => ({
      ...p,
      tags: p.tags.includes(t) ? p.tags.filter((x) => x !== t) : [...p.tags, t].slice(0, 6),
    }));
  }
  async function saveCareer() {
    setSaving(true);
    try {
      await api.saveProfile(profile);
      show("职业档案已保存，之后的 AI 总结会带上针对你的建议");
    } catch (e: any) {
      show("保存失败: " + e.message);
    } finally {
      setSaving(false);
    }
  }

  const connected = (id: string) => cred[id]?.status === "valid";

  return (
    <div className="setpage">
      <div className="sethead">
        <h1>设置</h1>
        <p className="sub">管理各平台的登录状态，告诉 AI 你是谁。</p>
      </div>

      <div className="setbody">
        <nav className="setnav" aria-label="设置分区">
          <button
            className={"setnav-item" + (section === "auth" ? " active" : "")}
            onClick={() => setSection("auth")}
          >
            <span>身份认证</span>
            <i className="dotrow">
              {CHANNELS.map((c) => (
                <i key={c.id} className={"mini-dot" + (connected(c.id) ? " on" : "")} />
              ))}
            </i>
          </button>
          <button
            className={"setnav-item" + (section === "career" ? " active" : "")}
            onClick={() => setSection("career")}
          >
            <span>个人职业</span>
            {profile.career ? <i className="mini-dot on" /> : null}
          </button>
        </nav>

        <div className="setmain">
          {section === "auth" && (
            <section aria-labelledby="auth-title">
              <div className="sec-head">
                <h2 id="auth-title">身份认证</h2>
                <p>认证一次，长期有效；不认证也能用，只是部分内容受限。</p>
              </div>

              <div className="chan-tabs" role="tablist">
                {CHANNELS.map((c) => (
                  <button
                    key={c.id}
                    role="tab"
                    aria-selected={tab === c.id}
                    className={"chan-tab" + (tab === c.id ? " on" : "")}
                    onClick={() => setTab(c.id)}
                  >
                    <b className={"chan-mark mark-" + c.id}>{c.mark}</b>
                    {c.name}
                    <i className={"status-dot" + (connected(c.id) ? " on" : "")} />
                  </button>
                ))}
              </div>

              {CHANNELS.filter((c) => c.id === tab).map((c) => (
                <div className="chan-body" key={c.id}>
                  <div className="chan-state">
                    <span className={"status-dot" + (connected(c.id) ? " on" : "")} />
                    <b>{connected(c.id) ? "已连接" : "未连接"}</b>
                    <span className="muted">
                      {connected(c.id)
                        ? `已保存 ${cred[c.id]?.keys?.length || 0} 项，本机加密存储`
                        : "尚未配置登录状态"}
                    </span>
                  </div>

                  <p className="chan-hint">{c.hint}</p>

                  <label className="field">
                    <span>粘贴 Cookie</span>
                    <textarea
                      value={drafts[c.id] || ""}
                      onChange={(e) => setDrafts((s) => ({ ...s, [c.id]: e.target.value }))}
                      placeholder={c.placeholder}
                      spellCheck={false}
                    />
                  </label>

                  <div className="act-row">
                    <button className="btn primary" disabled={!!pending[c.id]}
                      onClick={() => saveCookie(c.id)}>
                      {pending[c.id] === "save" ? "保存中…" : "保存"}
                    </button>
                    <button className="btn" disabled={!!pending[c.id]}
                      onClick={() => verifyCookie(c.id)}>
                      {pending[c.id] === "verify" ? "检测中…" : "检测登录"}
                    </button>
                    {c.id === "douyin" && (
                      <>
                        <button className="btn" disabled={!!pending[c.id]} onClick={douyinLogin}>
                          {pending[c.id] === "login" ? "启动中…" : "扫码登录"}
                        </button>
                        <button className="btn soft" disabled={!!pending[c.id]} onClick={douyinFetch}>
                          {pending[c.id] === "fetch" ? "采集…" : "从浏览器获取"}
                        </button>
                      </>
                    )}
                    {connected(c.id) && (
                      <button className="linkbtn" disabled={!!pending[c.id]}
                        onClick={() => clearCookie(c.id)}>
                        解除认证
                      </button>
                    )}
                  </div>

                  {c.id === "douyin" && (
                    <p className="foot-note">
                      扫码登录会打开一个独立浏览器窗口，登录后点「从浏览器获取」把登录状态取回来。
                    </p>
                  )}
                </div>
              ))}
            </section>
          )}

          {section === "career" && (
            <section aria-labelledby="career-title">
              <div className="sec-head">
                <h2 id="career-title">个人职业</h2>
                <p>填好之后，每份 AI 总结会多一段「这对你的职业有什么用」。</p>
              </div>

              <label className="field">
                <span>你的职业</span>
                <input
                  value={profile.career}
                  onChange={(e) => setProfile((p) => ({ ...p, career: e.target.value }))}
                  placeholder="例如：前端工程师、产品经理、中学教师"
                />
              </label>

              {careerTags.length > 0 && (
                <div className="field">
                  <span>常用标签（可多选，最多 6 个）</span>
                  <div className="tagpick">
                    {careerTags.map((t) => (
                      <button
                        key={t}
                        className={"tagchip" + (profile.tags.includes(t) ? " on" : "")}
                        onClick={() => toggleTag(t)}
                      >
                        {t}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <label className="field">
                <span>所在行业 <em>选填</em></span>
                <input
                  value={profile.industry}
                  onChange={(e) => setProfile((p) => ({ ...p, industry: e.target.value }))}
                  placeholder="例如：互联网、教育、医疗"
                />
              </label>

              <label className="field">
                <span>近期想达成的目标 <em>选填</em></span>
                <textarea
                  value={profile.goal}
                  onChange={(e) => setProfile((p) => ({ ...p, goal: e.target.value }))}
                  placeholder="例如：半年内独立负责一个项目；想转做数据分析"
                  style={{ minHeight: 66 }}
                />
              </label>

              <div className="act-row">
                <button className="btn primary" disabled={saving} onClick={saveCareer}>
                  {saving ? "保存中…" : "保存职业档案"}
                </button>
                <span className="muted">只存在本机，不会上传</span>
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
