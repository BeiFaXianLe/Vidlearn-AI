# S8 交付报告：安全、稳定性与发布

- 日期：2026-11-02
- 状态：**完成**（91 个单测通过；发布包与启动脚本就绪）

## 一、交付物

| 任务 | 成果 |
|---|---|
| S8-01 凭证安全 | DPAPI 加密 + 日志脱敏（RedactingFilter）+ 密文不含明文（实测） |
| S8-02 子进程隔离 | 抖音暂缓（保留 Adapter + 错误码 blocked）；其余子进程参数数组、超时限制 |
| S8-03 路径安全 | 媒体访问双重校验（DB 白名单 + data_root 前缀），实测越权返回 403 |
| S8-04 任务恢复 | TaskManager 状态机（FAILED→CREATED 重试）；DB WAL + busy_timeout |
| S8-05 长视频压测 | 3 分钟音频：RTF 0.194，36 段，时间戳单调无重叠（修复了重叠 bug） |
| S8-06 许可证检查 | `docs/LICENSE_AUDIT.md` |
| S8-07 Windows 打包/启动 | `setup.ps1`、`run.ps1`、静态前端由 FastAPI 托管 |

## 二、安全测试结果（`tests/test_s8_security.py`）
```
- 媒体路径越界（data_root 外）→ 403 ✅
- 媒体文件缺失 → 404 ✅
- Range 越界/非法 → 416 ✅
- 凭证多键脱敏 → 全部 *** ✅
- 畸形 Cookie 解析不崩溃、拒绝空键 ✅
- 不存在视频 → 404 ✅
```

## 三、S8 期间修复的问题

### 问题 1：parse_cookie 接受空键
- `";;;==="` → `{'': '=='}`（空键注入风险）
- 修复：跳过空键；已加测试。

### 问题 2：长音频重叠切片导致时间戳重叠
- 3 分钟压测 `status=partial`，6 处「与上段重叠」
- 修复：新增 `_fix_overlaps`，把当前段起点裁到上段终点，无效则丢弃；修复后 `complete`、36 段、单调。
- 已加单测 `test_fix_overlaps_clips_and_drops`。

## 四、Gate 判定

| Gate | 结果 |
|---|---|
| 凭证不外泄（密文/日志） | ✅ |
| 路径穿越防护 | ✅ |
| Range 非法请求处理 | ✅ |
| 长视频稳定处理 | ✅（RTF 0.194） |
| 许可证清单 | ✅ |
| 一键启动/部署脚本 | ✅ |

**S8 通过 → V2.0 全部阶段（S0–S8）完成。**

## 五、已知限制（如实记录）

1. **抖音**：按决策暂缓，`resolve_adapter` 返回 unsupported；后续若接入需重做 PoC。
2. **真实 LLM**：未提供 API Key，S5 用 mock 验证链路；真实调用需配置 `VIDLEARN_LLM_API_KEY`。
3. **模型分发**：faster-whisper 模型需预置（首次下载约 460MB / 10 分钟，建议用 HF 镜像）。
4. **FFmpeg GPL**：对外分发前需换 LGPL build（见 LICENSE_AUDIT）。
5. **前端**：生产构建已托管；开发可用 vite dev。
