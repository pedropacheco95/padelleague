from flask import Blueprint, redirect, render_template, request, url_for

from padel_league.models import Division
from padel_league.tools import auth_tools

bp = Blueprint("tournaments", __name__, url_prefix="/tournaments")


@bp.route("/", methods=("GET", "POST"))
def tournaments():
    show_all = request.args.get("show_all") == "true"

    divisions_to_play = (
        Division.query.filter_by(has_ended=False).order_by(Division.id.asc()).all()
    )
    divisions_ended = []

    if show_all:
        divisions_to_play = (
            Division.query.filter_by(has_ended=True).order_by(Division.id.desc()).all()
        )

    return render_template(
        "tournaments/tournaments.html",
        divisions_to_play=divisions_to_play,
        divisions_ended=divisions_ended,
        show_all=show_all,
    )


# GET only: the page is read-only, and update_table() would otherwise persist
# a recomputed table for any anonymous POST.
@bp.route("/<id>", methods=["GET"])
@bp.route("/<id>/<recalculate>", methods=["GET"])
def tournament(id, recalculate=False):
    recalculate = recalculate == "recalculate"
    if recalculate:
        # Forced table recompute: admin only.
        denied = auth_tools.admin_required(lambda: None)()
        if denied is not None:
            return denied
    division = Division.query.filter_by(id=id).first()
    division.update_table(recalculate)
    players = [rel.player for rel in division.players_relations]
    return render_template(
        "tournaments/tournament.html", tournament=division, players=players
    )


@bp.route("/edit/<id>", methods=("GET", "POST"))
@auth_tools.admin_required
def edit(id):
    return render_template("tournaments/edit_tournament.html")


@bp.route("/delete/<division_id>", methods=["POST"])
@auth_tools.admin_required
def delete(division_id):
    from flask import flash
    from flask_login import current_user

    from padel_league.services.editions import EditionPlanError, delete_classica_group
    from padel_league.sql_db import db

    try:
        delete_classica_group(int(division_id), actor_user_id=current_user.id)
        db.session.commit()
    except EditionPlanError as exc:
        db.session.rollback()
        flash(str(exc))
    return redirect(url_for("tournaments.tournaments"))
