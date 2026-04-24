import json
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import track_agent_run
from app.agents.state import PipelineState
from app.agents.tools.codebase import list_directory, read_file, search_files
from app.core.llm import get_llm_client


class CodeIssue(BaseModel):
    severity: str = Field(description="critical, major, or minor")
    file_path: str = Field(description="File where the issue was found")
    line_hint: str = Field(description="Approximate location or function name")
    issue: str = Field(description="What the problem is")
    suggestion: str = Field(description="How to fix it")


class CodeReview(BaseModel):
    decision: str = Field(description="'approved' or 'needs_rework'")
    summary: str = Field(description="1-2 sentence overall assessment")
    issues: list[CodeIssue] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)


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

MAX_TOOL_ROUNDS = 15

SYSTEM_PROMPT = """You are a senior code reviewer examining code that was just written by an implementation agent.

You have access to the repository through tools. Your job is to read every file that was created or modified and verify the implementation is correct, complete, and production-ready.

REVIEW CHECKLIST:
1. **Correctness** — Does the code actually work? Are there logic errors, off-by-one mistakes, or broken imports?
2. **Completeness** — Does the implementation match the technical design? Are there missing pieces?
3. **Error handling** — Are errors properly caught and handled? Are edge cases covered?
4. **Security** — Are there injection risks, exposed secrets, missing auth checks, or unsafe operations?
5. **Code quality** — Is the code clean, well-structured, and following the project's existing conventions?
6. **Test coverage** — If tests were required, are they present and meaningful?

You MUST read every file listed in the implementation result. Do not skip files.

DECISION:
- Approve if the code is solid (minor style issues are OK — note them but approve)
- Reject (needs_rework) only for critical or major issues: bugs, security holes, missing functionality, or broken code

Be specific. Reference exact files and functions when reporting issues."""

MAX_CODE_REVIEW_ROUNDS = 2


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


async def review_code(state: PipelineState) -> dict:
    """LangGraph node: reviews implemented code for bugs, security issues, and quality."""
    llm = get_llm_client()
    model = state["model"]
    workflow_id = state["workflow_id"]
    repo_path = state.get("repo_path", ".")

    tech_design = json.dumps(state.get("technical_design", {}), indent=2)
    impl_result = json.dumps(state.get("implementation_result", {}), indent=2)

    review_round = state.get("_code_review_count", 0) + 1
    prev_feedback = state.get("code_review_feedback", "")

    async with track_agent_run(
        workflow_id, f"code_reviewer_r{review_round}", model,
        input_data={"source_field": "implementation_result"},
    ) as run:
        user_content = (
            f"## Technical Design\n```json\n{tech_design}\n```\n\n"
            f"## Implementation Result\n```json\n{impl_result}\n```\n\n"
            "Read every file listed in the implementation result and review the code thoroughly."
        )
        if prev_feedback:
            user_content += f"\n\n## Previous Review Feedback (should now be addressed)\n{prev_feedback}"

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        raw = await _run_tool_loop(llm, model, messages, repo_path)

        structured = await llm.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": "Extract the code review into the required JSON structure."},
                {"role": "user", "content": raw},
            ],
            response_format=CodeReview,
            temperature=0.1,
        )

        review = structured.choices[0].message.parsed
        tokens = structured.usage.total_tokens if structured.usage else 0
        run.output_data = review.model_dump()
        run.tokens_used = tokens

    feedback_text = review.summary
    if review.issues:
        feedback_text += "\n\nIssues:\n" + "\n".join(
            f"- [{i.severity}] {i.file_path} ({i.line_hint}): {i.issue} → {i.suggestion}"
            for i in review.issues
        )

    return {
        "code_review_decision": review.decision,
        "code_review_feedback": feedback_text,
        "current_step": "code_reviewing",
    }
