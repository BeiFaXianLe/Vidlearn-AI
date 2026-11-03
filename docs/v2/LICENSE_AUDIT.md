# 许可证审查（S8-06）

> VidLearn AI V2.0 · 2026-11-02
> 原则：**仅自用可分發无碍；对外分发需按本表复核**。

## 一、直接依赖

| 组件 | 许可证 | 分发影响 | 规避方式 |
|---|---|---|---|
| Python 3.12 | PSF-2.0 | 宽松 | — |
| FastAPI | MIT | 宽松 | — |
| Uvicorn | BSD-3-Clause | 宽松 | — |
| Pydantic / pydantic-settings | MIT | 宽松 | — |
| httpx | BSD-3-Clause | 宽松 | — |
| PyYAML | MIT | 宽松 | — |
| **faster-whisper** | MIT | 宽松 | — |
| **ctranslate2** | MIT | 宽松 | — |
| React / React-DOM | MIT | 宽松 | — |
| Vite | MIT | 宽松 | — |

## 二、外部工具（非嵌入依赖）

| 工具 | 许可证 | 分发影响 | 重要说明 |
|---|---|---|---|
| **yt-dlp** | Unlicense（公共领域） | 宽松 | 以**外部可执行文件**调用，不内嵌源码 |
| **FFmpeg 8.1.1 full_build (gyan.dev)** | **GPLv3**（含 x264/x265 等） | **若随包分发，整个产品可能受 GPLv3 约束** | ①自用无影响；②对外分发请改用 **LGPL build**（去掉 x264/x265 等 GPL 组件）；③或以「用户自行安装」方式规避 |

## 三、参考但未引入代码的项目

| 项目 | 许可证 | 使用方式 |
|---|---|---|
| BiliSum | MIT | 仅借鉴思路，未拷贝代码 |
| BiliNote | MIT | 仅参考 |
| jiji262/douyin-downloader | MIT | 暂缓接入（后续若接入为外部子进程） |
| Evil0ctal/Douyin_TikTok_Download_API | Apache-2.0 | 备用，未接入 |
| VideoCaptioner | GPL-3.0 | **仅阅读思路，禁止拷贝代码** |

## 四、结论

1. **本项目自有代码**（apps/、apps/web/src）为原创，可自由授权。
2. **风险点只有一个**：FFmpeg 的 GPL full build。
   - 自用：无问题。
   - 对外分发：必须换 LGPL build 或要求用户自装。
3. 其余依赖均为 MIT/BSD/Apache 类宽松许可，无传染风险。

## 五、发布前检查清单

- [ ] 确认是否对外分发（决定 FFmpeg 策略）
- [ ] 附 `THIRD_PARTY_LICENSES.txt`（分发时）
- [ ] 不得把 GPL 项目（VideoCaptioner）源码拷入
- [ ] yt-dlp/FFmpeg 以外部进程调用，不静态链接进自有二进制
