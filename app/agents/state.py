from typing import Any, TypedDict


class ClarifyingQuestion(TypedDict):
    id: str
    question: str
    why: str


class ConversationRound(TypedDict):
    """One round of Q&A between the agent and the user."""
    questions: list[ClarifyingQuestion]
    answers: dict[str, str]


class PipelineState(TypedDict, total=False):
    """Shared state that flows through the LangGraph pipeline.

    Each node reads what it needs and returns only the fields it updates.
    LangGraph merges the returned fields into the existing state.
    """

    # Identifiers
    workflow_id: int
    model: str
    repo_url: str
    repo_path: str  # local clone path — set by the route after cloning
    github_token: str  # user-provided token for push/PR

    # Input
    feature_doc_text: str

    # FRD parsing (multi-round conversational)
    codebase_context: str
    clarifying_questions: list[ClarifyingQuestion]  # current round's questions
    clarification_answers: dict[str, str]  # current round's answers
    conversation_history: list[ConversationRound]  # all past rounds
    ready_to_finalize: bool  # agent signals it has enough info
    context_file_created: bool
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
    _review_count: int
