import asyncio
import json
import re
from urllib.parse import urlparse, urlunparse

import httpx
from pydantic import BaseModel, Field

from app.agents.base import track_agent_run
from app.agents.state import PipelineState
from app.core.config import get_settings
from app.core.llm import get_llm_client


class PRDescription(BaseModel):
    title: str = Field(description="Concise PR title, e.g. 'Add user notification system'")
    body: str = Field(description="Markdown PR body with summary, changes, and testing notes")
    branch_name: str = Field(description="Git branch name, e.g. 'feat/user-notifications'")


SYSTEM_PROMPT = """You are generating a pull request title, description, and branch name for a feature implementation.

Given the requirement summary, technical design, and implementation results, produce:
1. A concise PR title (imperative mood, e.g. "Add user notifications")
2. A well-structured PR body in markdown with:
   - Summary of what was implemented
   - List of key changes (files created/modified)
   - Testing notes
3. A git branch name (lowercase, hyphenated, prefixed with feat/, fix/, or chore/)

Keep the PR description clear and useful for reviewers."""


async def _run_git(repo_path: str, *args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=repo_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {stderr.decode().strip()}")
    return stdout.decode().strip()


def _sanitize_branch(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9/\-]", "-", name)
    name = re.sub(r"-+", "-", name)
    return name.strip("-")


def _extract_owner_repo(url: str) -> str:
    """Extract 'owner/repo' from a GitHub URL."""
    match = re.search(r"github\.com[/:]([^/]+)/([^/.]+)", url)
    if not match:
        return ""
    return f"{match.group(1)}/{match.group(2)}"


async def push_and_create_pr(
    repo_path: str,
    branch: str,
    title: str,
    body: str,
    token: str,
) -> str:
    """Push branch and open a GitHub PR. Returns the PR URL or a status message."""
    if not token:
        return f"branch:{branch} (no GitHub token — PR must be created manually)"

    try:
        origin_url = await _run_git(repo_path, "remote", "get-url", "origin")
        if "github.com" in origin_url:
            parsed = urlparse(origin_url)
            auth_url = urlunparse(parsed._replace(
                netloc=f"x-access-token:{token}@{parsed.hostname}",
            ))
            await _run_git(repo_path, "remote", "set-url", "origin", auth_url)

        await _run_git(repo_path, "push", "-u", "origin", branch)

        owner_repo = _extract_owner_repo(origin_url)
        if not owner_repo:
            return f"branch:{branch} (pushed but could not determine owner/repo for PR)"

        try:
            default_branch = await _run_git(repo_path, "rev-parse", "--abbrev-ref", "origin/HEAD")
            base = default_branch.removeprefix("origin/")
        except RuntimeError:
            base = "main"

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.github.com/repos/{owner_repo}/pulls",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                json={"title": title, "body": body, "head": branch, "base": base},
            )
            if resp.status_code in (200, 201):
                return resp.json().get("html_url", f"branch:{branch}")
            return f"branch:{branch} (pushed but PR creation failed: {resp.status_code} {resp.text})"
    except RuntimeError as e:
        return f"branch:{branch} (push failed: {e})"


async def create_pr(state: PipelineState) -> dict:
    """LangGraph node: creates a git branch, commits changes, pushes, and opens a PR."""
    llm = get_llm_client()
    model = state["model"]
    workflow_id = state["workflow_id"]
    repo_path = state.get("repo_path", ".")
    token = state.get("github_token") or get_settings().github_token

    req_summary = json.dumps(state.get("requirement_summary", {}), indent=2)
    tech_design = json.dumps(state.get("technical_design", {}), indent=2)
    impl_result = json.dumps(state.get("implementation_result", {}), indent=2)

    async with track_agent_run(
        workflow_id, "pr_creator", model,
        input_data={"source_field": "implementation_result"},
    ) as run:
        response = await llm.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"## Requirement Summary\n```json\n{req_summary}\n```\n\n"
                    f"## Technical Design\n```json\n{tech_design}\n```\n\n"
                    f"## Implementation Result\n```json\n{impl_result}\n```"
                )},
            ],
            response_format=PRDescription,
            temperature=0.3,
        )

        pr_desc = response.choices[0].message.parsed
        tokens = response.usage.total_tokens if response.usage else 0

        branch = _sanitize_branch(pr_desc.branch_name)

        await _run_git(repo_path, "checkout", "-b", branch)
        await _run_git(repo_path, "add", "-A")
        await _run_git(repo_path, "commit", "-m", pr_desc.title)

        pr_url = await push_and_create_pr(
            repo_path=repo_path,
            branch=branch,
            title=pr_desc.title,
            body=pr_desc.body,
            token=token,
        )

        result = {
            "title": pr_desc.title,
            "body": pr_desc.body,
            "branch": branch,
            "pr_url": pr_url,
        }
        run.output_data = result
        run.tokens_used = tokens

    return {"pr_url": pr_url, "current_step": "pr_created"}
