from fastapi import APIRouter, Header, HTTPException, Query, status

from app.integrations.github_client import GitHubRepo, list_user_repos

router = APIRouter(prefix="/github", tags=["github"])


@router.get("/repos", response_model=list[GitHubRepo])
async def get_repos(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=30, ge=1, le=100),
    authorization: str = Header(..., description="GitHub personal access token"),
) -> list[GitHubRepo]:
    """List GitHub repositories accessible to the authenticated user.

    Pass the GitHub token in the Authorization header:
        Authorization: Bearer ghp_xxxx
    """
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="GitHub token is required in the Authorization header.",
        )

    try:
        return await list_user_repos(token, page=page, per_page=per_page)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch repos from GitHub: {exc}",
        )
