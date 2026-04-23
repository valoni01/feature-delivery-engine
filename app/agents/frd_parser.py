import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agents.base import track_agent_run
from app.agents.state import PipelineState
from app.agents.tools.codebase import list_directory, read_file, read_context, search_files, write_context
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
    question: str = Field(description="A plain-language question a non-technical person can answer")
    why: str = Field(description="One sentence explaining why this matters for the feature, in simple terms")


class EvaluationDecision(BaseModel):
    ready_to_finalize: bool = Field(description="True if you have enough information to produce the requirement summary. False if you need to ask more questions.")
    codebase_observations: str = Field(description="Key observations about the existing codebase relevant to this feature (internal note, not shown to user)")
    clarifying_questions: list[ClarifyingQuestionItem] = Field(
        default_factory=list,
        description="Product/business questions for the user. Empty if ready_to_finalize is True.",
    )
    reasoning: str = Field(description="Internal reasoning for why you are or aren't ready to finalize")


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
    {
        "type": "function",
        "function": {
            "name": "write_context",
            "description": "Write or update the .fde/context.md project context file. Call this after exploring the codebase to persist your understanding for future runs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Full markdown content for the context file. Include: project overview, architecture, key patterns, existing features, conventions, and recent changes.",
                    },
                },
                "required": ["content"],
            },
        },
    },
]

TOOL_HANDLERS = {
    "read_file": lambda repo_path, args: read_file(repo_path, args["file_path"]),
    "list_directory": lambda repo_path, args: list_directory(repo_path, args.get("dir_path", "."), args.get("max_depth", 3)),
    "search_files": lambda repo_path, args: search_files(repo_path, args["pattern"], args.get("file_extension")),
    "write_context": lambda repo_path, args: write_context(repo_path, args["content"]),
}

MAX_TOOL_ROUNDS = 10

EVALUATE_SYSTEM_PROMPT = """You are a product-minded software architect. You are chatting with a project manager or product owner who has written a Feature Requirement Document (FRD). They are NOT an engineer — they think in terms of user stories, business goals, and outcomes.

You have access to the project's codebase through tools. You will use these tools privately to understand the technical landscape, but the user does not need to know about your codebase exploration.

{context_instructions}

YOUR ROLE IN THIS CONVERSATION:

1. Silently explore the codebase to understand architecture, patterns, and constraints. YOU make all technical decisions (libraries, patterns, data models, APIs) — never ask the user about these.

2. Only ask the user about PRODUCT and BUSINESS questions — things only they can answer:
   - Scope and priorities ("Is this for all users or just admins?")
   - User experience expectations ("Should users get notified in real-time or is a daily digest fine?")
   - Business rules ("What happens when a payment fails — retry or cancel?")
   - Edge cases from a product perspective ("Should deleted users keep their data?")
   - Feature boundaries ("Is this a standalone feature or part of the existing dashboard?")

3. NEVER ask about:
   - Libraries, frameworks, or tools ("Which JWT library?")
   - Technical architecture ("Should we use Redis?")
   - Code patterns ("How should we structure the modules?")
   - Database design ("What columns should the table have?")
   - Implementation details ("Should we use async or sync?")

4. Keep questions short, friendly, and jargon-free. Write like you're chatting with a colleague, not writing a spec.

5. Ask 2-4 questions max per round. Respect the user's time.

DECISION: After exploring the codebase and reviewing the FRD (plus any prior conversation), decide whether you have enough product clarity to write the requirement summary. If yes, set ready_to_finalize=True. If the FRD has gaps only the user can fill, ask questions."""

CONTEXT_INSTRUCTIONS_FIRST = """This is your first time looking at this project. Explore the codebase thoroughly to understand what exists before talking to the user."""

CONTEXT_INSTRUCTIONS_EXISTING = """You have a project context file (.fde/context.md) from a previous analysis — its contents are included below. Use it as your baseline, but check for anything specifically relevant to this feature request."""


FINALIZE_SYSTEM_PROMPT = """You are a senior software architect. You have chatted with a project manager about their feature request and explored the codebase yourself.

Now produce the final structured requirement summary. You must:
- Translate the user's product-level answers into precise technical requirements
- Make all technical decisions yourself based on what you learned from the codebase (patterns, conventions, existing libraries, architecture)
- Follow the existing codebase conventions and patterns
- Include both the product requirements (from the user) and the technical requirements (from your codebase analysis)
- Flag any open questions that still need answers, but these should be rare

Be thorough and precise. The engineering team will use this to build the feature."""


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


