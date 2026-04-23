from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.services.models import Service
from app.workflows.models import Workflow
from app.workflows.schemas import WorkflowCreate, WorkflowResponse, WorkflowStatus, WorkflowUpdate

router = APIRouter(prefix="/workflows", tags=["workflows"])

VALID_TRANSITIONS: dict[WorkflowStatus, list[WorkflowStatus]] = {
    WorkflowStatus.DRAFT: [WorkflowStatus.PARSING, WorkflowStatus.FAILED],
    WorkflowStatus.PARSING: [WorkflowStatus.DESIGNING, WorkflowStatus.FAILED],
    WorkflowStatus.DESIGNING: [WorkflowStatus.REVIEWING, WorkflowStatus.FAILED],
    WorkflowStatus.REVIEWING: [WorkflowStatus.DESIGNING, WorkflowStatus.TICKETING, WorkflowStatus.FAILED],
    WorkflowStatus.TICKETING: [WorkflowStatus.IMPLEMENTING, WorkflowStatus.FAILED],
    WorkflowStatus.IMPLEMENTING: [WorkflowStatus.PR_CREATED, WorkflowStatus.FAILED],
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
        status=WorkflowStatus.DRAFT,
    )

    db.add(workflow)
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
