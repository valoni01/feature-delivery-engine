import json
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import track_agent_run
from app.agents.state import PipelineState
from app.agents.tools.codebase import list_directory, read_file, read_context, search_files
from app.core.llm import get_llm_client


class ReviewItem(BaseModel):
    severity: str = Field(description="critical, major, or minor")
    area: str = Field(description="Which part of the design this applies to")
    issue: str = Field(description="What the problem is")
    suggestion: str = Field(description="How to fix it")


class DesignReview(BaseModel):
    decision: str = Field(description="'approved' or 'needs_rework'")
    summary: str = Field(description="1-2 sentence overall assessment")
    items: list[ReviewItem] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list, description="What the design does well")


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file in the repository",
            "parameters": {
                "type": "object",
                "properties": {"file_path": {"type": "string"}},
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List the directory tree",
            "parameters": {
                "type": "object",
                "properties": {
                    "dir_path": {"type": "string"},
                    "max_depth": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for a text pattern across files",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "file_extension": {"type": "string"},
                },
                "required": ["pattern"],
            },
        },
    },
]

TOOL_HANDLERS = {
    "read_file": lambda rp, args: read_file(rp, args["file_path"]),
    "list_directory": lambda rp, args: list_directory(rp, args.get("dir_path", "."), args.get("max_depth", 3)),
    "search_files": lambda rp, args: search_files(rp, args["pattern"], args.get("file_extension")),
}

MAX_TOOL_ROUNDS = 10

SYSTEM_PROMPT = """You are a principal engineer reviewing a technical design document before implementation begins.

You have access to the project's codebase through tools. Your job is to verify the design is correct, complete, and follows existing codebase conventions.

REVIEW CHECKLIST:
1. **Correctness** — Does the design actually solve the requirements? Are the file paths real? Do the proposed changes make sense given the existing code?
2. **Completeness** — Are there missing files, endpoints, or migrations? Does it cover edge cases?
3. **Consistency** — Does the design follow existing patterns? If the codebase uses a specific routing style, ORM pattern, or test structure, does the design match?
4. **Dependencies** — Are proposed new packages necessary? Are there existing packages that could be reused?
5. **Risks** — Are there security, performance, or compatibility concerns?

Read the actual files referenced in the design to verify paths and patterns are correct.

DECISION:
- Approve if the design is sound (minor issues are OK — note them but approve)
- Reject (needs_rework) only for critical or major issues that would lead to a broken implementation

Be constructive. Explain issues clearly and suggest fixes."""

MAX_REVIEW_ROUNDS = 3


async def _run_tool_loop(llm, model: str, messages: list[dict[str, Any]], repo_path: str) -> str:
    for _ in range(MAX_TOOL_ROUNDS):
        response = await llm.chat.completions.create(
            model=model, messages=messages, tools=TOOLS, temperature=0.2,
        )
        choice = response.choices[0]
        if choice.finish_reason == "stop" or not choice.message.tool_calls:
            return choice.message.content or ""

        messages.append(choice.message)
        for tc in choice.message.tool_calls:
            fn = tc.function.name
            args = json.loads(tc.function.arguments)
            handler = TOOL_HANDLERS.get(fn)
            try:
                result = handler(repo_path, args) if handler else f"Unknown tool: {fn}"
            except Exception as e:
                result = f"Error: {e}"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    return messages[-1].get("content", "")


async def review_design(state: PipelineState) -> dict:
    """LangGraph node: reviews the technical design and approves or requests rework."""
    llm = get_llm_client()
    model = state["model"]
    workflow_id = state["workflow_id"]
    repo_path = state.get("repo_path", ".")

    req_summary = json.dumps(state["requirement_summary"], indent=2)
    tech_design = json.dumps(state["technical_design"], indent=2)

    review_round = 1
    prev_feedback = state.get("review_feedback", "")
    if prev_feedback:
        review_round = 2

    async with track_agent_run(
        workflow_id, f"design_reviewer_r{review_round}", model,
        input_data={"source_field": "technical_design"},
    ) as run:
        user_content = (
            f"## Requirement Summary\n```json\n{req_summary}\n```\n\n"
            f"## Technical Design\n```json\n{tech_design}\n```"
        )
        if prev_feedback:
            user_content += f"\n\n## Previous Review Feedback (should be addressed)\n{prev_feedback}"

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        raw = await _run_tool_loop(llm, model, messages, repo_path)

        structured = await llm.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": "Extract the review into the required JSON structure."},
                {"role": "user", "content": raw},
            ],
            response_format=DesignReview,
            temperature=0.1,
        )

        review = structured.choices[0].message.parsed
        tokens = structured.usage.total_tokens if structured.usage else 0
        run.output_data = review.model_dump()
        run.tokens_used = tokens

    feedback_text = review.summary
    if review.items:
        feedback_text += "\n\nIssues:\n" + "\n".join(
            f"- [{i.severity}] {i.area}: {i.issue} → {i.suggestion}" for i in review.items
        )

    return {
        "review_decision": review.decision,
        "review_feedback": feedback_text,
        "current_step": "reviewing",
    }
