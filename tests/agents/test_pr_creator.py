from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.pr_creator import PRDescription, _sanitize_branch, create_pr


class TestSanitizeBranch:
    def test_basic(self):
        assert _sanitize_branch("feat/user-notifications") == "feat/user-notifications"

    def test_spaces_and_special_chars(self):
        assert _sanitize_branch("feat/Add User Auth!") == "feat/add-user-auth"

    def test_double_hyphens(self):
        assert _sanitize_branch("feat/some--thing") == "feat/some-thing"

    def test_leading_trailing_hyphens(self):
        assert _sanitize_branch("-feat/test-") == "feat/test"


class TestCreatePR:
    async def test_creates_branch_and_commits(self):
        pr_desc = PRDescription(
            title="Add user notifications",
            body="## Summary\nAdded notification system.",
            branch_name="feat/user-notifications",
        )

        mock_llm = MagicMock()
        mock_llm.beta.chat.completions.parse = AsyncMock()

        message = MagicMock()
        message.parsed = pr_desc
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        response.usage = MagicMock(total_tokens=100)
        mock_llm.beta.chat.completions.parse.return_value = response

        state = {
            "workflow_id": 1,
            "model": "gpt-4o",
            "repo_path": "/fake/repo",
            "requirement_summary": {"title": "Notifications"},
            "technical_design": {"overview": "Add notifications"},
            "implementation_result": {"files_changed": ["app/models.py"]},
        }

        mock_run = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_run)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        track_fn = MagicMock(return_value=mock_ctx)

        mock_settings = MagicMock()
        mock_settings.github_token = ""

        git_calls = []

        async def mock_run_git(repo_path, *args):
            git_calls.append(args)
            return ""

        with patch("app.agents.pr_creator.get_llm_client", return_value=mock_llm), \
             patch("app.agents.pr_creator.track_agent_run", track_fn), \
             patch("app.agents.pr_creator.get_settings", return_value=mock_settings), \
             patch("app.agents.pr_creator._run_git", side_effect=mock_run_git):
            result = await create_pr(state)

        assert "pr_url" in result
        assert result["current_step"] == "pr_created"

        assert ("checkout", "-b", "feat/user-notifications") in git_calls
        assert ("add", "-A") in git_calls
        assert ("commit", "-m", "Add user notifications") in git_calls

    async def test_no_push_without_token(self):
        pr_desc = PRDescription(
            title="Add feature", body="Changes.", branch_name="feat/test",
        )

        mock_llm = MagicMock()
        message = MagicMock()
        message.parsed = pr_desc
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        response.usage = MagicMock(total_tokens=50)
        mock_llm.beta.chat.completions.parse = AsyncMock(return_value=response)

        state = {
            "workflow_id": 1, "model": "gpt-4o", "repo_path": "/fake",
            "requirement_summary": {}, "technical_design": {}, "implementation_result": {},
        }

        mock_run = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_run)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        track_fn = MagicMock(return_value=mock_ctx)

        mock_settings = MagicMock()
        mock_settings.github_token = ""

        async def mock_run_git(repo_path, *args):
            return ""

        with patch("app.agents.pr_creator.get_llm_client", return_value=mock_llm), \
             patch("app.agents.pr_creator.track_agent_run", track_fn), \
             patch("app.agents.pr_creator.get_settings", return_value=mock_settings), \
             patch("app.agents.pr_creator._run_git", side_effect=mock_run_git):
            result = await create_pr(state)

        assert "no GitHub token" in result["pr_url"]