def _build_conversation_history(state: PipelineState) -> str:
    """Build a readable history of all Q&A rounds so far."""
    history = state.get("conversation_history", [])
    if not history:
        return ""

    lines = []
    for i, round_data in enumerate(history, 1):
        lines.append(f"--- Round {i} ---")
        for q in round_data.get("questions", []):
            answer = round_data.get("answers", {}).get(q["id"], "No answer provided")
            lines.append(f"Q ({q['id']}): {q['question']}")
            lines.append(f"A: {answer}")
        lines.append("")

    return "\n".join(lines)


async def evaluate_frd(state: PipelineState) -> dict:
    """LangGraph node: explores codebase and decides whether to ask questions or finalize.

    This node is called in a loop. On each round it:
    1. Silently explores the codebase to understand the technical landscape
    2. Asks the user product/business questions (if needed) — never technical ones
    3. Or signals ready to produce the final requirement summary
    """
    if state.get("ready_to_finalize", False):
        return {
            "ready_to_finalize": True,
            "clarifying_questions": [],
            "current_step": "evaluating",
        }

    llm = get_llm_client()
    model = state["model"]
    workflow_id = state["workflow_id"]
    repo_path = state.get("repo_path", ".")
    round_number = len(state.get("conversation_history", [])) + 1

    existing_context = read_context(repo_path)
    has_context = existing_context is not None

    if has_context:
        context_instructions = CONTEXT_INSTRUCTIONS_EXISTING
    else:
        context_instructions = CONTEXT_INSTRUCTIONS_FIRST

    system_prompt = EVALUATE_SYSTEM_PROMPT.format(context_instructions=context_instructions)

    user_parts = []
    if has_context:
        user_parts.append(f"## Existing Project Context\n{existing_context}")

    user_parts.append(f"## Feature Requirement Document\n{state['feature_doc_text']}")

    conversation_text = _build_conversation_history(state)
    if conversation_text:
        user_parts.append(f"## Previous Conversation\n{conversation_text}")

    user_message = "\n\n".join(user_parts)

    async with track_agent_run(
        workflow_id, f"frd_parser_evaluate_r{round_number}", model,
        input_data={"round": round_number, "has_existing_context": has_context},
    ) as run:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        raw_analysis = await _run_tool_loop(llm, model, messages, repo_path)

        messages_for_parse = [
            {"role": "system", "content": "Extract your evaluation into the required JSON structure. Remember: questions must be product/business questions that a non-technical project manager can answer. Never ask about libraries, architecture, or implementation details."},
            {"role": "user", "content": raw_analysis},
        ]
        structured = await llm.beta.chat.completions.parse(
            model=model,
            messages=messages_for_parse,
            response_format=EvaluationDecision,
            temperature=0.1,
        )

        decision = structured.choices[0].message.parsed
        tokens = (structured.usage.total_tokens if structured.usage else 0)

        run.output_data = decision.model_dump()
        run.tokens_used = tokens

    return {
        "codebase_context": decision.codebase_observations,
        "clarifying_questions": [q.model_dump() for q in decision.clarifying_questions],
        "ready_to_finalize": decision.ready_to_finalize,
        "context_file_created": not has_context,
        "current_step": "evaluating",
    }


async def finalize_frd(state: PipelineState) -> dict:
    """LangGraph node: produces final requirement summary from the full conversation."""
    llm = get_llm_client()
    model = state["model"]
    workflow_id = state["workflow_id"]

    conversation_text = _build_conversation_history(state)

    async with track_agent_run(workflow_id, "frd_parser_finalize", model, input_data={"source_field": "conversation_history"}) as run:
        response = await llm.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": FINALIZE_SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"## Feature Requirement Document\n{state['feature_doc_text']}\n\n"
                    f"## Codebase Observations\n{state.get('codebase_context', 'None')}\n\n"
                    f"## Full Conversation with User\n{conversation_text or 'No questions were asked — the FRD was clear enough.'}"
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

    return {"requirement_summary": result, "current_step": "parsing_complete"}
