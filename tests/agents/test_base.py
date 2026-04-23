from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.base import track_agent_run


class TestTrackAgentRun:
    async def test_success_path(self):
        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        async with track_agent_run(
            workflow_id=1,
            agent_name="test_agent",
            model="gpt-4o",
            input_data={"source_field": "test"},
            db=mock_session,
        ) as run:
            run.output_data = {"result": "ok"}
            run.tokens_used = 42

        assert run.status == "success"
        assert run.duration_ms is not None
        assert run.duration_ms >= 0
        mock_session.add.assert_called_once()
        assert mock_session.commit.await_count == 2  # once for create, once for success

    async def test_failure_path(self):
        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        try:
            async with track_agent_run(
                workflow_id=1,
                agent_name="test_agent",
                model="gpt-4o",
                db=mock_session,
            ) as run:
                raise ValueError("Something went wrong")
        except ValueError:
            pass

        assert run.status == "failed"
        assert run.error == "Something went wrong"
        assert run.duration_ms is not None
        assert mock_session.commit.await_count == 2

    async def test_creates_run_with_correct_fields(self):
        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        async with track_agent_run(
            workflow_id=42,
            agent_name="frd_parser",
            model="gpt-4o-mini",
            input_data={"source_field": "feature_doc_text"},
            db=mock_session,
        ) as run:
            pass

        assert run.workflow_id == 42
        assert run.agent_name == "frd_parser"
        assert run.model_used == "gpt-4o-mini"
        assert run.input_data == {"source_field": "feature_doc_text"}

    async def test_creates_own_session_when_none_provided(self):
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.agents.base.async_session", return_value=mock_session):
            async with track_agent_run(
                workflow_id=1,
                agent_name="test",
                model="gpt-4o",
            ) as run:
                pass

        mock_session.close.assert_awaited_once()
