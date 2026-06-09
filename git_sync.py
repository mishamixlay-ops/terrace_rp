"""
git_sync — автосинхронизация рабочей папки с GitHub-репо.
Вызывается в конце парсера/генератора.
"""
import subprocess
from datetime import datetime
from pathlib import Path


def git_sync(label: str = "auto-sync"):
    """git add/commit/push. Если репо не настроен или нет изменений — тихо."""
    repo_dir = Path(__file__).parent
    try:
        check = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=repo_dir, capture_output=True, text=True
        )
        if check.returncode != 0:
            print("git_sync: not a git repo, skip")
            return

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_dir, capture_output=True, text=True
        )
        if not status.stdout.strip():
            print("git_sync: nothing to commit")
            return

        msg = f"{label}: {datetime.now():%Y-%m-%d %H:%M}"
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
        subprocess.run(["git", "commit", "-m", msg], cwd=repo_dir, check=True)
        subprocess.run(["git", "push"], cwd=repo_dir, check=True)
        print(f"git_sync: pushed ({msg})")

    except Exception as e:
        print(f"git_sync: error ({e}), continuing anyway")
