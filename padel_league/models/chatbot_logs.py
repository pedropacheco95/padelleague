from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from padel_league import model
from padel_league.sql_db import db
from padel_league.tools.input_tools import Block, Field, Form


class ChatbotLog(db.Model, model.Model):
    """
    One row per question asked to the chatbot: what was asked, how the
    orchestrator routed it, which SQL ran, and what was answered.

    `verdict`, `expected_answer` and `notes` are left empty by the app and are
    meant to be filled in by hand (editor) to build a ground-truth set.
    """

    __tablename__ = "chatbot_logs"
    __table_args__ = {"extend_existing": True}

    page_title = "Chatbot Logs"
    model_name = "ChatbotLog"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session_id = Column(String(64))
    question = Column(Text, nullable=False)
    agent_name = Column(String(64))
    agent_questions = Column(Text)  # JSON list of rewritten questions
    sql_queries = Column(Text)  # JSON list of {question, sql, row_count, error}
    answer = Column(Text)
    status = Column(String(16), nullable=False, default="ok")  # ok | error
    error = Column(Text)
    duration_ms = Column(Integer)

    # Ground-truth labelling, filled in by hand later.
    verdict = Column(String(16))  # correct | wrong | unclear
    expected_answer = Column(Text)
    notes = Column(Text)

    @property
    def name(self):
        return (self.question or "")[:80]

    def display_all_info(self):
        searchable_column = {"field": "question", "label": "Question"}
        table_columns = [
            {"field": "created_at", "label": "When"},
            searchable_column,
            {"field": "agent_name", "label": "Agent"},
            {"field": "answer", "label": "Answer"},
            {"field": "status", "label": "Status"},
            {"field": "duration_ms", "label": "ms"},
            {"field": "verdict", "label": "Verdict"},
        ]
        return searchable_column, table_columns

    def get_create_form(self):
        def get_field(name, label, type, required=False):
            return Field(
                instance_id=getattr(self, "id", None),
                model=self.model_name,
                name=name,
                label=label,
                type=type,
                required=required,
            )

        form = Form()
        fields = [
            get_field("created_at", "When", "DateTime"),
            get_field("session_id", "Session", "Text"),
            get_field("question", "Question", "Text", required=True),
            get_field("agent_name", "Agent", "Text"),
            get_field("agent_questions", "Rewritten questions (JSON)", "Text"),
            get_field("sql_queries", "SQL (JSON)", "Text"),
            get_field("answer", "Answer", "Text"),
            get_field("status", "Status", "Text"),
            get_field("error", "Error", "Text"),
            get_field("duration_ms", "Duration (ms)", "Integer"),
            get_field("verdict", "Verdict (correct/wrong/unclear)", "Text"),
            get_field("expected_answer", "Expected answer", "Text"),
            get_field("notes", "Notes", "Text"),
        ]
        form.add_block(Block("info_block", fields))
        return form
