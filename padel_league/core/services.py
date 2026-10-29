"""The chatbot's database access.

Generated SQL is untrusted input. Three layers keep it harmless:

1. `check_select_only` accepts one SELECT (or WITH ... SELECT) and nothing
   else, and refuses credentials, archived schemas and the catalog by name.
2. The query runs on its own connection inside a READ ONLY transaction with a
   statement timeout, and that transaction is always rolled back.
3. When `CHATBOT_DATABASE_URI` is configured the connection uses a dedicated
   read-only database role (docs/security/chatbot_readonly_role.sql) instead
   of the application's user.
"""

import re
from typing import Any, Dict, List, Optional

from flask import current_app, has_app_context
from sqlalchemy import create_engine, text

from padel_league.sql_db import db

DEFAULT_STATEMENT_TIMEOUT_MS = 5000


class UnsafeSQLError(ValueError):
    """The chatbot produced SQL that is not one read-only SELECT over the public tables."""


_COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_STARTS_LIKE_A_SELECT = re.compile(r"^(select|with)\b", re.I)
# Credentials, archived data and the catalog are never the chatbot's business.
_FORBIDDEN_NAMES = re.compile(
    r"\b(users|password|generated_code|legacy|compat|pg_catalog|information_schema|pg_[a-z_]+|dblink|lo_[a-z_]+)\b",
    re.I,
)
# Keywords no read-only SELECT needs (CTEs can hide DML; SELECT INTO creates a table).
_WRITE_KEYWORDS = re.compile(
    r"\b(insert|update|delete|merge|truncate|drop|alter|create|grant|revoke|into|lock|copy)\b",
    re.I,
)


def check_select_only(sql: Optional[str]) -> str:
    """Return the statement stripped of comments and the trailing semicolon, or raise UnsafeSQLError."""
    body = _COMMENTS.sub(" ", sql or "").strip().rstrip(";").strip()
    if not body:
        raise UnsafeSQLError("empty SQL")
    if ";" in body:
        raise UnsafeSQLError("one statement only")
    if not _STARTS_LIKE_A_SELECT.match(body):
        raise UnsafeSQLError("only SELECT queries are allowed")
    hit = _FORBIDDEN_NAMES.search(body)
    if hit:
        raise UnsafeSQLError(f"'{hit.group(0)}' is off limits to the chatbot")
    hit = _WRITE_KEYWORDS.search(body)
    if hit:
        raise UnsafeSQLError(f"'{hit.group(0).upper()}' is not allowed in a chatbot query")
    return body


class SQLClient:
    """Run the chatbot's SQL and return rows as dicts.

    Only `public` is on the search path: the schema description in
    core/agents.py names the v2 tables, so the old names in `compat` must not
    resolve.
    """

    SEARCH_PATH = "public"

    def __init__(self, session=None, statement_timeout_ms: Optional[int] = None):
        self.session = session or db.session  # kept for callers that still pass one
        self.statement_timeout_ms = statement_timeout_ms
        self._own_engine = None
        self._own_uri = None

    def _timeout_ms(self) -> int:
        if self.statement_timeout_ms is not None:
            return int(self.statement_timeout_ms)
        if has_app_context():
            return int(current_app.config.get("CHATBOT_STATEMENT_TIMEOUT_MS") or DEFAULT_STATEMENT_TIMEOUT_MS)
        return DEFAULT_STATEMENT_TIMEOUT_MS

    def _engine(self):
        uri = current_app.config.get("CHATBOT_DATABASE_URI") if has_app_context() else None
        if not uri:
            return db.engine
        if self._own_engine is None or self._own_uri != uri:
            self._own_engine = create_engine(uri, pool_pre_ping=True, pool_size=2, max_overflow=2)
            self._own_uri = uri
        return self._own_engine

    def _run(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        body = check_select_only(query)
        with self._engine().connect() as conn:
            trans = conn.begin()
            try:
                conn.execute(text("SET TRANSACTION READ ONLY"))
                conn.execute(text(f"SET LOCAL statement_timeout = {self._timeout_ms()}"))
                conn.execute(text(f"SET LOCAL search_path TO {self.SEARCH_PATH}"))
                result = conn.execute(text(body), params or {})
                rows = [dict(row) for row in result.mappings().all()] if result.returns_rows else []
            finally:
                trans.rollback()
        return rows

    def fetch_all(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return self._run(query, params)

    def fetch_one(self, query: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        rows = self._run(query, params)
        return rows[0] if rows else None

    def execute(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return self._run(query, params)
