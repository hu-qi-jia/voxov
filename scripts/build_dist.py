# scripts/build_dist.py —— 安全重建 dist：构建前后保护 data/ 与 models/（用户数据）。
# PyInstaller COLLECT 会清空 dist/notes-viewer，直接 pyinstaller 会丢用户数据
#（2026-10-05 事故：kb.db/会话被清）。备份/回填均带数量验证，异常即中止并保留备份。
# 用法：python scripts/build_dist.py
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST_APP = ROOT / "dist" / "notes-viewer"
PROTECTED = {"data": DIST_APP / "data", "models": DIST_APP / "models"}
BACKUP = ROOT / "build" / "dist_data_backup"


def _count(p: Path) -> int:
    return 0 if not p.exists() else sum(1 for _ in p.rglob("*") if _.is_file())


def _copy_tree(src: Path, dst: Path) -> int:
    n = 0
    for item in src.rglob("*"):
        target = dst / item.relative_to(src)
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, target)
            n += 1
    return n


def main() -> int:
    backup_counts: dict[str, int] = {}
    if BACKUP.exists():
        shutil.rmtree(BACKUP)                    # 上一次残留：以本次状态为准
    for name, src in PROTECTED.items():
        if src.exists():
            n = _copy_tree(src, BACKUP / name)
            backup_counts[name] = n
            print(f"[备份] {name}: {n} 个文件 -> {BACKUP / name}")
            if n == 0:
                print("[中止] 备份为 0 个文件（源目录异常为空），不执行构建。"
                      "请人工检查 dist/notes-viewer 后重跑。")
                return 2

    code = subprocess.call([sys.executable, "-m", "PyInstaller",
                            "interview-assistant.spec", "--noconfirm"], cwd=ROOT)
    if code != 0:
        print("[失败] PyInstaller 构建失败，还原备份（保留不动）")
        for name, n in backup_counts.items():
            dst = PROTECTED[name]
            if not dst.exists():
                _copy_tree(BACKUP / name, dst)
            print(f"[还原] {name}（{n} 文件）")
        return code

    for name, n in backup_counts.items():
        dst = PROTECTED[name]
        got = _copy_tree(BACKUP / name, dst)
        if got < n:                              # 回填数量不足：保留备份供人工处理
            print(f"[严重] {name} 回填 {got}/{n} 个文件——备份保留在 {BACKUP}")
            return 3
        lock = dst / "app.lock"
        if lock.exists():
            lock.unlink()                        # 退出残留的锁文件
        print(f"[还原] {name}: {got} 个文件 -> {dst}")
    shutil.rmtree(BACKUP)
    print("[完成] dist/notes-viewer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
