from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.implementer import ImplementationResult, TaskResult, implement_tasks


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
    response.usage = MagicMock(total_tokens=500)
    return response


def _mock_parsed_response(parsed_obj):
    message = MagicMock()
    message.parsed = parsed_obj
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    response.usage = MagicMock(total_tokens=600)
    return response


def _mock_track():
    mock_run = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_run)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=mock_ctx), mock_run


class TestImplementTasks:
    async def test_implements_all_tasks(self):
        impl = ImplementationResult(
            task_results=[
                TaskResult(task_id="T-1", status="completed", files_written=["app/models.py"], summary="Created model"),
                TaskResult(task_id="T-2", status="completed", files_written=["app/routes.py"], summary="Created routes"),
            ],
            files_changed=["app/models.py", "app/routes.py"],
            summary="Implemented notification model and routes.",
        )

        mock_llm = _make_mock_llm()
        mock_llm.chat.completions.create.return_value = _mock_tool_response("Implemented everything.")
        mock_llm.beta.chat.completions.parse.return_value = _mock_parsed_response(impl)

        state = {
            "workflow_id": 1,
            "model": "gpt-4o",
            "repo_path": "/fake/repo",
            "technical_design": {"overview": "Add notifications"},
            "tasks": [
                {"id": "T-1", "title": "Create model", "files": ["app/models.py"]},
                {"id": "T-2", "title": "Create routes", "files": ["app/routes.py"]},
            ],
        }

        track_fn, _ = _mock_track()

        with patch("app.agents.implementer.get_llm_client", return_value=mock_llm), \
             patch("app.agents.implementer.track_agent_run", track_fn):
            result = await implement_tasks(state)

        assert "implementation_result" in result
        assert len(result["implementation_result"]["task_results"]) == 2
        assert result["implementation_result"]["task_results"][0]["status"] == "completed"
        assert result["current_step"] == "implementing"


class TestImplementationResultValidation:
    def test_completed_result(self):
        r = ImplementationResult(
            task_results=[TaskResult(task_id="T-1", status="completed", files_written=["a.py"], summary="Done")],
            files_changed=["a.py"],
            summary="All done",
        )
        assert len(r.task_results) == 1

    def test_failed_result(self):
        r = TaskResult(task_id="T-1", status="failed", files_written=[], summary="Syntax error")
        assert r.status == "failed"
