from padel_league.sql_db import db
from sqlalchemy.exc import SQLAlchemyError


class SQLClient:
    """
    A safe wrapper around db.session.execute.
    """

    def __init__(self):
        pass

    def run_query(self, sql: str):
        """
        Executes SQL and returns rows as dicts.
        Raises clean errors.
        """
        try:
            result = db.session.execute(sql).mappings().all()
            return [dict(row) for row in result]

        except SQLAlchemyError as e:
            raise RuntimeError(f"Database execution failed: {str(e)}") from e
