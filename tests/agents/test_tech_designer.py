from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.tech_designer import TechnicalDesign, FileChange, create_technical_design


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
    response.usage = MagicMock(total_tokens=300)
    return response


def _mock_track():
    mock_run = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_run)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=mock_ctx), mock_run


class TestCreateTechnicalDesign:
    async def test_produces_design(self):
        design = TechnicalDesign(
            overview="Add a notifications module following existing patterns.",
            file_changes=[
                FileChange(file_path="app/notifications/models.py", action="create", description="Notification model"),
                FileChange(file_path="app/notifications/routes.py", action="create", description="API routes"),
            ],
            api_endpoints=[],
            data_model_changes=[],
            dependencies=["flask-sock>=0.7"],
            migration_notes="Add notifications table",
            testing_strategy="Unit tests with mocked DB",
            risks_and_tradeoffs=["WebSocket support may need ASGI"],
        )

        mock_llm = _make_mock_llm()
        mock_llm.chat.completions.create.return_value = _mock_tool_response("Here is the design...")
        mock_llm.beta.chat.completions.parse.return_value = _mock_parsed_response(design)

        state = {
            "workflow_id": 1,
            "model": "gpt-4o",
            "repo_path": "/fake/repo",
            "requirement_summary": {"title": "Notifications", "goals": ["Notify users"]},
        }

        track_fn, _ = _mock_track()

        with patch("app.agents.tech_designer.get_llm_client", return_value=mock_llm), \
             patch("app.agents.tech_designer.track_agent_run", track_fn), \
             patch("app.agents.tech_designer.read_context", return_value="# Project context"):
            result = await create_technical_design(state)

        assert "technical_design" in result
        assert len(result["technical_design"]["file_changes"]) == 2
        assert result["current_step"] == "designing"

    async def test_design_schema_validation(self):
        design = TechnicalDesign(
            overview="Test overview",
            file_changes=[FileChange(file_path="test.py", action="create", description="test")],
            testing_strategy="Unit tests",
        )
        assert design.overview == "Test overview"
        assert len(design.file_changes) == 1
        assert design.dependencies == []
