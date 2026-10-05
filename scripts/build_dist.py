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
BACKUP = ROOT / "build" / "dist_data_backup"


def main() -> int:
    if DATA.exists():
        if BACKUP.exists():
            shutil.rmtree(BACKUP)
        shutil.copytree(DATA, BACKUP)
        print(f"[备份] {DATA} -> {BACKUP}")

    code = subprocess.call([sys.executable, "-m", "PyInstaller",
                            "interview-assistant.spec", "--noconfirm"], cwd=ROOT)
    if code != 0:
        print("[失败] PyInstaller 构建失败，尝试还原 data/")
        if BACKUP.exists() and not DATA.exists():
            shutil.copytree(BACKUP, DATA)
        return code

    if BACKUP.exists():
        DATA.mkdir(parents=True, exist_ok=True)
        for item in BACKUP.iterdir():
            dst = DATA / item.name
            if item.is_dir():
                shutil.copytree(item, dst, dirs_exist_ok=True)
            else:
                shutil.copyfile(item, dst)
        lock = DATA / "app.lock"
        if lock.exists():
            lock.unlink()          # 备份时可能带着退出残留的锁文件
        shutil.rmtree(BACKUP)
        print(f"[还原] 用户数据已回填 {DATA}")
    else:
        print("[跳过] 无既有用户数据")
    print("[完成] dist/notes-viewer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
