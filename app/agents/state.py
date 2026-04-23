from typing import Any, TypedDict


class ClarifyingQuestion(TypedDict):
    id: str
    question: str
    context: str


class PipelineState(TypedDict, total=False):
    """Shared state that flows through the LangGraph pipeline.

    Each node reads what it needs and returns only the fields it updates.
    LangGraph merges the returned fields into the existing state.
    """

    # Identifiers
    workflow_id: int
    model: str
    repo_path: str

    # Input
    feature_doc_text: str

    # FRD parsing (two-step: analyze → clarify → finalize)
    codebase_context: str
    clarifying_questions: list[ClarifyingQuestion]
    clarification_answers: dict[str, str]
    requirement_summary: dict[str, Any]

    # Design & review
    technical_design: dict[str, Any]
    review_decision: str  # "approved" or "needs_rework"
    review_feedback: str

    # Ticketing & implementation
    tasks: list[dict[str, Any]]
    implementation_result: dict[str, Any]
    pr_url: str

    # Tracking
    current_step: str
    error: str | None
