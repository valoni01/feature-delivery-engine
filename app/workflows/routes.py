from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import AgentRun
from app.agents.pr_creator import push_and_create_pr
from app.agents.tools.repo_manager import clone_repo
from app.core.config import get_settings
from app.core.db import get_db
from app.orchestration.pipeline import pipeline
from app.services.models import Service
from app.workflows.models import Workflow
from app.workflows.schemas import (
    AgentRunResponse,
    ClarificationAnswers,
    WorkflowCreate,
    WorkflowResponse,
    WorkflowStatus,
    WorkflowUpdate,
)


def _extract_token(authorization: str | None) -> str:
    """Pull the bearer token from the Authorization header, if present."""
    if not authorization:
        return ""
    return authorization.removeprefix("Bearer ").strip()

router = APIRouter(prefix="/workflows", tags=["workflows"])


async def _sync_workflow_from_result(
    workflow: Workflow,
    result: dict[str, Any],
    db: AsyncSession,
) -> Workflow:
    """Sync the workflow DB record with the pipeline result.

    If the pipeline paused for clarification, returns a ClarificationResponse dict.
    Otherwise, updates all workflow fields and returns the workflow.
    """
    questions = result.get("clarifying_questions", [])
    has_summary = result.get("requirement_summary") is not None

    if questions and not has_summary:
        workflow.status = WorkflowStatus.AWAITING_CLARIFICATION
        workflow.pending_questions = questions
        await db.commit()
        await db.refresh(workflow)
        return workflow

    workflow.pending_questions = None

    if result.get("requirement_summary"):
        workflow.requirement_summary = result["requirement_summary"]
    if result.get("technical_design"):
        workflow.technical_design = result["technical_design"]
    if result.get("tasks"):
        workflow.tasks = result["tasks"]
    if result.get("pr_url"):
        workflow.pr_url = result["pr_url"]

    step = result.get("current_step", "")
    if result.get("pr_url"):
        workflow.status = WorkflowStatus.COMPLETED
    elif step == "pr_created":
        workflow.status = WorkflowStatus.PR_CREATED
    elif step in ("code_reviewing", "code_auto_approved"):
        workflow.status = WorkflowStatus.CODE_REVIEWING
    elif step == "implementing":
        workflow.status = WorkflowStatus.IMPLEMENTING
    elif step == "ticketing":
        workflow.status = WorkflowStatus.TICKETING
    elif result.get("review_decision"):
        workflow.status = WorkflowStatus.REVIEWING
    elif result.get("technical_design"):
        workflow.status = WorkflowStatus.DESIGNING
    elif result.get("requirement_summary"):
        workflow.status = WorkflowStatus.DESIGNING

    await db.commit()
    await db.refresh(workflow)
    return workflow

VALID_TRANSITIONS: dict[WorkflowStatus, list[WorkflowStatus]] = {
    WorkflowStatus.DRAFT: [WorkflowStatus.PARSING, WorkflowStatus.FAILED],
    WorkflowStatus.PARSING: [WorkflowStatus.AWAITING_CLARIFICATION, WorkflowStatus.DESIGNING, WorkflowStatus.FAILED],
    WorkflowStatus.AWAITING_CLARIFICATION: [WorkflowStatus.PARSING, WorkflowStatus.FAILED],
    WorkflowStatus.DESIGNING: [WorkflowStatus.REVIEWING, WorkflowStatus.FAILED],
    WorkflowStatus.REVIEWING: [WorkflowStatus.DESIGNING, WorkflowStatus.TICKETING, WorkflowStatus.FAILED],
    WorkflowStatus.TICKETING: [WorkflowStatus.IMPLEMENTING, WorkflowStatus.FAILED],
    WorkflowStatus.IMPLEMENTING: [WorkflowStatus.CODE_REVIEWING, WorkflowStatus.FAILED],
    WorkflowStatus.CODE_REVIEWING: [WorkflowStatus.IMPLEMENTING, WorkflowStatus.PR_CREATED, WorkflowStatus.FAILED],
    WorkflowStatus.PR_CREATED: [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED],
    WorkflowStatus.COMPLETED: [],
    WorkflowStatus.FAILED: [WorkflowStatus.DRAFT],
}


