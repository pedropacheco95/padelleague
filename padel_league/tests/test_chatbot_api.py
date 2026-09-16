"""HTTP-level tests for the chatbot endpoint.

The LLM is replaced by a fake orchestrator so no API key or network is needed.
"""

import json
import os
import tempfile

import pytest

from padel_league import create_app
from padel_league.models import ChatbotLog
from padel_league.sql_db import db
from padel_league.core.llm_handler import LLMConversation
from padel_league.modules import chatbot_api


class FakeOrchestrator:
    """Records which conversation each call received and echoes the input."""

    def __init__(self, fail=False, empty=False):
        self.calls = []
        self.fail = fail
        self.empty = empty

    def new_conversation(self):
        return LLMConversation(system_prompt="test")

    def run(self, user_message, conversation=None, trace=None):
        self.calls.append((user_message, conversation))
        if trace is not None:
            trace["agent_name"] = "PadelLeagueAnswerAgent"
            trace["agent_questions"] = [f"rewritten: {user_message}"]
            trace["sql_queries"] = [
                {"question": user_message, "sql": "SELECT 1", "row_count": 1}
            ]
        if self.fail:
            raise RuntimeError("boom")
        if self.empty:
            return None
        conversation.add_message("user", user_message)
        conversation.add_message("assistant", f"echo: {user_message}")
        return f"echo: {user_message}"


@pytest.fixture
def app():
    db_fd, db_path = tempfile.mkstemp()
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SESSION_TYPE": "filesystem",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "JWT_SECRET_KEY": "test-jwt-secret",
            "JWT_TOKEN_LOCATION": ["headers"],
            "JWT_HEADER_TYPE": "Bearer",
        }
    )
    with app.app_context():
        ChatbotLog.__table__.create(bind=db.engine)

    yield app
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def fake_orchestrator(monkeypatch):
    fake = FakeOrchestrator()
    monkeypatch.setattr(chatbot_api, "orchestrator_agent", fake)
    monkeypatch.setattr(chatbot_api, "conversation_cache", {})
    return fake


def test_chat_answers_with_form_body(app, fake_orchestrator):
    client = app.test_client()
    resp = client.post("/api/v1/chatbot/chat", data={"user_input": "olá"})
    assert resp.status_code == 200
    assert resp.get_json() == {"response": "echo: olá"}


def test_chat_answers_with_json_body(app, fake_orchestrator):
    client = app.test_client()
    resp = client.post("/api/v1/chatbot/chat", json={"user_input": "olá"})
    assert resp.status_code == 200
    assert resp.get_json()["response"] == "echo: olá"


def test_chat_rejects_empty_input(app, fake_orchestrator):
    client = app.test_client()
    resp = client.post("/api/v1/chatbot/chat", data={"user_input": "   "})
    assert resp.status_code == 400
    assert fake_orchestrator.calls == []


def test_each_session_gets_its_own_conversation(app, fake_orchestrator):
    alice = app.test_client()
    bob = app.test_client()

    alice.post("/api/v1/chatbot/chat", data={"user_input": "a1"})
    bob.post("/api/v1/chatbot/chat", data={"user_input": "b1"})
    alice.post("/api/v1/chatbot/chat", data={"user_input": "a2"})

    conv_by_msg = {msg: conv for msg, conv in fake_orchestrator.calls}
    assert conv_by_msg["a1"] is conv_by_msg["a2"]
    assert conv_by_msg["a1"] is not conv_by_msg["b1"]

    alice_texts = [m.content for m in conv_by_msg["a1"].messages]
    assert "a1" in alice_texts and "a2" in alice_texts and "b1" not in alice_texts
    assert len(chatbot_api.conversation_cache) == 2


