from app.orchestration.pipeline import after_evaluation, after_review, rework_design


class TestAfterEvaluation:
    def test_routes_to_finalize_when_ready(self):
        state = {"ready_to_finalize": True, "clarifying_questions": []}
        assert after_evaluation(state) == "finalize_frd"

    def test_routes_to_clarification_when_not_ready(self):
        state = {
            "ready_to_finalize": False,
            "clarifying_questions": [{"id": "Q-1", "question": "test?", "why": "..."}],
        }
        assert after_evaluation(state) == "wait_for_clarification"

    def test_routes_to_finalize_when_no_questions(self):
        state = {"ready_to_finalize": False, "clarifying_questions": []}
        assert after_evaluation(state) == "finalize_frd"

    def test_routes_to_finalize_when_ready_even_with_questions(self):
        state = {
            "ready_to_finalize": True,
            "clarifying_questions": [{"id": "Q-1", "question": "stale?", "why": "..."}],
        }
        assert after_evaluation(state) == "finalize_frd"

    def test_defaults_to_finalize_with_empty_state(self):
        state = {}
        assert after_evaluation(state) == "finalize_frd"


class TestAfterReview:
    def test_approved_routes_to_plan_tasks(self):
        state = {"review_decision": "approved"}
        assert after_review(state) == "plan_tasks"

    def test_needs_rework_routes_to_rework(self):
        state = {"review_decision": "needs_rework"}
        assert after_review(state) == "rework_design"

    def test_empty_decision_routes_to_rework(self):
        state = {"review_decision": ""}
        assert after_review(state) == "rework_design"


class TestReworkDesign:
    async def test_increments_review_count(self):
        state = {"_review_count": 0}
        result = await rework_design(state)
        assert result["_review_count"] == 1

    async def test_auto_approves_after_max_rounds(self):
        state = {"_review_count": 2}
        result = await rework_design(state)
        assert result["review_decision"] == "approved"
        assert result["current_step"] == "auto_approved"

    async def test_first_rework(self):
        state = {}
        result = await rework_design(state)
        assert result["_review_count"] == 1
        assert "review_decision" not in result
