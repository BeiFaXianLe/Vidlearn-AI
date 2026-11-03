# S6 交付报告：本地播放器与学习工作台

- 日期：2026-11-02
- 状态：**完成**（77 个单测通过；前端构建成功并由 FastAPI 托管；UI 截图验证通过）
- 依据：PRD V2.0 §3.7/§5.2、原型视觉

---

## 一、交付物

| 任务 | 文件 | 说明 |
|---|---|---|
| S6-01 受控媒体访问 | `apps/api_s6_media.py` | 仅允许读取 DB 登记的 media_assets，路径必须在 data_root 内（防穿越） |
| S6-02 HTTP Range | 同上 | 支持 `bytes=a-b` / `bytes=a-` / `bytes=-N`，返回 206 + Content-Range |
| S6-03 本地播放器 | `apps/web/src/App.tsx` | `<video>` 播放 `api.mediaUrl()`，支持拖动 |
| S6-04 编码兼容 | 播放提示显示 vcodec/分辨率；S2 已优先 avc1 | — |
| S6-05 字幕同步 | `App.tsx` activeIdx 按 currentTime 高亮 | 点击字幕定位 |
| S6-06 章节跳转 | `seek(start_ms)` | 点击章节/知识点定位播放器 |
| S6-07 工作台整合 | 原型视觉 1:1 还原 | 首页 Gallery + 详情左右分栏 |
| 前端工程 | `apps/web/` | Vite + React 18 + TS，构建产物 `dist/` |
| 静态托管 | `apps/main.py` | FastAPI 挂载 `/assets` + `/` 返回 index.html |

---

## 二、验收结果

### 2.1 单元测试
```
77 passed（S1 13 + S2 12 + S3 32 + S4 8 + S5 8 + S6 4）
```

### 2.2 Range 播放（HTTP 实测）
```
无 Range      → 200, Content-Length=49807, Accept-Ranges=bytes
bytes=0-1023  → 206, 1024 bytes, Content-Range: bytes 0-1023/49807
bytes=-500    → 206, 500 bytes（后缀范围）
```

### 2.3 前端托管（HTTP 实测）
```
GET /              → 200, 含 <div id="root">
GET /assets/*.js   → 200, 159721 bytes
GET /api/videos    → 3 videos
```

### 2.4 UI 截图（Playwright + 真实浏览器）
- 首页：侧边栏 / 统计卡 / 搜索筛选 / 视频卡片，**完全还原原型视觉**
- 详情页：真实 `<video>` 播放器（0:00/0:05，Range 提示）、Tabs、生成总结按钮、学习信息、笔记
- 字幕 Tab：显示 ASR 转写内容「大家好,今天我们来讲一下视频学习工作战则。」可点击定位

---

## 三、S6 期间的问题与处理

### 问题 1：pnpm 11 忽略 esbuild 构建脚本导致构建失败
- 现象：`ERR_PNPM_IGNORED_BUILDS: esbuild`，`pnpm build` 连带 `pnpm install` 失败
- 处理：直接用 `node node_modules/vite/bin/vite.js build` 构建；并补 `pnpm-workspace.yaml` 声明 `onlyBuiltDependencies: [esbuild]`
- 结果：构建成功（32 modules，JS 158KB gzip 51KB）

### 说明：前端为生产构建托管
- 开发态可用 `vite dev`（代理 /api 到 8000）；生产由 FastAPI 直接托管 `dist/`，单进程可运行。

---

## 四、S6 Gate 判定

| Gate 条件 | 结果 |
|---|---|
| 后端安全提供媒体访问 | ✅（DB 白名单 + 路径校验） |
| HTTP Range 拖动 | ✅（200/206/后缀全通） |
| 本地视频正常播放 | ✅（截图验证） |
| H.264 优先 | ✅（S2 已实现） |
| 字幕同步定位 | ✅ |
| 章节跳转 | ✅ |
| 工作台接入原型 | ✅（视觉还原） |
| 非 H.264 原生播放优先 | ✅（不默认转码） |

**S6 通过，可进入 S7（视频库与业务闭环）。**

---

## 五、移交 S7

1. 首页已展示列表/状态/搜索；S7 补：删除、批量、学习进度持久化、Markdown 导出。
2. 学习进度目前仅前端内存；S7 需 `learning_progress` 表 + 接口。
3. 播放器已能播放，S7 需把进度写回并在下次打开时恢复。
