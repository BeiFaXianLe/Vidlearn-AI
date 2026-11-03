"""导入上传接口测试。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    import importlib
    import apps.main as main_mod
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        yield c


def test_upload_local_file(client):
    r = client.post("/api/upload", files={"files": ("测试样本.mp4", b"FAKEDATA" * 100, "video/mp4")})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] and d["files"][0]["path"]
    assert d["files"][0]["size"] > 0
    assert Path(d["files"][0]["path"]).exists()
