from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.integrations.models import ServiceIntegration
from app.integrations.schemas import IntegrationCreate, IntegrationResponse, IntegrationUpdate
from app.services.models import Service

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.post(
    "",
    response_model=IntegrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_integration(
    payload: IntegrationCreate,
    db: AsyncSession = Depends(get_db),
) -> ServiceIntegration:
    service = await db.get(Service, payload.service_id)
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Service not found.",
        )

    result = await db.execute(
        select(ServiceIntegration).where(
            ServiceIntegration.service_id == payload.service_id,
            ServiceIntegration.integration_type == payload.integration_type,
            ServiceIntegration.provider == payload.provider,
            ServiceIntegration.is_active.is_(True),
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An active {payload.integration_type} integration with "
                   f"provider '{payload.provider}' already exists for this service.",
        )

    integration = ServiceIntegration(
        service_id=payload.service_id,
        integration_type=payload.integration_type,
        provider=payload.provider,
        external_identifier=payload.external_identifier,
        base_url=payload.base_url,
        config=payload.config,
    )

    db.add(integration)
    await db.commit()
    await db.refresh(integration)

    return integration


@router.get("", response_model=list[IntegrationResponse])
async def list_integrations(
    service_id: int | None = Query(default=None),
    integration_type: str | None = Query(default=None),
    active_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
) -> list[ServiceIntegration]:
    query = select(ServiceIntegration).order_by(ServiceIntegration.created_at.desc())

    if service_id is not None:
        query = query.where(ServiceIntegration.service_id == service_id)
    if integration_type is not None:
        query = query.where(ServiceIntegration.integration_type == integration_type)
    if active_only:
        query = query.where(ServiceIntegration.is_active.is_(True))

    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{integration_id}", response_model=IntegrationResponse)
async def get_integration(
    integration_id: int,
    db: AsyncSession = Depends(get_db),
) -> ServiceIntegration:
    integration = await db.get(ServiceIntegration, integration_id)
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found.",
        )
    return integration


@router.patch("/{integration_id}", response_model=IntegrationResponse)
async def update_integration(
    integration_id: int,
    payload: IntegrationUpdate,
    db: AsyncSession = Depends(get_db),
) -> ServiceIntegration:
    integration = await db.get(ServiceIntegration, integration_id)
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found.",
        )

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(integration, field, value)

    await db.commit()
    await db.refresh(integration)

    return integration


@router.delete("/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_integration(
    integration_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    integration = await db.get(ServiceIntegration, integration_id)
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found.",
        )

    integration.is_active = False
    await db.commit()