@router.post(
    "",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workflow(
    payload: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
) -> Workflow:
    if payload.service_id is not None:
        service = await db.get(Service, payload.service_id)
        if not service:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Service not found.",
            )

    workflow = Workflow(
        service_id=payload.service_id,
        title=payload.title,
        feature_doc_text=payload.feature_doc_text,
        repo_url=payload.repo_url,
        branch=payload.branch,
        status=WorkflowStatus.DRAFT,
    )

    db.add(workflow)
    await db.commit()
    await db.refresh(workflow)

    return workflow


@router.post("/{workflow_id}/run", response_model=WorkflowResponse)
async def run_pipeline(
    workflow_id: int,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Kick off the FRD analysis pipeline. Returns clarifying questions if the agent has any."""
    workflow = await db.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found.",
        )

    restartable = {WorkflowStatus.DRAFT, WorkflowStatus.FAILED, WorkflowStatus.AWAITING_CLARIFICATION}
    if workflow.status not in restartable:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Workflow must be in draft, failed, or awaiting_clarification status to run. Current: '{workflow.status}'.",
        )

    settings = get_settings()
    user_token = _extract_token(authorization) or settings.github_token

    try:
        local_path = await clone_repo(
            workflow.repo_url, workflow.id, workflow.branch, github_token=user_token,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to clone repository: {exc}",
        )

    workflow.repo_local_path = local_path
    workflow.status = WorkflowStatus.PARSING
    await db.commit()

    initial_state = {
        "workflow_id": workflow.id,
        "feature_doc_text": workflow.feature_doc_text,
        "model": settings.default_model,
        "repo_url": workflow.repo_url,
        "repo_path": local_path,
        "github_token": user_token,
    }

    thread_id = f"workflow-{workflow.id}"
    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = await pipeline.ainvoke(initial_state, config=config)
    except Exception as exc:
        workflow.status = WorkflowStatus.FAILED
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline failed: {exc}",
        )

    return await _sync_workflow_from_result(workflow, result, db)


@router.post("/{workflow_id}/clarify", response_model=WorkflowResponse)
async def submit_clarifications(
    workflow_id: int,
    payload: ClarificationAnswers,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any] | Workflow:
    """Submit answers to clarifying questions and resume the pipeline.

    Returns either more clarifying questions (another round) or the final workflow
    with requirement_summary populated.
    """
    workflow = await db.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found.",
        )

    if workflow.status != WorkflowStatus.AWAITING_CLARIFICATION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Workflow must be 'awaiting_clarification' to submit answers. Current: '{workflow.status}'.",
        )

    thread_id = f"workflow-{workflow.id}"
    config = {"configurable": {"thread_id": thread_id}}

    workflow.status = WorkflowStatus.PARSING
    await db.commit()

    try:
        result = await pipeline.ainvoke(
            Command(resume=payload.answers),
            config=config,
        )
    except Exception as exc:
        workflow.status = WorkflowStatus.AWAITING_CLARIFICATION
        await db.commit()
        detail = str(exc)
        if "checkpoint" in detail.lower() or "thread" in detail.lower():
            detail = "Pipeline session expired (server was restarted). Please re-run the workflow."
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline failed: {detail}",
        )

    return await _sync_workflow_from_result(workflow, result, db)


@router.post("/{workflow_id}/skip-clarification", response_model=WorkflowResponse)
async def skip_clarification(
    workflow_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any] | Workflow:
    """Skip remaining questions and tell the agent to finalize with what it has."""
    workflow = await db.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found.",
        )

    if workflow.status != WorkflowStatus.AWAITING_CLARIFICATION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Workflow must be 'awaiting_clarification' to skip. Current: '{workflow.status}'.",
        )

    thread_id = f"workflow-{workflow.id}"
    config = {"configurable": {"thread_id": thread_id}}

    workflow.status = WorkflowStatus.PARSING
    await db.commit()

    try:
        result = await pipeline.ainvoke(
            Command(resume={"__skip__": "true"}),
            config=config,
        )
    except Exception as exc:
        workflow.status = WorkflowStatus.AWAITING_CLARIFICATION
        await db.commit()
        detail = str(exc)
        if "checkpoint" in detail.lower() or "thread" in detail.lower():
            detail = "Pipeline session expired (server was restarted). Please re-run the workflow."
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline failed: {detail}",
        )

    return await _sync_workflow_from_result(workflow, result, db)


@router.post("/{workflow_id}/retry-push", response_model=WorkflowResponse)
async def retry_push(
    workflow_id: int,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Workflow:
    """Retry pushing to GitHub and creating a PR for a completed workflow."""
    workflow = await db.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found.",
        )

    eligible = {WorkflowStatus.COMPLETED, WorkflowStatus.PR_CREATED}
    if workflow.status not in eligible:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Retry push is only available for completed/pr_created workflows. Current: '{workflow.status}'.",
        )

    if not workflow.repo_local_path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No local repository path found. The repo may have been cleaned up.",
        )

    token = _extract_token(authorization) or get_settings().github_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No GitHub token provided. Set it in Settings or the backend .env.",
        )

    import subprocess
    try:
        branch_output = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=workflow.repo_local_path,
            text=True,
        ).strip()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not determine current branch in the local repo.",
        )

    title = workflow.requirement_summary.get("title", workflow.title) if workflow.requirement_summary else workflow.title
    body = f"Automated PR for workflow #{workflow.id}: {workflow.title}"

    pr_url = await push_and_create_pr(
        repo_path=workflow.repo_local_path,
        branch=branch_output,
        title=title,
        body=body,
        token=token,
    )

    workflow.pr_url = pr_url
    if pr_url.startswith("http"):
        workflow.status = WorkflowStatus.COMPLETED
    await db.commit()
    await db.refresh(workflow)

    return workflow


@router.get("", response_model=list[WorkflowResponse])
async def list_workflows(
    service_id: int | None = Query(default=None),
    status_filter: WorkflowStatus | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
) -> list[Workflow]:
    query = select(Workflow).order_by(Workflow.created_at.desc())

    if service_id is not None:
        query = query.where(Workflow.service_id == service_id)
    if status_filter is not None:
        query = query.where(Workflow.status == status_filter)

    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: int,
    db: AsyncSession = Depends(get_db),
) -> Workflow:
    workflow = await db.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found.",
        )
    return workflow


@router.get("/{workflow_id}/agent-runs", response_model=list[AgentRunResponse])
async def get_agent_runs(
    workflow_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[AgentRun]:
    """Get all agent runs for a workflow, ordered chronologically."""
    workflow = await db.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found.",
        )

    result = await db.execute(
        select(AgentRun)
        .where(AgentRun.workflow_id == workflow_id)
        .order_by(AgentRun.created_at.asc())
    )
    return list(result.scalars().all())


@router.patch("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: int,
    payload: WorkflowUpdate,
    db: AsyncSession = Depends(get_db),
) -> Workflow:
    workflow = await db.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found.",
        )

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(workflow, field, value)

    await db.commit()
    await db.refresh(workflow)

    return workflow


@router.post("/{workflow_id}/transition", response_model=WorkflowResponse)
async def transition_workflow(
    workflow_id: int,
    target_status: WorkflowStatus = Query(...),
    db: AsyncSession = Depends(get_db),
) -> Workflow:
    workflow = await db.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found.",
        )

    current = WorkflowStatus(workflow.status)
    allowed = VALID_TRANSITIONS.get(current, [])

    if target_status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot transition from '{current}' to '{target_status}'. "
                   f"Allowed transitions: {[s.value for s in allowed]}.",
        )

    workflow.status = target_status
    await db.commit()
    await db.refresh(workflow)

    return workflow
