import json
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import track_agent_run
from app.agents.state import PipelineState
from app.agents.tools.codebase import list_directory, read_file, read_context, search_files
from app.core.llm import get_llm_client


class FileChange(BaseModel):
    file_path: str = Field(description="Relative path from repo root")
    action: str = Field(description="create, modify, or delete")
    description: str = Field(description="What changes to make and why")


class APIEndpoint(BaseModel):
    method: str
    path: str
    description: str
    request_body: str | None = Field(default=None, description="Brief description of request shape")
    response_body: str = Field(description="Brief description of response shape")


class DataModelChange(BaseModel):
    entity: str = Field(description="Table or model name")
    action: str = Field(description="create, modify, or delete")
    fields: list[str] = Field(description="List of field descriptions, e.g. 'email: str (unique, indexed)'")


class TechnicalDesign(BaseModel):
    overview: str = Field(description="2-3 paragraph summary of the implementation approach")
    file_changes: list[FileChange]
    api_endpoints: list[APIEndpoint] = Field(default_factory=list)
    data_model_changes: list[DataModelChange] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list, description="New packages to add, e.g. 'flask-sock>=0.7'")
    migration_notes: str = Field(default="", description="Notes on database migrations needed")
    testing_strategy: str = Field(description="How to test this feature")
    risks_and_tradeoffs: list[str] = Field(default_factory=list, description="Known risks or tradeoffs")


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file in the repository",
            "parameters": {
                "type": "object",
                "properties": {"file_path": {"type": "string", "description": "Relative path from repo root"}},
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List the directory tree of the repository or a subdirectory",
            "parameters": {
                "type": "object",
                "properties": {
                    "dir_path": {"type": "string", "description": "Relative path. Use '.' for root."},
                    "max_depth": {"type": "integer", "description": "Recursion depth. Default 3."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for a text pattern across files in the repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Text to search for (case-insensitive)"},
                    "file_extension": {"type": "string", "description": "Optional filter like '.py', '.ts'"},
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

SYSTEM_PROMPT = """You are a senior software architect producing a technical design document.

You are given a requirement summary (from a product conversation) and you have access to the project's codebase through tools. Your job is to produce a detailed, actionable technical design that an engineer can follow to implement the feature.

{context_section}

APPROACH:
1. Read the project context file and the requirement summary carefully
2. Explore the codebase deeply — read the actual source files that will need to change
3. Understand existing patterns (how routes are defined, how models work, how tests are written)
4. Design a solution that follows existing conventions exactly
5. Be specific: name exact files, exact function signatures, exact field names

YOUR DESIGN MUST INCLUDE:
- Every file that needs to be created or modified, with a clear description of the changes
- API endpoint contracts (method, path, request/response shapes) if applicable
- Data model changes (tables, fields, types, constraints) if applicable
- New dependencies needed
- Database migration notes
- Testing strategy (what to test, how)
- Risks and tradeoffs

BE PRECISE. Don't say "add a route" — say "add POST /api/v1/notifications to app/notifications/routes.py with NotificationCreate schema". Don't say "add a model" — say "create app/notifications/models.py with Notification table (id, user_id FK, type varchar(50), ...)".
"""


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


async def create_technical_design(state: PipelineState) -> dict:
    """LangGraph node: produces a technical design from the requirement summary."""
    llm = get_llm_client()
    model = state["model"]
    workflow_id = state["workflow_id"]
    repo_path = state.get("repo_path", ".")

    existing_context = read_context(repo_path)
    context_section = f"PROJECT CONTEXT:\n{existing_context}" if existing_context else "No project context file found. Explore the codebase thoroughly."

    system = SYSTEM_PROMPT.format(context_section=context_section)
    req_summary = json.dumps(state["requirement_summary"], indent=2)

    async with track_agent_run(
        workflow_id, "tech_designer", model,
        input_data={"source_field": "requirement_summary"},
    ) as run:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"## Requirement Summary\n```json\n{req_summary}\n```\n\nProduce the technical design. Explore the codebase first to understand existing patterns."},
        ]

        raw = await _run_tool_loop(llm, model, messages, repo_path)

        structured = await llm.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": "Extract the technical design into the required JSON structure. Be precise with file paths and field names."},
                {"role": "user", "content": raw},
            ],
            response_format=TechnicalDesign,
            temperature=0.1,
        )

        design = structured.choices[0].message.parsed
        tokens = structured.usage.total_tokens if structured.usage else 0
        result = design.model_dump()
        run.output_data = result
        run.tokens_used = tokens

    return {"technical_design": result, "current_step": "designing"}
