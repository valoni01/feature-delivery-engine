import httpx
from pydantic import BaseModel


class GitHubRepo(BaseModel):
    id: int
    full_name: str
    name: str
    private: bool
    html_url: str
    description: str | None
    default_branch: str
    language: str | None
    updated_at: str


GITHUB_API = "https://api.github.com"


async def list_user_repos(
    token: str,
    page: int = 1,
    per_page: int = 30,
    sort: str = "updated",
) -> list[GitHubRepo]:
    """Fetch repositories accessible to the authenticated user."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/user/repos",
            headers=headers,
            params={
                "page": page,
                "per_page": per_page,
                "sort": sort,
                "affiliation": "owner,collaborator,organization_member",
            },
            timeout=15.0,
        )
        resp.raise_for_status()

    return [
        GitHubRepo(
            id=r["id"],
            full_name=r["full_name"],
            name=r["name"],
            private=r["private"],
            html_url=r["html_url"],
            description=r.get("description"),
            default_branch=r["default_branch"],
            language=r.get("language"),
            updated_at=r["updated_at"],
        )
        for r in resp.json()
    ]
