import json
import logging
import time
import uuid

from flask import Blueprint, current_app, jsonify, request, session

from padel_league.core.agents import (
    DataAgent,
    GenericAnswerAgent,
    OrchestratorAgent,
    PadelLeagueAnswerAgent,
)
from padel_league.core.services import SQLClient
from padel_league.models import ChatbotLog
from padel_league.sql_db import db

bp = Blueprint("chatbot_api", __name__, url_prefix="/api/v1/chatbot")

llm_client = None
data_agent = None
generic_answer_agent = None
padelleague_answer_agent = None
orchestrator_agent = None
sql_client = None

# conversation_id (stored in the Flask session cookie) -> LLMConversation.
# Each visitor gets their own history so questions from one player never
# leak into another player's context.
conversation_cache = {}

FALLBACK_ANSWER = (
    "Não consegui responder agora. Tenta outra vez daqui a bocado."
)


def init_llm():
    """
    Lazily builds the agent graph the first time a chatbot route is hit.
    Reads the OpenAI key from the Flask config (LLM_API_KEY).
    """
    global llm_client
    global data_agent
    global generic_answer_agent
    global padelleague_answer_agent
    global orchestrator_agent
    global sql_client
    if orchestrator_agent is not None:
        return

    api_key = current_app.config.get("LLM_API_KEY", "")
    if not api_key:
        raise RuntimeError("LLM_API_KEY is not configured")

    sql_client = SQLClient()
    data_agent = DataAgent(api_key=api_key, sql_client=sql_client)
    generic_answer_agent = GenericAnswerAgent(api_key=api_key)
    padelleague_answer_agent = PadelLeagueAnswerAgent(
        api_key=api_key, data_agent=data_agent
    )
    orchestrator_agent = OrchestratorAgent(
        api_key=api_key,
        agents=[generic_answer_agent, padelleague_answer_agent],
    )


@bp.before_request
def initialize_globals():
    """
    Builds the agents on first use. Scoped to this blueprint so the rest of
    the app never depends on an LLM key being present.
    """
    init_llm()


def get_conversation():
    """
    Returns the LLMConversation for the current session, creating both the
    session id and the conversation on first contact.
    """
    conversation_id = session.get("conversation_id")
    if not conversation_id:
        conversation_id = str(uuid.uuid4())
        session["conversation_id"] = conversation_id

    conversation = conversation_cache.get(conversation_id)
    if conversation is None:
        conversation = orchestrator_agent.new_conversation()
        conversation_cache[conversation_id] = conversation
    return conversation


@bp.route("/chat", methods=["POST"])
def chat():
    """
    Appends the user's message to their own conversation, runs the
    orchestrator and returns the answer as JSON.
    """
    user_input = (request.form.get("user_input") or "").strip()
    if not user_input:
        payload = request.get_json(silent=True) or {}
        user_input = (payload.get("user_input") or "").strip()
    if not user_input:
        return jsonify({"error": "No user_input provided"}), 400

    conversation = get_conversation()
    trace = {}
    started = time.monotonic()

    try:
        response = orchestrator_agent.run(
            user_input, conversation=conversation, trace=trace
        )
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace to the chat UI
        logging.exception("Chatbot failed to answer: %r", user_input)
        log_question(user_input, trace, started, answer=None, error=repr(exc))
        return jsonify({"response": FALLBACK_ANSWER, "error": "llm_failure"}), 502

    if not response:
        log_question(user_input, trace, started, answer=None, error="empty_answer")
        return jsonify({"response": FALLBACK_ANSWER, "error": "empty_answer"}), 502

    log_question(user_input, trace, started, answer=response)
    return jsonify({"response": response})


def log_question(question, trace, started, answer=None, error=None):
    """
    Persists one ChatbotLog row. Never raises: a logging problem must not
    turn a good answer into an error for the user.
    """
    try:
        row = ChatbotLog(
            session_id=session.get("conversation_id"),
            question=question,
            agent_name=trace.get("agent_name"),
            agent_questions=_json(trace.get("agent_questions")),
            sql_queries=_json(trace.get("sql_queries")),
            answer=answer,
            status="ok" if error is None else "error",
            error=error,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        db.session.add(row)
        db.session.commit()
    except Exception:  # noqa: BLE001
        logging.exception("Could not write chatbot log")
        try:
            db.session.rollback()
        except Exception:  # noqa: BLE001
            pass


def _json(value):
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


@bp.route("/reset", methods=["POST"])
def reset():
    """Forgets the current session's conversation."""
    conversation_id = session.pop("conversation_id", None)
    if conversation_id:
        conversation_cache.pop(conversation_id, None)
    return jsonify({"ok": True})
