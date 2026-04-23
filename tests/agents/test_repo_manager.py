from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.agents.tools.repo_manager import (
    _build_clone_url,
    _workspace_path,
    clone_repo,
    cleanup_repo,
)

SAMPLE_URL = "https://github.com/acme/widget"


class TestBuildCloneUrl:
    def test_appends_git_suffix(self):
        url = _build_clone_url("https://github.com/acme/widget", token="")
        assert url.endswith(".git")

    def test_no_double_git_suffix(self):
        url = _build_clone_url("https://github.com/acme/widget.git", token="")
        assert url.endswith(".git")
        assert not url.endswith(".git.git")

    def test_strips_trailing_slash(self):
        url = _build_clone_url("https://github.com/acme/widget/", token="")
        assert url == "https://github.com/acme/widget.git"

    def test_injects_token_when_present(self):
        url = _build_clone_url("https://github.com/acme/widget", token="ghp_test123")
        assert "x-access-token:ghp_test123@" in url

    def test_no_token_injection_when_empty(self):
        url = _build_clone_url("https://github.com/acme/widget", token="")
        assert "x-access-token" not in url

    def test_no_token_injection_for_non_github(self):
        url = _build_clone_url("https://gitlab.com/acme/widget", token="ghp_test123")
        assert "x-access-token" not in url


class TestWorkspacePath:
    @patch("app.agents.tools.repo_manager.get_settings")
    def test_deterministic_path(self, mock_settings):
        mock_settings.return_value = MagicMock(repo_workspace_dir="/tmp/workspaces")
        path1 = _workspace_path(SAMPLE_URL, 42)
        path2 = _workspace_path(SAMPLE_URL, 42)
        assert path1 == path2
        assert str(path1).startswith("/tmp/workspaces/")
        assert "-42" in str(path1)

    @patch("app.agents.tools.repo_manager.get_settings")
    def test_different_workflows_get_different_paths(self, mock_settings):
        mock_settings.return_value = MagicMock(repo_workspace_dir="/tmp/workspaces")
        path1 = _workspace_path(SAMPLE_URL, 1)
        path2 = _workspace_path(SAMPLE_URL, 2)
        assert path1 != path2


class TestCloneRepo:
    @patch("app.agents.tools.repo_manager._build_clone_url", return_value="https://github.com/acme/widget.git")
    @patch("app.agents.tools.repo_manager._workspace_path")
    async def test_clone_fresh_repo(self, mock_ws_path, mock_build_url):
        fake_path = Path("/tmp/fake-workspace/abc-1")
        mock_ws_path.return_value = fake_path

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("app.agents.tools.repo_manager.asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec, \
             patch.object(Path, "exists", return_value=False), \
             patch.object(Path, "mkdir"):
            result = await clone_repo(SAMPLE_URL, 1)

        assert result == str(fake_path)
        call_args = mock_exec.call_args[0]
        assert "clone" in call_args

    @patch("app.agents.tools.repo_manager._build_clone_url", return_value="https://github.com/acme/widget.git")
    @patch("app.agents.tools.repo_manager._workspace_path")
    async def test_clone_with_branch(self, mock_ws_path, mock_build_url):
        fake_path = Path("/tmp/fake-workspace/abc-1")
        mock_ws_path.return_value = fake_path

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("app.agents.tools.repo_manager.asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec, \
             patch.object(Path, "exists", return_value=False), \
             patch.object(Path, "mkdir"):
            result = await clone_repo(SAMPLE_URL, 1, branch="develop")

        call_args = mock_exec.call_args[0]
        assert "--branch" in call_args
        assert "develop" in call_args

    @patch("app.agents.tools.repo_manager._build_clone_url", return_value="https://github.com/acme/widget.git")
    @patch("app.agents.tools.repo_manager._workspace_path")
    async def test_pulls_if_already_cloned(self, mock_ws_path, mock_build_url):
        fake_path = MagicMock(spec=Path)
        fake_path.exists.return_value = True
        fake_path.__truediv__ = MagicMock(return_value=MagicMock(is_dir=MagicMock(return_value=True)))
        fake_path.__str__ = MagicMock(return_value="/tmp/fake-workspace/abc-1")
        mock_ws_path.return_value = fake_path

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("app.agents.tools.repo_manager.asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            result = await clone_repo(SAMPLE_URL, 1)

        assert result == "/tmp/fake-workspace/abc-1"
        call_args = mock_exec.call_args[0]
        assert "pull" in call_args

    @patch("app.agents.tools.repo_manager._build_clone_url", return_value="https://github.com/acme/widget.git")
    @patch("app.agents.tools.repo_manager._workspace_path")
    async def test_clone_failure_raises(self, mock_ws_path, mock_build_url):
        fake_path = Path("/tmp/fake-workspace/abc-1")
        mock_ws_path.return_value = fake_path

        mock_proc = AsyncMock()
        mock_proc.returncode = 128
        mock_proc.communicate = AsyncMock(return_value=(b"", b"fatal: repo not found"))

        with patch("app.agents.tools.repo_manager.asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch.object(Path, "exists", return_value=False), \
             patch.object(Path, "mkdir"):
            with pytest.raises(RuntimeError, match="git clone failed"):
                await clone_repo(SAMPLE_URL, 1)


class TestCleanupRepo:
    @patch("app.agents.tools.repo_manager._workspace_path")
    async def test_cleanup_removes_directory(self, mock_ws_path):
        fake_path = MagicMock(spec=Path)
        fake_path.exists.return_value = True
        mock_ws_path.return_value = fake_path

        with patch("app.agents.tools.repo_manager.asyncio.to_thread") as mock_thread:
            await cleanup_repo(SAMPLE_URL, 1)
            mock_thread.assert_called_once()

    @patch("app.agents.tools.repo_manager._workspace_path")
    async def test_cleanup_noop_if_not_exists(self, mock_ws_path):
        fake_path = MagicMock(spec=Path)
        fake_path.exists.return_value = False
        mock_ws_path.return_value = fake_path

        with patch("app.agents.tools.repo_manager.asyncio.to_thread") as mock_thread:
            await cleanup_repo(SAMPLE_URL, 1)
            mock_thread.assert_not_called()
