from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from app.agents.frd_parser import analyze_frd, finalize_frd
from app.agents.state import PipelineState


async def wait_for_clarification(state: PipelineState) -> dict:
    """Human-in-the-loop node: pauses the pipeline and waits for answers.

    LangGraph's interrupt() suspends execution here. The pipeline resumes
    when the API receives the user's answers and calls graph.invoke()
    with the updated state containing clarification_answers.
    """
    questions = state.get("clarifying_questions", [])

    if not questions:
        return {"clarification_answers": {}}

    answers = interrupt({
        "type": "clarification_needed",
        "questions": questions,
    })

    return {"clarification_answers": answers}


def should_ask_questions(state: PipelineState) -> str:
    """Route after analysis: skip clarification if no questions were generated."""
    questions = state.get("clarifying_questions", [])
    if questions:
        return "wait_for_clarification"
    return "finalize_frd"


def build_pipeline() -> StateGraph:
    """Constructs the FDE pipeline graph.

    Current flow:
        analyze_frd → (questions?) → wait_for_clarification → finalize_frd → END
                                ↘ (no questions) → finalize_frd → END

    Future agents will be added as new nodes between finalize_frd and END.
    """
    graph = StateGraph(PipelineState)

    graph.add_node("analyze_frd", analyze_frd)
    graph.add_node("wait_for_clarification", wait_for_clarification)
    graph.add_node("finalize_frd", finalize_frd)

    graph.set_entry_point("analyze_frd")

    graph.add_conditional_edges(
        "analyze_frd",
        should_ask_questions,
        {
            "wait_for_clarification": "wait_for_clarification",
            "finalize_frd": "finalize_frd",
        },
    )

    graph.add_edge("wait_for_clarification", "finalize_frd")
    graph.add_edge("finalize_frd", END)

    return graph


checkpointer = MemorySaver()
pipeline = build_pipeline().compile(checkpointer=checkpointer)
