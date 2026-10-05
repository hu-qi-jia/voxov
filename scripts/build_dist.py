# scripts/build_dist.py —— 安全重建 dist：构建前后保护 data/（用户配置+知识库）。
# PyInstaller COLLECT 会清空 dist/notes-viewer，直接 pyinstaller 会丢用户数据
#（2026-10-05 事故：kb.db/会话被清）。用法：python scripts/build_dist.py
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST_APP = ROOT / "dist" / "notes-viewer"
DATA = DIST_APP / "data"
MODELS = DIST_APP / "models"
BACKUP = ROOT / "build" / "dist_data_backup"


def main() -> int:
    if DATA.exists():
        if BACKUP.exists():
            shutil.rmtree(BACKUP)
        BACKUP.mkdir(parents=True, exist_ok=True)
        shutil.copytree(DATA, BACKUP / "data")
        if MODELS.exists():
            shutil.copytree(MODELS, BACKUP / "models")
        print(f"[备份] {DATA} 与 {MODELS} -> {BACKUP}")

    code = subprocess.call([sys.executable, "-m", "PyInstaller",
                            "interview-assistant.spec", "--noconfirm"], cwd=ROOT)
    if code != 0:
        print("[失败] PyInstaller 构建失败，尝试还原备份")
        if BACKUP.exists() and not DATA.exists():
            shutil.copytree(BACKUP / "data", DATA)
        if BACKUP.exists() and not MODELS.exists():
            shutil.copytree(BACKUP / "models", MODELS)
        return code

    for name in ("data", "models"):
        src, dst = BACKUP / name, ROOT / "dist" / "notes-viewer" / name
        if not src.exists():
            continue
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.rglob("*"):
            rel = item.relative_to(src)
            target = dst / rel
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                shutil.copyfile(item, target)
        lock = dst / "app.lock"
        if lock.exists():
            lock.unlink()          # 备份时可能带着退出残留的锁文件
        print(f"[还原] {name} 已回填 {dst}")
    shutil.rmtree(BACKUP)
    print("[完成] dist/notes-viewer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
