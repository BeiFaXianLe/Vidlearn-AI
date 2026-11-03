# ASR 模型下载与配置（MODEL_SETUP）

> VidLearn AI 使用 `faster-whisper` 的 CTranslate2 模型。默认 `small`，约 464MB。
> **首次运行会自动下载**；网络慢时按本文手动下载即可（推荐）。

## 一、需要哪些文件

放到同一目录，共 6 个：

| 文件 | 大小 |
|---|---|
| `model.bin` | ~461 MB |
| `tokenizer.json` | ~2.1 MB |
| `vocabulary.txt` | ~0.44 MB |
| `config.json` | 小 |
| `README.md` | 小（可选） |
| `.gitattributes` | 小（可选） |

## 二、下载方式（三选一）

### A. ModelScope 国内镜像（最快）
```powershell
pip install modelscope
modelscope download --model pz499/faster-whisper-small --local_dir "D:\models\faster-whisper-small"
# 若仓库名失效：--model AI-ModelScope/faster-whisper-small
```

### B. HuggingFace 镜像
```powershell
$env:HF_ENDPOINT="https://hf-mirror.com"
pip install huggingface_hub
huggingface-cli download Systran/faster-whisper-small --local-dir "D:\models\faster-whisper-small"
```

### C. 浏览器手动下载（断点续传最稳）
把以下文件存到同一目录：
```
https://hf-mirror.com/Systran/faster-whisper-small/resolve/main/model.bin
https://hf-mirror.com/Systran/faster-whisper-small/resolve/main/tokenizer.json
https://hf-mirror.com/Systran/faster-whisper-small/resolve/main/vocabulary.txt
https://hf-mirror.com/Systran/faster-whisper-small/resolve/main/config.json
https://hf-mirror.com/Systran/faster-whisper-small/resolve/main/README.md
https://hf-mirror.com/Systran/faster-whisper-small/resolve/main/.gitattributes
```

## 三、让程序用你下载的模型

### 方式 1：放到默认位置（最省心）
把整个文件夹放到项目下 `./models/faster-whisper-small/`，`run.ps1` 会自动识别。

### 方式 2：环境变量指定任意目录
```powershell
$env:VIDLEARN_ASR_MODEL_DIR="D:\models\faster-whisper-small"
.\run.ps1
```

### 方式 3：用 faster-whisper 内置缓存
把 `HF_HOME` 指向你的缓存根目录（需符合 HF 缓存结构），或不设任何变量让程序自动下载。

## 四、可选：更大模型

| 模型 | 大小 | 精度 | 说明 |
|---|---|---|---|
| small | ~464MB | 够用 | 默认，CPU 可跑 |
| medium | ~1.5GB | 更好 | CPU 较慢 |
| large-v3 | ~3GB | 最好 | 建议 GPU |

换模型：
```powershell
$env:VIDLEARN_ASR_MODEL="medium"
$env:VIDLEARN_ASR_MODEL_DIR="D:\models\faster-whisper-medium"
```

## 五、验证是否可用

```powershell
.\.venv\Scripts\python.exe -c "import sys;sys.path.insert(0,'.');from faster_whisper import WhisperModel;m=WhisperModel(r'D:\models\faster-whisper-small',device='cpu',compute_type='int8');print('模型加载成功')"
```

## 六、当前本机状态

- 模型已完整下载（463.7MB，6 文件齐全）于 `.tmp/hf/...`，`run.ps1` 已能自动识别。
- 如需迁移到 `./models/`，把 `snapshots\536b0662.../` 下 6 个文件拷到 `./models/faster-whisper-small/` 即可。
