from typing import Any, Dict, List, Optional

from sqlalchemy import text

from padel_league.sql_db import db


class SQLClient:
    """Run the chatbot's SQL and return rows as dicts.

    Queries run on their own connection inside a READ ONLY transaction that is
    always rolled back, so generated SQL can never change data. The schema
    description in core/agents.py names the v2 tables, so only `public` is on
    the search path (the old names in `compat` no longer resolve).
    """

    SEARCH_PATH = "public"

    def __init__(self, session=None):
        self.session = session or db.session

    def _run(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        with db.engine.connect() as conn:
            trans = conn.begin()
            try:
                conn.execute(text("SET TRANSACTION READ ONLY"))
                conn.execute(text(f"SET LOCAL search_path TO {self.SEARCH_PATH}"))
                result = conn.execute(text(query), params or {})
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
