# core/config.py
import json
import sys
from dataclasses import dataclass, asdict, fields
from pathlib import Path


def app_root() -> Path:
    """项目根：打包后取 exe 所在目录；开发时取仓库根。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[1]


@dataclass
class AppConfig:
    root: Path
    models_dir: Path
    data_dir: Path
    kb_path: Path
    sessions_dir: Path
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    hotkey: str = "ctrl+alt+space"
    hide_hotkey: str = "ctrl+alt+h"
    audio_device: str = ""  # 空 = 系统默认输出设备

    def ensure_dirs(self) -> None:
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)


def default_config() -> AppConfig:
    root = app_root()
    data = root / "data"
    return AppConfig(
        root=root, models_dir=root / "models", data_dir=data,
        kb_path=data / "kb.db", sessions_dir=data / "sessions",
    )


def save_config(cfg: AppConfig) -> None:
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    plain = {k: str(v) if isinstance(v, Path) else v for k, v in asdict(cfg).items()}
    (cfg.data_dir / "config.json").write_text(
        json.dumps(plain, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config(data_dir: Path) -> AppConfig:
    cfg = default_config()
    f = data_dir / "config.json"
    if not f.exists():
        return cfg
    raw = json.loads(f.read_text(encoding="utf-8"))
    names = {fld.name for fld in fields(AppConfig)}
    for k, v in raw.items():
        if k in names:
            setattr(cfg, k, Path(v) if k in ("root", "models_dir", "data_dir", "kb_path", "sessions_dir") and isinstance(v, str) else v)
    return cfg
