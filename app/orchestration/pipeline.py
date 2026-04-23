from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from app.agents.design_reviewer import review_design
from app.agents.frd_parser import evaluate_frd, finalize_frd
from app.agents.implementer import implement_tasks
from app.agents.pr_creator import create_pr
from app.agents.state import PipelineState
from app.agents.task_planner import plan_tasks
from app.agents.tech_designer import create_technical_design

MAX_REVIEW_ROUNDS = 3


async def wait_for_clarification(state: PipelineState) -> dict:
    """Human-in-the-loop node: pauses the pipeline and waits for user answers."""
    questions = state.get("clarifying_questions", [])

    if not questions:
        return {"clarification_answers": {}, "conversation_history": state.get("conversation_history", [])}

    answers = interrupt({
        "type": "clarification_needed",
        "questions": questions,
    })

    if isinstance(answers, dict) and answers.get("__skip__"):
        return {
            "clarification_answers": {},
            "conversation_history": state.get("conversation_history", []),
            "ready_to_finalize": True,
        }

    current_round = {
        "questions": questions,
        "answers": answers,
    }
    history = list(state.get("conversation_history", []))
    history.append(current_round)

    return {
        "clarification_answers": answers,
        "conversation_history": history,
    }


def after_evaluation(state: PipelineState) -> str:
    """Route after evaluate_frd: ask user or finalize."""
    if state.get("ready_to_finalize", False):
        return "finalize_frd"
    questions = state.get("clarifying_questions", [])
    if questions:
        return "wait_for_clarification"
    return "finalize_frd"


def after_review(state: PipelineState) -> str:
    """Route after design review: proceed to ticketing or loop back for rework."""
    if state.get("review_decision") == "approved":
        return "plan_tasks"
    return "rework_design"


async def rework_design(state: PipelineState) -> dict:
    """Thin wrapper: re-runs technical design with review feedback incorporated.

    The tech_designer will see the existing design + feedback and produce a revised version.
    We cap rework rounds to prevent infinite loops.
    """
    review_count = state.get("_review_count", 0) + 1

    if review_count >= MAX_REVIEW_ROUNDS:
        return {"review_decision": "approved", "_review_count": review_count, "current_step": "auto_approved"}

    return {"_review_count": review_count}


def build_pipeline() -> StateGraph:
    """Constructs the full FDE pipeline graph.

    Flow:
        evaluate_frd ←→ wait_for_clarification (multi-round user chat)
              ↓
        finalize_frd
              ↓
        create_technical_design ←→ review_design (rework loop, max 3 rounds)
              ↓
        plan_tasks
              ↓
        implement_tasks
              ↓
        create_pr
              ↓
            END
    """
    graph = StateGraph(PipelineState)

    # FRD parsing nodes
    graph.add_node("evaluate_frd", evaluate_frd)
    graph.add_node("wait_for_clarification", wait_for_clarification)
    graph.add_node("finalize_frd", finalize_frd)

    # Design nodes
    graph.add_node("create_technical_design", create_technical_design)
    graph.add_node("review_design", review_design)
    graph.add_node("rework_design", rework_design)

    # Execution nodes
    graph.add_node("plan_tasks", plan_tasks)
    graph.add_node("implement_tasks", implement_tasks)
    graph.add_node("create_pr", create_pr)

    # Entry
    graph.set_entry_point("evaluate_frd")

    # FRD parsing edges
    graph.add_conditional_edges(
        "evaluate_frd",
        after_evaluation,
        {
            "wait_for_clarification": "wait_for_clarification",
            "finalize_frd": "finalize_frd",
        },
    )
    graph.add_edge("wait_for_clarification", "evaluate_frd")
    graph.add_edge("finalize_frd", "create_technical_design")

    # Design review loop
    graph.add_edge("create_technical_design", "review_design")
    graph.add_conditional_edges(
        "review_design",
        after_review,
        {
            "plan_tasks": "plan_tasks",
            "rework_design": "rework_design",
        },
    )
    graph.add_edge("rework_design", "create_technical_design")

    # Execution chain
    graph.add_edge("plan_tasks", "implement_tasks")
    graph.add_edge("implement_tasks", "create_pr")
    graph.add_edge("create_pr", END)

    return graph


checkpointer = MemorySaver()
pipeline = build_pipeline().compile(checkpointer=checkpointer)
