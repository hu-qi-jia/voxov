# tests/test_downloader.py —— 模型获取 v2：纯 HTTP 下载 + 完整性门禁
import tarfile

import core.downloader as dl


def _mk_tar(src_dir, members):
    p = src_dir / "arch.tar.bz2"
    with tarfile.open(p, "w:bz2") as t:
        for name, content in members.items():
            import io
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name="bundle/" + name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return p


def test_models_ready_requires_all_files(tmp_path):
    assert dl.models_ready(tmp_path) is False
    (tmp_path / "asr").mkdir()
    (tmp_path / "asr" / "model.int8.onnx").write_bytes(b"x")
    (tmp_path / "asr" / "tokens.txt").write_bytes(b"x")
    (tmp_path / "asr" / "silero_vad.onnx").write_bytes(b"x")
    (tmp_path / "embed").mkdir()
    (tmp_path / "embed" / "model.onnx").write_bytes(b"x")
    assert dl.models_ready(tmp_path) is False
    (tmp_path / "embed" / "tokenizer.json").write_bytes(b"x")
    assert dl.models_ready(tmp_path) is True


def test_ensure_models_downloads_and_extracts(tmp_path):
    calls = []

    def fake_fetch(urls, dest, progress=None, **kw):
        calls.append((tuple(urls), dest.name))
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.suffix == ".bz2":
            p = _mk_tar(dest.parent, {"model.int8.onnx": "M", "tokens.txt": "T"})
            shutil.copyfile(p, dest)
        else:
            dest.write_bytes(b"E")

    import shutil
    logs = []
    percents = []
    dl.ensure_models(tmp_path, logs.append, progress=percents.append, fetch=fake_fetch)
    assert (tmp_path / "asr" / "model.int8.onnx").exists()
    assert (tmp_path / "asr" / "tokens.txt").exists()
    assert (tmp_path / "embed" / "model.onnx").exists()
    assert (tmp_path / "embed" / "tokenizer.json").exists()
    assert any("[完成]" in m for m in logs)
    assert not (tmp_path / "asr_archive.tar.bz2").exists()   # 归档用后即删


def test_ensure_models_skips_when_ready(tmp_path):
    for rel in dl.REQUIRED:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")

    def boom(*a, **k):
        raise AssertionError("已就绪不应下载")

    logs = []
    dl.ensure_models(tmp_path, logs.append, fetch=boom)
    assert any("就绪" in m for m in logs)


def test_fetch_to_tries_all_mirrors_then_raises(tmp_path, monkeypatch):
    errs = []

    class FakeResp:
        def __init__(self, body): self.body = body
        def read(self, n): return b""
        def __enter__(self): return self
        def __exit__(self, *a): return False
        headers = {}

    def fake_urlopen(req, timeout):
        errs.append(req.full_url)
        raise IOError("connection refused")

    monkeypatch.setattr(dl.urllib.request, "urlopen", fake_urlopen)
    import pytest
    with pytest.raises(RuntimeError, match="下载失败"):
        dl._fetch_to(["https://m1.example/a", "https://m2.example/a"],
                     tmp_path / "x.bin")
    assert len(errs) == 2                      # 两个镜像都试过
    assert not (tmp_path / "x.bin.part").exists()


def test_fetch_to_rejects_bad_magic_and_falls_to_next_mirror(tmp_path, monkeypatch):
    """镜像回 HTML 错误页时必须换源，而不是把垃圾内容当文件落盘（not a bzip2 根因）。"""
    bodies = {0: b"<!-- error page -->", 1: b"BZh9valid-bz2"}
    calls = []

    class FakeResp:
        def __init__(self, body):
            self.body = body
            self._read = False
        def read(self, n):
            if self._read:                  # 模拟流式：第二次读到 EOF
                return b""
            self._read = True
            return self.body
        def __enter__(self): return self
        def __exit__(self, *a): return False
        headers = {}

    def fake_urlopen(req, timeout):
        calls.append(req.full_url)
        return FakeResp(bodies[len(calls) - 1])

    monkeypatch.setattr(dl.urllib.request, "urlopen", fake_urlopen)
    dest = tmp_path / "a.tar.bz2"
    dl._fetch_to(["https://bad.example/a", "https://good.example/a"],
                 dest, expected_magic=b"BZh")
    assert dest.read_bytes() == b"BZh9valid-bz2"     # 坏镜像被跳过，好源落盘
    assert len(calls) == 2
