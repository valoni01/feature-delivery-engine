import asyncio
import hashlib
import shutil
from pathlib import Path

from app.core.config import get_settings


def _workspace_path(repo_url: str, workflow_id: int) -> Path:
    """Deterministic local path for a cloned repo: <workspace_dir>/<url_hash>-<workflow_id>"""
    settings = get_settings()
    url_hash = hashlib.sha256(repo_url.encode()).hexdigest()[:12]
    return Path(settings.repo_workspace_dir) / f"{url_hash}-{workflow_id}"


_UNSET = object()


def _build_clone_url(repo_url: str, token: str | object = _UNSET) -> str:
    """Inject GitHub token into HTTPS clone URL when available."""
    if token is _UNSET:
        token = get_settings().github_token or ""

    url = repo_url.rstrip("/")
    if not url.endswith(".git"):
        url += ".git"

    if token and url.startswith("https://github.com/"):
        return url.replace("https://github.com/", f"https://x-access-token:{token}@github.com/")

    return url


async def clone_repo(
    repo_url: str,
    workflow_id: int,
    branch: str | None = None,
    github_token: str = "",
) -> str:
    """Clone a GitHub repo into the managed workspace. Returns the local path.

    If the directory already exists, it pulls latest instead of re-cloning.
    """
    local_path = _workspace_path(repo_url, workflow_id)
    clone_url = _build_clone_url(repo_url, token=github_token)

    if local_path.exists() and (local_path / ".git").is_dir():
        cmd = ["git", "-C", str(local_path), "pull", "--ff-only"]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git pull failed: {stderr.decode().strip()}")
        return str(local_path)

    local_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd.extend(["--branch", branch])
    cmd.extend([clone_url, str(local_path)])

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"git clone failed: {stderr.decode().strip()}")

    return str(local_path)


async def cleanup_repo(repo_url: str, workflow_id: int) -> None:
    """Remove the cloned repo from disk."""
    local_path = _workspace_path(repo_url, workflow_id)
    if local_path.exists():
        await asyncio.to_thread(shutil.rmtree, local_path)
