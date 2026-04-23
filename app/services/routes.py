from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.services.models import Service
from app.services.schemas import ServiceCreate, ServiceResponse, ServiceUpdate

router = APIRouter(prefix="/services", tags=["services"])


@router.post(
    "",
    response_model=ServiceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_service(
    payload: ServiceCreate,
    db: AsyncSession = Depends(get_db),
) -> Service:
    result = await db.execute(
        select(Service).where(Service.slug == payload.slug)
    )
    existing_service = result.scalar_one_or_none()

    if existing_service:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Service with this slug already exists.",
        )

    service = Service(
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        department=payload.department,
        is_active=payload.is_active,
    )

    db.add(service)
    await db.commit()
    await db.refresh(service)

    return service


@router.get("", response_model=list[ServiceResponse])
async def list_services(
    db: AsyncSession = Depends(get_db),
) -> list[Service]:
    result = await db.execute(
        select(Service).order_by(Service.name.asc())
    )
    return list(result.scalars().all())


@router.get("/{service_id}", response_model=ServiceResponse)
async def get_service(
    service_id: int,
    db: AsyncSession = Depends(get_db),
) -> Service:
    service = await db.get(Service, service_id)
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Service not found.",
        )
    return service


@router.patch("/{service_id}", response_model=ServiceResponse)
async def update_service(
    service_id: int,
    payload: ServiceUpdate,
    db: AsyncSession = Depends(get_db),
) -> Service:
    service = await db.get(Service, service_id)
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Service not found.",
        )

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(service, field, value)

    await db.commit()
    await db.refresh(service)

    return service


@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_service(
    service_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    service = await db.get(Service, service_id)
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Service not found.",
        )

    service.is_active = False
    await db.commit()
