# tests/conftest.py —— 兜底隔离：任何测试默认把 app_root 重定向到独立 tmp，
# 杜绝「测试写真实 models//data 目录」这一类事故（1 字节假模型/覆写真实
# config.json 均由此起）。显式自管 app_root 的测试可再覆盖，不受影响。
import pytest


@pytest.fixture(autouse=True)
def _isolate_app_root(tmp_path, monkeypatch):
    import core.config as cc
    monkeypatch.setattr(cc, "_real_app_root", cc.app_root, raising=False)
    monkeypatch.setattr(cc, "app_root", lambda: tmp_path)
    yield


@pytest.fixture
def real_app_root(monkeypatch):
    """需要真实 models//data 的测试（model 标记）用：恢复未隔离的 app_root。"""
    import core.config as cc
    monkeypatch.setattr(cc, "app_root", cc._real_app_root)
    return cc.app_root()
