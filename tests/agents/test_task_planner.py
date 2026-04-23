from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.task_planner import ImplementationTask, TaskPlan, plan_tasks


def _mock_parsed_response(parsed_obj):
    message = MagicMock()
    message.parsed = parsed_obj
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    response.usage = MagicMock(total_tokens=200)
    return response


def _mock_track():
    mock_run = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_run)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=mock_ctx), mock_run


class TestPlanTasks:
    async def test_creates_ordered_tasks(self):
        plan = TaskPlan(
            tasks=[
                ImplementationTask(
                    id="T-1", title="Create Notification model",
                    description="Add SQLAlchemy model for notifications",
                    files=["app/notifications/models.py"],
                    depends_on=[], estimated_complexity="low",
                ),
                ImplementationTask(
                    id="T-2", title="Create notification routes",
                    description="Add CRUD API routes",
                    files=["app/notifications/routes.py"],
                    depends_on=["T-1"], estimated_complexity="medium",
                ),
                ImplementationTask(
                    id="T-3", title="Add tests",
                    description="Unit tests for notifications",
                    files=["tests/test_notifications.py"],
                    depends_on=["T-1", "T-2"], estimated_complexity="medium",
                ),
            ],
            implementation_order=["T-1", "T-2", "T-3"],
        )

        mock_llm = MagicMock()
        mock_llm.beta.chat.completions.parse = AsyncMock(return_value=_mock_parsed_response(plan))

        state = {
            "workflow_id": 1,
            "model": "gpt-4o",
            "requirement_summary": {"title": "Notifications"},
            "technical_design": {"overview": "Add notifications"},
        }

        track_fn, _ = _mock_track()

        with patch("app.agents.task_planner.get_llm_client", return_value=mock_llm), \
             patch("app.agents.task_planner.track_agent_run", track_fn):
            result = await plan_tasks(state)

        assert len(result["tasks"]) == 3
        assert result["tasks"][0]["id"] == "T-1"
        assert result["tasks"][1]["depends_on"] == ["T-1"]
        assert result["current_step"] == "ticketing"


class TestTaskPlanValidation:
    def test_task_with_dependencies(self):
        task = ImplementationTask(
            id="T-2", title="Routes", description="Add routes",
            files=["routes.py"], depends_on=["T-1"], estimated_complexity="medium",
        )
        assert task.depends_on == ["T-1"]

    def test_task_without_dependencies(self):
        task = ImplementationTask(
            id="T-1", title="Models", description="Add models",
            files=["models.py"], estimated_complexity="low",
        )
        assert task.depends_on == []
