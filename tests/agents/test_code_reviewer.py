from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.code_reviewer import CodeIssue, CodeReview, review_code
from app.orchestration.pipeline import after_code_review, fix_code


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


class TestReviewCode:
    async def test_approves_clean_code(self):
        review = CodeReview(
            decision="approved",
            summary="Code is clean and follows project conventions.",
            issues=[],
            strengths=["Good error handling", "Consistent naming"],
        )

        mock_llm = _make_mock_llm()
        mock_llm.chat.completions.create.return_value = _mock_tool_response("Code looks good.")
        mock_llm.beta.chat.completions.parse.return_value = _mock_parsed_response(review)

        state = {
            "workflow_id": 1,
            "model": "gpt-4o",
            "repo_path": "/fake/repo",
            "technical_design": {"overview": "Add Feature X"},
            "implementation_result": {"files_changed": ["app/models.py"]},
        }

        track_fn, _ = _mock_track()

        with patch("app.agents.code_reviewer.get_llm_client", return_value=mock_llm), \
             patch("app.agents.code_reviewer.track_agent_run", track_fn):
            result = await review_code(state)

        assert result["code_review_decision"] == "approved"
        assert result["current_step"] == "code_reviewing"

    async def test_rejects_with_issues(self):
        review = CodeReview(
            decision="needs_rework",
            summary="Found critical bugs and missing error handling.",
            issues=[
                CodeIssue(
                    severity="critical",
                    file_path="app/routes.py",
                    line_hint="create_user()",
                    issue="No input validation on email field",
                    suggestion="Add Pydantic validation",
                ),
                CodeIssue(
                    severity="major",
                    file_path="app/models.py",
                    line_hint="User class",
                    issue="Missing unique constraint on email",
                    suggestion="Add unique=True to email column",
                ),
            ],
            strengths=["Good test structure"],
        )

        mock_llm = _make_mock_llm()
        mock_llm.chat.completions.create.return_value = _mock_tool_response("Issues found.")
        mock_llm.beta.chat.completions.parse.return_value = _mock_parsed_response(review)

        state = {
            "workflow_id": 1,
            "model": "gpt-4o",
            "repo_path": "/fake/repo",
            "technical_design": {"overview": "Add Feature X"},
            "implementation_result": {"files_changed": ["app/routes.py", "app/models.py"]},
        }

        track_fn, _ = _mock_track()

        with patch("app.agents.code_reviewer.get_llm_client", return_value=mock_llm), \
             patch("app.agents.code_reviewer.track_agent_run", track_fn):
            result = await review_code(state)

        assert result["code_review_decision"] == "needs_rework"
        assert "No input validation" in result["code_review_feedback"]
        assert "app/routes.py" in result["code_review_feedback"]

    async def test_includes_previous_feedback(self):
        review = CodeReview(
            decision="approved",
            summary="Previous issues are fixed.",
            issues=[],
            strengths=[],
        )

        mock_llm = _make_mock_llm()
        mock_llm.chat.completions.create.return_value = _mock_tool_response("Fixed.")
        mock_llm.beta.chat.completions.parse.return_value = _mock_parsed_response(review)

        state = {
            "workflow_id": 1,
            "model": "gpt-4o",
            "repo_path": "/fake/repo",
            "technical_design": {"overview": "Add Feature X"},
            "implementation_result": {"files_changed": ["app/models.py"]},
            "code_review_feedback": "Previous: missing email validation",
            "_code_review_count": 1,
        }

        track_fn, _ = _mock_track()

        with patch("app.agents.code_reviewer.get_llm_client", return_value=mock_llm), \
             patch("app.agents.code_reviewer.track_agent_run", track_fn):
            result = await review_code(state)

        assert result["code_review_decision"] == "approved"


class TestAfterCodeReview:
    def test_approved_routes_to_create_pr(self):
        state = {"code_review_decision": "approved"}
        assert after_code_review(state) == "create_pr"

    def test_needs_rework_routes_to_fix(self):
        state = {"code_review_decision": "needs_rework"}
        assert after_code_review(state) == "fix_code"

    def test_empty_decision_routes_to_fix(self):
        state = {"code_review_decision": ""}
        assert after_code_review(state) == "fix_code"


class TestFixCode:
    async def test_increments_review_count(self):
        state = {"_code_review_count": 0}
        result = await fix_code(state)
        assert result["_code_review_count"] == 1

    async def test_auto_approves_after_max_rounds(self):
        state = {"_code_review_count": 1}
        result = await fix_code(state)
        assert result["code_review_decision"] == "approved"
        assert result["current_step"] == "code_auto_approved"

    async def test_first_fix(self):
        state = {}
        result = await fix_code(state)
        assert result["_code_review_count"] == 1
        assert "code_review_decision" not in result
