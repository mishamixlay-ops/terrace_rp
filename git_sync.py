"""
git_sync — автосинхронизация рабочей папки с GitHub-репо.
Перед пушем копирует новейшие версии скриптов в стабильные имена
(parser_actual.py, generator_actual.py), чтобы Claude мог подтягивать
их по неизменным raw-ссылкам.
"""
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


def _latest(pattern: str, version_re: str, folder: Path):
    """Находит файл с максимальным номером версии, игнорируя бэкапы."""
    best, best_v = None, -1
    for f in folder.glob(pattern):
        name = f.name
        if any(s in name.upper() for s in ("_BACKUP", "_OLD", "_COPY")):
            continue
        m = re.search(version_re, name)
        if m and int(m.group(1)) > best_v:
            best_v, best = int(m.group(1)), f
    return best


def _update_actual_copies(folder: Path):
    """Копирует новейший парсер и генератор в стабильные имена."""
    parser = _latest("trendagent_parser_*.py", r"trendagent_parser_(\d+)\.py", folder)
    gen = _latest("Generate_filter_*.py", r"Generate_filter_(\d+)", folder)
    if parser:
        shutil.copyfile(parser, folder / "parser_actual.py")
        print(f"git_sync: parser_actual.py <- {parser.name}")
    if gen:
        shutil.copyfile(gen, folder / "generator_actual.py")
        print(f"git_sync: generator_actual.py <- {gen.name}")


def git_sync(label: str = "auto-sync"):
    """git add/commit/push. Пушит даже если новых изменений нет,
    но есть незапушенные коммиты."""
    repo_dir = Path(__file__).parent
    try:
        check = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=repo_dir, capture_output=True, text=True
        )
        if check.returncode != 0:
            print("git_sync: not a git repo, skip")
            return

        _update_actual_copies(repo_dir)

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_dir, capture_output=True, text=True
        )
        if status.stdout.strip():
            msg = f"{label}: {datetime.now():%Y-%m-%d %H:%M}"
            subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
            subprocess.run(["git", "commit", "-m", msg], cwd=repo_dir, check=True)
            print(f"git_sync: committed ({msg})")
        else:
            print("git_sync: no new changes")

        # Пушим всегда — подхватит и незапушенные коммиты прошлых запусков
        push = subprocess.run(
            ["git", "push"], cwd=repo_dir, capture_output=True, text=True
        )
        if push.returncode == 0:
            print("git_sync: push ok")
        else:
            print(f"git_sync: push failed: {push.stderr.strip()}")

    except Exception as e:
        print(f"git_sync: error ({e}), continuing anyway")


if __name__ == "__main__":
    git_sync("manual sync")
