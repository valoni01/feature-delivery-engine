from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.frd_parser import (
    RequirementSummary,
    analyze_frd,
    finalize_frd,
)

SAMPLE_FRD = "We need a user notification system with email and SMS support."

SAMPLE_REQUIREMENT_SUMMARY = {
    "title": "User Notification System",
    "summary": "A notification system that supports email and SMS channels.",
    "goals": ["Enable multi-channel notifications"],
    "functional_requirements": [
        {"id": "FR-1", "description": "Send email notifications", "priority": "must-have"},
        {"id": "FR-2", "description": "Send SMS notifications", "priority": "must-have"},
    ],
    "non_functional_requirements": [
        {"id": "NFR-1", "description": "Handle 10k messages per minute", "category": "performance"},
    ],
    "acceptance_criteria": ["Email delivery succeeds", "SMS delivery succeeds"],
    "assumptions": ["Existing SMTP server available"],
    "open_questions": ["Should we support push notifications?"],
}


def _make_mock_llm():
    """Build a properly structured mock AsyncOpenAI client."""
    mock = MagicMock()
    mock.chat.completions.create = AsyncMock()
    mock.beta.chat.completions.parse = AsyncMock()
    return mock


def _mock_tool_response(content: str, tool_calls=None, finish_reason="stop"):
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls or []

    choice = MagicMock()
    choice.message = message
    choice.finish_reason = finish_reason

    usage = MagicMock()
    usage.total_tokens = 150

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


def _mock_parsed_response(parsed_obj, tokens=100):
    message = MagicMock()
    message.parsed = parsed_obj

    choice = MagicMock()
    choice.message = message

    usage = MagicMock()
    usage.total_tokens = tokens

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


def _mock_track():
    """Build a mock for track_agent_run context manager."""
    mock_run = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_run)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_track_fn = MagicMock(return_value=mock_ctx)
    return mock_track_fn, mock_run


class TestAnalyzeFRD:
    async def test_analyze_returns_questions(self):
        from app.agents.frd_parser import AnalysisResult, ClarifyingQuestionItem

        analysis = AnalysisResult(
            codebase_observations="Found existing notification module at /services/notify",
            clarifying_questions=[
                ClarifyingQuestionItem(
                    id="Q-1",
                    question="Should quiet hours apply globally?",
                    context="The FRD mentions quiet hours but doesn't specify scope.",
                ),
            ],
        )

        mock_llm = _make_mock_llm()
        mock_llm.chat.completions.create.return_value = _mock_tool_response(
            content="I found an existing notification service. Here is my analysis..."
        )
        mock_llm.beta.chat.completions.parse.return_value = _mock_parsed_response(analysis)

        state = {
            "workflow_id": 1,
            "model": "gpt-4o",
            "feature_doc_text": SAMPLE_FRD,
            "repo_path": "/fake/repo",
        }

        track_fn, _ = _mock_track()

        with patch("app.agents.frd_parser.get_llm_client", return_value=mock_llm), \
             patch("app.agents.frd_parser.track_agent_run", track_fn):
            result = await analyze_frd(state)

        assert "clarifying_questions" in result
        assert len(result["clarifying_questions"]) == 1
        assert result["clarifying_questions"][0]["id"] == "Q-1"
        assert "codebase_context" in result
        assert result["current_step"] == "analyzing"

    async def test_analyze_no_questions(self):
        from app.agents.frd_parser import AnalysisResult

        analysis = AnalysisResult(
            codebase_observations="Codebase is straightforward.",
            clarifying_questions=[],
        )

        mock_llm = _make_mock_llm()
        mock_llm.chat.completions.create.return_value = _mock_tool_response(content="All clear.")
        mock_llm.beta.chat.completions.parse.return_value = _mock_parsed_response(analysis)

        state = {
            "workflow_id": 1,
            "model": "gpt-4o",
            "feature_doc_text": SAMPLE_FRD,
            "repo_path": "/fake/repo",
        }

        track_fn, _ = _mock_track()

        with patch("app.agents.frd_parser.get_llm_client", return_value=mock_llm), \
             patch("app.agents.frd_parser.track_agent_run", track_fn):
            result = await analyze_frd(state)

        assert result["clarifying_questions"] == []


class TestFinalizeFRD:
    async def test_finalize_with_answers(self):
        summary = RequirementSummary(**SAMPLE_REQUIREMENT_SUMMARY)

        mock_llm = _make_mock_llm()
        mock_llm.beta.chat.completions.parse.return_value = _mock_parsed_response(summary)

        state = {
            "workflow_id": 1,
            "model": "gpt-4o",
            "feature_doc_text": SAMPLE_FRD,
            "codebase_context": "Found existing notify module.",
            "clarifying_questions": [{"id": "Q-1", "question": "Quiet hours scope?", "context": "..."}],
            "clarification_answers": {"Q-1": "Global quiet hours"},
        }

        track_fn, _ = _mock_track()

        with patch("app.agents.frd_parser.get_llm_client", return_value=mock_llm), \
             patch("app.agents.frd_parser.track_agent_run", track_fn):
            result = await finalize_frd(state)

        assert "requirement_summary" in result
        assert result["requirement_summary"]["title"] == "User Notification System"
        assert len(result["requirement_summary"]["functional_requirements"]) == 2
        assert result["current_step"] == "parsing"

    async def test_finalize_without_answers(self):
        summary = RequirementSummary(**SAMPLE_REQUIREMENT_SUMMARY)

        mock_llm = _make_mock_llm()
        mock_llm.beta.chat.completions.parse.return_value = _mock_parsed_response(summary)

        state = {
            "workflow_id": 1,
            "model": "gpt-4o",
            "feature_doc_text": SAMPLE_FRD,
        }

        track_fn, _ = _mock_track()

        with patch("app.agents.frd_parser.get_llm_client", return_value=mock_llm), \
             patch("app.agents.frd_parser.track_agent_run", track_fn):
            result = await finalize_frd(state)

        assert "requirement_summary" in result


class TestRequirementSummaryValidation:
    def test_valid_summary(self):
        summary = RequirementSummary(**SAMPLE_REQUIREMENT_SUMMARY)
        assert summary.title == "User Notification System"
        assert len(summary.functional_requirements) == 2

    def test_invalid_priority_rejected(self):
        import pytest

        bad_data = SAMPLE_REQUIREMENT_SUMMARY.copy()
        bad_data["functional_requirements"] = [
            {"id": "FR-1", "description": "Test", "priority": "critical"}
        ]
        with pytest.raises(Exception):
            RequirementSummary(**bad_data)

    def test_invalid_nfr_category_rejected(self):
        import pytest

        bad_data = SAMPLE_REQUIREMENT_SUMMARY.copy()
        bad_data["non_functional_requirements"] = [
            {"id": "NFR-1", "description": "Test", "category": "speed"}
        ]
        with pytest.raises(Exception):
            RequirementSummary(**bad_data)
