from typing import Any, Dict, List, Optional

from sqlalchemy import text

from padel_league.sql_db import db


class SQLClient:
    """Thin wrapper around SQLAlchemy to run raw SQL and return dicts."""

    def __init__(self, session=None):
        """
        Args:
            session: Optional SQLAlchemy session. Defaults to `db.session`.
        """
        self.session = session or db.session

    def fetch_all(
        self, query: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Run a SELECT query and return all rows as a list of dicts.
        """
        result = self.session.execute(text(query), params or {})
        # mappings() → RowMapping objects (behave like dicts)
        return [dict(row) for row in result.mappings().all()]

    def fetch_one(
        self, query: str, params: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Run a SELECT query and return a single row as a dict (or None).
        """
        result = self.session.execute(text(query), params or {})
        row = result.mappings().first()
        return dict(row) if row else None

    def execute(self, query: str, params: Optional[Dict[str, Any]] = None) -> None:
        """
        Run INSERT/UPDATE/DELETE queries and commit.
        """
        self.session.execute(text(query), params or {})
        result = self.session.execute(text(query), params or {})
        return [dict(row) for row in result.mappings().all()]
