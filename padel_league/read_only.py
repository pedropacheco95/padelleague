"""GET requests never write to the database.

Several old read paths (standings, shuffle stats, ranking) recompute values on
the ORM objects and save them. Under v2 they keep computing in memory, so the
response is unchanged, but nothing is persisted:

- `Model.save()` skips the commit (old read paths save recomputed values),
- `Model.create()` / `delete()` raise: a GET that deletes or creates is a bug,
- autoflush is off, so pending changes are never sent,
- any other commit attempt raises, so a missed write path fails loudly,
- the session is rolled back when the request ends.

Endpoints that must write on GET are listed in `_writes_on_get`.
"""

from flask import current_app, has_app_context, request
from sqlalchemy import event

from .sql_db import db

# Endpoints that legitimately write on GET.
WRITE_ON_GET_ENDPOINTS = {
    "sponsors.sponsor_click",  # records the click, then redirects
}


def _writes_on_get():
    if request.endpoint in WRITE_ON_GET_ENDPOINTS:
        return True
    # Legacy admin action /players/ranking/recalculate recomputes the stored ranking.
    return request.endpoint == "players.players" and (request.view_args or {}).get("recalculate") == "recalculate"

READ_ONLY_KEY = "read_only_request"


def is_read_only():
    return bool(db.session.info.get(READ_ONLY_KEY))


class WriteDuringReadOnlyRequest(RuntimeError):
    pass


def init_app(app):
    init_compat_guard()

    @app.before_request
    def _enter_read_only():
        if request.method in ("GET", "HEAD") and not _writes_on_get():
            db.session.info[READ_ONLY_KEY] = True
            db.session.autoflush = False

    @app.teardown_request
    def _leave_read_only(exc=None):
        if db.session.info.pop(READ_ONLY_KEY, False):
            db.session.rollback()
            db.session.autoflush = True

    @event.listens_for(db.session, "before_commit")
    def _refuse_commit(session):
        if session.info.get(READ_ONLY_KEY):
            raise WriteDuringReadOnlyRequest(
                f"{request.method} {request.path} tried to commit; GET requests are read-only"
            )


class CompatWriteError(RuntimeError):
    """A write path still targets a pre-v2 model, which maps onto a read-only view."""


def _is_compat(obj):
    table = getattr(obj, "__table__", None)
    return table is not None and table.schema == "compat"


def init_compat_guard():
    @event.listens_for(db.session, "before_flush")
    def _refuse_compat_writes(session, flush_context, instances):
        # Unit tests of the old models run on SQLite, where compat is a real schema.
        if has_app_context() and current_app.config.get("ALLOW_COMPAT_WRITES"):
            return
        offenders = [o for o in list(session.new) + list(session.dirty) + list(session.deleted) if _is_compat(o)]
        # Only objects with real column changes count; touched relationships alone do not.
        offenders = [o for o in offenders if o in session.new or o in session.deleted or session.is_modified(o)]
        if offenders:
            names = sorted({o.__class__.__name__ for o in offenders})
            raise CompatWriteError(
                f"{', '.join(names)} are pre-v2 models over read-only views (schema compat). "
                "This write path has not been moved to the v2 models yet; see docs/v2/PLAN.md."
            )
