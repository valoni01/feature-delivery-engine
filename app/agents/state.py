from typing import Any, TypedDict


class PipelineState(TypedDict, total=False):
    """Shared state that flows through the LangGraph pipeline.

    Each node reads what it needs and returns only the fields it updates.
    LangGraph merges the returned fields into the existing state.
    """

    # Identifiers
    workflow_id: int
    model: str

    # Input
    feature_doc_text: str

    # Stage outputs (populated by each agent node)
    requirement_summary: dict[str, Any]
    technical_design: dict[str, Any]
    review_decision: str  # "approved" or "needs_rework"
    review_feedback: str
    tasks: list[dict[str, Any]]
    implementation_result: dict[str, Any]
    pr_url: str

    # Tracking
    current_step: str
    error: str | None
