from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from padel_league.models import League
from padel_league.sql_db import db
from padel_league.tools import auth_tools

bp = Blueprint("editions", __name__, url_prefix="/editions")


@bp.before_request
@auth_tools.admin_required
def before_request():
    pass


@bp.route("/create", methods=("GET", "POST"))
def create():
    if request.method == "POST":
        from padel_league.services.editions import create_classica_competition

        name = request.form["name"]
        league_id = int(request.form["league"])
        create_classica_competition(name, league_id, actor_user_id=current_user.id)
        db.session.commit()
        return redirect(url_for("main.index"))
    leagues = League.query.all()
    return render_template("editions/edition_create.html", leagues=leagues)


@bp.route("/delete/<id>", methods=["POST"])
def delete(id):
    from padel_league.services.editions import EditionPlanError, delete_empty_competition

    try:
        delete_empty_competition(int(id), actor_user_id=current_user.id)
        db.session.commit()
    except EditionPlanError as exc:
        db.session.rollback()
        flash(str(exc))
    return redirect(url_for("main.index"))
