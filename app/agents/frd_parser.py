import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agents.base import track_agent_run
from app.agents.state import PipelineState
from app.agents.tools.codebase import list_directory, read_file, search_files
from app.core.llm import get_llm_client

# ── Pydantic response models ──

class FunctionalRequirement(BaseModel):
    id: str = Field(description="Unique ID like FR-1, FR-2")
    description: str
    priority: Literal["must-have", "should-have", "nice-to-have"]


class NonFunctionalRequirement(BaseModel):
    id: str = Field(description="Unique ID like NFR-1, NFR-2")
    description: str
    category: Literal["performance", "security", "scalability", "reliability", "usability"]


class RequirementSummary(BaseModel):
    title: str = Field(description="Short title for the feature")
    summary: str = Field(description="2-3 sentence overview of what the feature does")
    goals: list[str]
    functional_requirements: list[FunctionalRequirement]
    non_functional_requirements: list[NonFunctionalRequirement]
    acceptance_criteria: list[str]
    assumptions: list[str]
    open_questions: list[str]


class ClarifyingQuestionItem(BaseModel):
    id: str = Field(description="Unique ID like Q-1, Q-2")
    question: str
    context: str = Field(description="Why this question matters for the implementation")


class AnalysisResult(BaseModel):
    codebase_observations: str = Field(description="Key observations about the existing codebase relevant to this feature")
    clarifying_questions: list[ClarifyingQuestionItem]


# ── Tool definitions for OpenAI function calling ──

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file in the repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Relative path to the file from repo root, e.g. 'app/main.py'",
                    }
                },
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
                    "dir_path": {
                        "type": "string",
                        "description": "Relative path to list. Use '.' for the repo root.",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "How deep to recurse. Default 3.",
                    },
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
                    "pattern": {
                        "type": "string",
                        "description": "Text to search for (case-insensitive)",
                    },
                    "file_extension": {
                        "type": "string",
                        "description": "Optional filter like '.py', '.ts'",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
]

TOOL_HANDLERS = {
    "read_file": lambda repo_path, args: read_file(repo_path, args["file_path"]),
    "list_directory": lambda repo_path, args: list_directory(repo_path, args.get("dir_path", "."), args.get("max_depth", 3)),
    "search_files": lambda repo_path, args: search_files(repo_path, args["pattern"], args.get("file_extension")),
}

MAX_TOOL_ROUNDS = 10

ANALYZE_SYSTEM_PROMPT = """You are a senior software architect analyzing a Feature Requirement Document (FRD).

You have access to the project's codebase through tools. Your job is to:
1. Explore the codebase to understand the existing architecture, patterns, and relevant code
2. Identify any ambiguities, gaps, or contradictions in the FRD
3. Generate clarifying questions that would help produce a better technical plan

Follow this exploration strategy:

STEP 1 — List the project structure first (list_directory at root).

STEP 2 — Check for documentation files: AGENTS.md, README.md, CONTRIBUTING.md, ARCHITECTURE.md, docs/, or any .md files in the root. These give quick context on conventions, setup, and architecture. However, treat docs as hints, NOT as the source of truth — they may be stale or incomplete.

STEP 3 — Read the actual codebase. This is the primary source of truth. Look for:
- Existing patterns and conventions (how are routes structured? what ORM patterns are used?)
- Related functionality that already exists (anything similar to the requested feature?)
- Dependencies and constraints (what packages are used? what DB schema exists?)
- Potential conflicts with the requested feature

STEP 4 — If anything in the docs contradicts what you see in the code, trust the code.

Be thorough in your exploration. Read the files that matter."""

FINALIZE_SYSTEM_PROMPT = """You are a senior software architect. You have already analyzed a Feature Requirement Document and explored the codebase. The user has answered your clarifying questions.

Now produce the final structured requirement summary. Incorporate:
- What you learned from the codebase exploration
- The answers to your clarifying questions
- Every requirement from the FRD, including implicit ones

Be thorough and precise."""


async def _run_tool_loop(
    llm,
    model: str,
    messages: list[dict[str, Any]],
    repo_path: str,
) -> str:
    """Runs the LLM with tools until it produces a final text response."""
    for _ in range(MAX_TOOL_ROUNDS):
        response = await llm.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            temperature=0.2,
        )

        choice = response.choices[0]

        if choice.finish_reason == "stop" or not choice.message.tool_calls:
            return choice.message.content or ""

        messages.append(choice.message)

        for tool_call in choice.message.tool_calls:
            fn_name = tool_call.function.name
            fn_args = json.loads(tool_call.function.arguments)
            handler = TOOL_HANDLERS.get(fn_name)

            try:
                result = handler(repo_path, fn_args) if handler else f"Unknown tool: {fn_name}"
            except Exception as e:
                result = f"Error: {e}"

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

    return messages[-1].get("content", "")


async def analyze_frd(state: PipelineState) -> dict:
    """LangGraph node (step 1): explores codebase and generates clarifying questions."""
    llm = get_llm_client()
    model = state["model"]
    workflow_id = state["workflow_id"]
    repo_path = state.get("repo_path", ".")

    async with track_agent_run(workflow_id, "frd_parser_analyze", model, input_data={"source_field": "feature_doc_text"}) as run:
        messages = [
            {"role": "system", "content": ANALYZE_SYSTEM_PROMPT},
            {"role": "user", "content": f"Here is the Feature Requirement Document:\n\n{state['feature_doc_text']}"},
        ]

        raw_analysis = await _run_tool_loop(llm, model, messages, repo_path)

        messages_for_parse = [
            {"role": "system", "content": "Extract your analysis into the required JSON structure."},
            {"role": "user", "content": raw_analysis},
        ]
        structured = await llm.beta.chat.completions.parse(
            model=model,
            messages=messages_for_parse,
            response_format=AnalysisResult,
            temperature=0.1,
        )

        analysis = structured.choices[0].message.parsed
        tokens = (structured.usage.total_tokens if structured.usage else 0)

        run.output_data = analysis.model_dump()
        run.tokens_used = tokens

    return {
        "codebase_context": analysis.codebase_observations,
        "clarifying_questions": [q.model_dump() for q in analysis.clarifying_questions],
        "current_step": "analyzing",
    }


async def finalize_frd(state: PipelineState) -> dict:
    """LangGraph node (step 2): produces final requirement summary using answers."""
    llm = get_llm_client()
    model = state["model"]
    workflow_id = state["workflow_id"]

    qa_section = ""
    answers = state.get("clarification_answers", {})
    questions = state.get("clarifying_questions", [])
    if questions and answers:
        qa_lines = []
        for q in questions:
            answer = answers.get(q["id"], "No answer provided")
            qa_lines.append(f"Q ({q['id']}): {q['question']}\nA: {answer}")
        qa_section = "\n\n".join(qa_lines)

    async with track_agent_run(workflow_id, "frd_parser_finalize", model, input_data={"source_field": "clarification_answers"}) as run:
        response = await llm.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": FINALIZE_SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"## Feature Requirement Document\n{state['feature_doc_text']}\n\n"
                    f"## Codebase Observations\n{state.get('codebase_context', 'None')}\n\n"
                    f"## Clarifying Q&A\n{qa_section or 'No questions were asked.'}"
                )},
            ],
            response_format=RequirementSummary,
            temperature=0.2,
        )

        parsed = response.choices[0].message.parsed
        tokens = response.usage.total_tokens if response.usage else 0

        result = parsed.model_dump()
        run.output_data = result
        run.tokens_used = tokens

    return {"requirement_summary": result, "current_step": "parsing"}
