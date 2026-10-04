# tests/test_main_app.py —— 审查修复轮 C2
import json


def test_build_app_reads_config_from_app_root(tmp_path, monkeypatch):
    # 审查 C2：打包后 __file__ 指向 _internal，配置必须从 app_root() 读
    import core.config as cc
    monkeypatch.setattr(cc, "app_root", lambda: tmp_path)
    d = tmp_path / "data"
    d.mkdir(parents=True)
    (d / "config.json").write_text(
        json.dumps({"llm_model": "m1", "llm_base_url": "https://x/v1"}), encoding="utf-8")
    import main
    res = main.build_app()
    assert len(res) == 4  # cfg, kb, rag, recorder（彩排工厂已删）
    cfg = res[0]
    assert cfg.llm_model == "m1"
    assert cfg.kb_path == tmp_path / "data" / "kb.db"
