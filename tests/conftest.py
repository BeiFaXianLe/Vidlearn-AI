"""全局测试夹具：确保测试绝不污染真实数据目录。

问题：多数测试直接 import apps.main（会创建 lifespan 与真实 DB），
若不隔离，会在 data/database/vidlearn.db 里写入测试视频。

方案：在会话开始时强制把 VIDLEARN_DATA_ROOT 指向临时目录。
      pydantic-settings 优先级：环境变量 > .env 文件，
      因此该设置会覆盖 .env 里的 VIDLEARN_DATA_ROOT=./data。
"""
import os
import shutil
from pathlib import Path

# 必须在导入 apps.* 之前设置
# 注意：沙箱环境里 tempfile.gettempdir() 可能回落到项目根目录，
# 因此测试数据统一放到项目内被忽略的 .tmp/test_data，避免污染项目根。
_ROOT = Path(__file__).resolve().parents[1]
_TMP_DATA = str(_ROOT / ".tmp" / "test_data")
os.environ["VIDLEARN_DATA_ROOT"] = _TMP_DATA
os.environ["VIDLEARN_LLM_API_KEY"] = ""

# 清掉上次测试残留，保证每次干净
shutil.rmtree(_TMP_DATA, ignore_errors=True)
os.makedirs(_TMP_DATA, exist_ok=True)
