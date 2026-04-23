from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.github_client import GitHubRepo, list_user_repos

SAMPLE_REPO_DATA = [
    {
        "id": 123,
        "full_name": "acme/widget",
        "name": "widget",
        "private": False,
        "html_url": "https://github.com/acme/widget",
        "description": "A widget library",
        "default_branch": "main",
        "language": "Python",
        "updated_at": "2026-04-20T10:00:00Z",
    },
    {
        "id": 456,
        "full_name": "acme/gadget",
        "name": "gadget",
        "private": True,
        "html_url": "https://github.com/acme/gadget",
        "description": None,
        "default_branch": "develop",
        "language": "TypeScript",
        "updated_at": "2026-04-21T10:00:00Z",
    },
]


class TestListUserRepos:
    async def test_returns_parsed_repos(self):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = SAMPLE_REPO_DATA

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.integrations.github_client.httpx.AsyncClient", return_value=mock_client):
            repos = await list_user_repos("ghp_test_token")

        assert len(repos) == 2
        assert isinstance(repos[0], GitHubRepo)
        assert repos[0].full_name == "acme/widget"
        assert repos[0].private is False
        assert repos[1].full_name == "acme/gadget"
        assert repos[1].private is True
        assert repos[1].description is None

    async def test_passes_correct_headers(self):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = []

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.integrations.github_client.httpx.AsyncClient", return_value=mock_client):
            await list_user_repos("ghp_my_token")

        call_kwargs = mock_client.get.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert "Bearer ghp_my_token" in headers.get("Authorization", "")

    async def test_raises_on_http_error(self):
        import httpx

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=MagicMock()
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.integrations.github_client.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await list_user_repos("bad_token")
