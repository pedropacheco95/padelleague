from flask import Blueprint, redirect, render_template, request, url_for

from padel_league.models import Division

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


@bp.route("/<id>", methods=("GET", "POST"))
@bp.route("/<id>/<recalculate>", methods=("GET", "POST"))
def tournament(id, recalculate=False):
    if recalculate == "recalculate":
        recalculate = True
    division = Division.query.filter_by(id=id).first()
    division.update_table(recalculate)
    players = [rel.player for rel in division.players_relations]
    return render_template(
        "tournaments/tournament.html", tournament=division, players=players
    )


@bp.route("/edit/<id>", methods=("GET", "POST"))
def edit(id):
    return render_template("tournaments/edit_tournament.html")


@bp.route("/delete/<division_id>", methods=("GET", "POST"))
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
