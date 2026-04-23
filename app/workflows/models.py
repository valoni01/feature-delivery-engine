from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    service_id: Mapped[int] = mapped_column(
        ForeignKey("services.id"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    feature_doc_text: Mapped[str] = mapped_column(nullable=False)
    repo_url: Mapped[str] = mapped_column(String(500), nullable=False)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    repo_local_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    pending_questions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    requirement_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    technical_design: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tasks: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
