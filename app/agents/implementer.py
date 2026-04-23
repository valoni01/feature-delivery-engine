import json
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import track_agent_run
from app.agents.state import PipelineState
from app.agents.tools.codebase import list_directory, read_file, search_files, write_file
from app.core.llm import get_llm_client


class FileWrite(BaseModel):
    file_path: str
    content: str
    action: str = Field(description="'create' or 'modify'")


class TaskResult(BaseModel):
    task_id: str
    status: str = Field(description="'completed' or 'failed'")
    files_written: list[str]
    summary: str


class ImplementationResult(BaseModel):
    task_results: list[TaskResult]
    files_changed: list[str] = Field(description="All files created or modified")
    summary: str


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
            "description": "List directory tree",
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
            "description": "Search for text pattern across files",
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
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file. Creates parent directories if needed. For new files, provide the full content. For modifications, provide the complete updated file content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Relative path from repo root"},
                    "content": {"type": "string", "description": "Full file content to write"},
                },
                "required": ["file_path", "content"],
            },
        },
    },
]

TOOL_HANDLERS = {
    "read_file": lambda rp, args: read_file(rp, args["file_path"]),
    "list_directory": lambda rp, args: list_directory(rp, args.get("dir_path", "."), args.get("max_depth", 3)),
    "search_files": lambda rp, args: search_files(rp, args["pattern"], args.get("file_extension")),
    "write_file": lambda rp, args: write_file(rp, args["file_path"], args["content"]),
}

MAX_TOOL_ROUNDS = 30

SYSTEM_PROMPT = """You are a senior software engineer implementing a feature based on a technical design and task list.

You have access to read and write files in the repository. For each task, you must:
1. Read the existing files you need to modify to understand current code
2. Write the new or modified files using write_file
3. Follow existing code patterns and conventions exactly
4. Write complete, working code — no placeholders, no TODOs, no "implement this"

RULES:
- When modifying a file, read it first, then write the COMPLETE updated file content
- Follow existing import styles, naming conventions, and code patterns
- Include proper error handling
- Keep code clean and well-structured
- Process tasks in the order specified by the task plan

IMPORTANT: Use write_file for every file you need to create or modify. The file content must be complete and syntactically valid."""


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


async def implement_tasks(state: PipelineState) -> dict:
    """LangGraph node: implements all tasks by writing code to the repository."""
    llm = get_llm_client()
    model = state["model"]
    workflow_id = state["workflow_id"]
    repo_path = state.get("repo_path", ".")

    tech_design = json.dumps(state["technical_design"], indent=2)
    tasks = json.dumps(state["tasks"], indent=2)

    async with track_agent_run(
        workflow_id, "implementer", model,
        input_data={"task_count": len(state["tasks"])},
    ) as run:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"## Technical Design\n```json\n{tech_design}\n```\n\n"
                f"## Tasks to Implement\n```json\n{tasks}\n```\n\n"
                "Implement all tasks in order. Read existing files before modifying them. "
                "Use write_file for every change. When done, provide a summary of what you implemented."
            )},
        ]

        raw = await _run_tool_loop(llm, model, messages, repo_path)

        structured = await llm.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": "Extract the implementation results into JSON."},
                {"role": "user", "content": raw},
            ],
            response_format=ImplementationResult,
            temperature=0.1,
        )

        impl = structured.choices[0].message.parsed
        tokens = structured.usage.total_tokens if structured.usage else 0
        result = impl.model_dump()
        run.output_data = result
        run.tokens_used = tokens

    return {"implementation_result": result, "current_step": "implementing"}
