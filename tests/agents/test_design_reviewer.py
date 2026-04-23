from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.design_reviewer import DesignReview, ReviewItem, review_design


def _make_mock_llm():
    mock = MagicMock()
    mock.chat.completions.create = AsyncMock()
    mock.beta.chat.completions.parse = AsyncMock()
    return mock


def _mock_tool_response(content: str):
    message = MagicMock()
    message.content = content
    message.tool_calls = []
    choice = MagicMock()
    choice.message = message
    choice.finish_reason = "stop"
    response = MagicMock()
    response.choices = [choice]
    response.usage = MagicMock(total_tokens=200)
    return response


def _mock_parsed_response(parsed_obj):
    message = MagicMock()
    message.parsed = parsed_obj
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    response.usage = MagicMock(total_tokens=250)
    return response


def _mock_track():
    mock_run = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_run)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=mock_ctx), mock_run


class TestReviewDesign:
    async def test_approves_good_design(self):
        review = DesignReview(
            decision="approved",
            summary="Design looks solid and follows existing patterns.",
            items=[],
            strengths=["Good use of existing patterns", "Clear file structure"],
        )

        mock_llm = _make_mock_llm()
        mock_llm.chat.completions.create.return_value = _mock_tool_response("Looks good.")
        mock_llm.beta.chat.completions.parse.return_value = _mock_parsed_response(review)

        state = {
            "workflow_id": 1,
            "model": "gpt-4o",
            "repo_path": "/fake/repo",
            "requirement_summary": {"title": "Feature X"},
            "technical_design": {"overview": "Add Feature X"},
        }

        track_fn, _ = _mock_track()

        with patch("app.agents.design_reviewer.get_llm_client", return_value=mock_llm), \
             patch("app.agents.design_reviewer.track_agent_run", track_fn):
            result = await review_design(state)

        assert result["review_decision"] == "approved"
        assert result["current_step"] == "reviewing"

    async def test_rejects_with_issues(self):
        review = DesignReview(
            decision="needs_rework",
            summary="Missing error handling and wrong file paths.",
            items=[
                ReviewItem(severity="critical", area="routes", issue="Missing 404 handler", suggestion="Add not-found check"),
                ReviewItem(severity="major", area="models", issue="Wrong FK reference", suggestion="Fix foreign key to users.id"),
            ],
            strengths=["Good testing strategy"],
        )

        mock_llm = _make_mock_llm()
        mock_llm.chat.completions.create.return_value = _mock_tool_response("Issues found.")
        mock_llm.beta.chat.completions.parse.return_value = _mock_parsed_response(review)

        state = {
            "workflow_id": 1,
            "model": "gpt-4o",
            "repo_path": "/fake/repo",
            "requirement_summary": {"title": "Feature X"},
            "technical_design": {"overview": "Add Feature X"},
        }

        track_fn, _ = _mock_track()

        with patch("app.agents.design_reviewer.get_llm_client", return_value=mock_llm), \
             patch("app.agents.design_reviewer.track_agent_run", track_fn):
            result = await review_design(state)

        assert result["review_decision"] == "needs_rework"
        assert "Missing 404 handler" in result["review_feedback"]

    async def test_includes_previous_feedback(self):
        review = DesignReview(
            decision="approved",
            summary="Issues from previous round are addressed.",
            items=[],
            strengths=[],
        )

        mock_llm = _make_mock_llm()
        mock_llm.chat.completions.create.return_value = _mock_tool_response("Fixed.")
        mock_llm.beta.chat.completions.parse.return_value = _mock_parsed_response(review)

        state = {
            "workflow_id": 1,
            "model": "gpt-4o",
            "repo_path": "/fake/repo",
            "requirement_summary": {"title": "Feature X"},
            "technical_design": {"overview": "Revised design"},
            "review_feedback": "Previous: missing error handling",
        }

        track_fn, _ = _mock_track()

        with patch("app.agents.design_reviewer.get_llm_client", return_value=mock_llm), \
             patch("app.agents.design_reviewer.track_agent_run", track_fn):
            result = await review_design(state)

        assert result["review_decision"] == "approved"
