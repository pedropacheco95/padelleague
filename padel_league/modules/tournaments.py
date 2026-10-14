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
    division = Division.query.filter_by(id=division_id).first()
    for match in division.matches:
        for association in match.players_relations:
            association.delete()
        match.delete()
    for association in division.players_relations:
        association.delete()
    division.delete()
    return redirect(url_for("tournaments.tournaments"))
