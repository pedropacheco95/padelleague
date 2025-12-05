from flask import Blueprint, request, session, jsonify, current_app
from padel_league.core.agents import (
    DataAgent,
    GenericAnswerAgent,
    PadelLeagueAnswerAgent,
    OrchestratorAgent,
)
from padel_league.core.services import SQLClient
import uuid

bp = Blueprint("chatbot_api", __name__, url_prefix="/chatbot_api")

llm_client = None
data_agent = None
generic_answer_agent = None
padelleague_answer_agent = None
orchestrator_agent = None
conversation_cache = {}


def init_llm():
    """
    Initializes the global LLM model using the Flask app's configuration.
    """
    global llm_client
    global data_agent
    global generic_answer_agent
    global padelleague_answer_agent
    global orchestrator_agent
    global sql_client
    if orchestrator_agent is None:

        api_key = current_app.config["LLM_API_KEY"]

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


@bp.before_app_request
def initialize_globals():
    """
    Initializes global objects before handling the first request.
    """
    init_llm()


@bp.before_request
def load_conversation():
    """
    Ensures each session has a unique conversation.

    If the session doesn't have a conversation_id, one is created and a new
    LLMConversation is stored in a global cache. On subsequent requests, the
    conversation is retrieved from the cache using the session's conversation_id.
    """
    if "conversation_id" not in session:
        conversation_id = str(uuid.uuid4())
        session["conversation_id"] = conversation_id
        conversation_cache[conversation_id] = orchestrator_agent.conversation
    else:
        conversation_id = session["conversation_id"]
        if conversation_id not in conversation_cache:
            conversation_cache[conversation_id] = orchestrator_agent.conversation


@bp.route("/chat", methods=["POST"])
def chat():
    """
    Handles chat requests by retrieving the per-user conversation from the global
    cache, appending the user's input, generating a response using the global LLM,
    and then updating the conversation.
    """
    user_input = request.form.get("user_input")
    if not user_input:
        return jsonify({"error": "No user_input provided"}), 400

    conversation_id = session.get("conversation_id")
    if not conversation_id:
        return jsonify({"error": "Session not initialized properly"}), 400

    response = orchestrator_agent.run(user_input)

    return jsonify({"response": response})