def test_reset_forgets_the_conversation(app, fake_orchestrator):
    client = app.test_client()
    client.post("/api/v1/chatbot/chat", data={"user_input": "a1"})
    first_conv = fake_orchestrator.calls[0][1]

    resp = client.post("/api/v1/chatbot/reset")
    assert resp.status_code == 200
    assert chatbot_api.conversation_cache == {}

    client.post("/api/v1/chatbot/chat", data={"user_input": "a2"})
    assert fake_orchestrator.calls[1][1] is not first_conv


def test_llm_failure_returns_fallback_not_500(app, monkeypatch):
    monkeypatch.setattr(chatbot_api, "orchestrator_agent", FakeOrchestrator(fail=True))
    monkeypatch.setattr(chatbot_api, "conversation_cache", {})
    client = app.test_client()
    resp = client.post("/api/v1/chatbot/chat", data={"user_input": "olá"})
    assert resp.status_code == 502
    body = resp.get_json()
    assert body["error"] == "llm_failure"
    assert body["response"] == chatbot_api.FALLBACK_ANSWER


def test_empty_llm_answer_returns_fallback(app, monkeypatch):
    monkeypatch.setattr(chatbot_api, "orchestrator_agent", FakeOrchestrator(empty=True))
    monkeypatch.setattr(chatbot_api, "conversation_cache", {})
    client = app.test_client()
    resp = client.post("/api/v1/chatbot/chat", data={"user_input": "olá"})
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "empty_answer"


def test_missing_llm_key_only_affects_chatbot_routes(app, monkeypatch):
    """Other endpoints must not depend on LLM_API_KEY any more."""
    monkeypatch.setattr(chatbot_api, "orchestrator_agent", None)
    app.config["LLM_API_KEY"] = ""
    client = app.test_client()

    assert client.get("/api/v1/tournaments").status_code != 500

    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        client.post("/api/v1/chatbot/chat", data={"user_input": "olá"})


def test_orchestrator_parses_fenced_json():
    from padel_league.core.agents import OrchestratorAgent

    raw = '```json\n{"agent": [{"name": "GenericAnswerAgent", "question": ["q"]}]}\n```'
    assert OrchestratorAgent.parse_tasks(raw)["agent"][0]["name"] == "GenericAnswerAgent"
    assert OrchestratorAgent.parse_tasks('ok {"agent": []} done') == {"agent": []}
    with pytest.raises(ValueError):
        OrchestratorAgent.parse_tasks(None)


def test_every_question_is_logged(app, fake_orchestrator):
    client = app.test_client()
    client.post("/api/v1/chatbot/chat", data={"user_input": "quem lidera?"})

    with app.app_context():
        rows = ChatbotLog.query.all()
        assert len(rows) == 1
        row = rows[0]
        assert row.question == "quem lidera?"
        assert row.answer == "echo: quem lidera?"
        assert row.status == "ok"
        assert row.agent_name == "PadelLeagueAnswerAgent"
        assert json.loads(row.agent_questions) == ["rewritten: quem lidera?"]
        assert json.loads(row.sql_queries)[0]["sql"] == "SELECT 1"
        assert row.session_id
        assert row.duration_ms is not None and row.duration_ms >= 0
        assert row.verdict is None


def test_failures_are_logged_too(app, monkeypatch):
    monkeypatch.setattr(chatbot_api, "orchestrator_agent", FakeOrchestrator(fail=True))
    monkeypatch.setattr(chatbot_api, "conversation_cache", {})
    client = app.test_client()
    client.post("/api/v1/chatbot/chat", data={"user_input": "olá"})

    with app.app_context():
        row = ChatbotLog.query.one()
        assert row.status == "error"
        assert "boom" in row.error
        assert row.answer is None


def test_logging_failure_does_not_break_the_answer(app, fake_orchestrator, monkeypatch):
    def explode(*_args, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(chatbot_api.db.session, "commit", explode)
    client = app.test_client()
    resp = client.post("/api/v1/chatbot/chat", data={"user_input": "olá"})
    assert resp.status_code == 200
    assert resp.get_json()["response"] == "echo: olá"
