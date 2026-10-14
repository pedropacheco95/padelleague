from flask import Blueprint, redirect, render_template, request, url_for

from padel_league.models import Edition, League
from padel_league.tools import auth_tools

bp = Blueprint("editions", __name__, url_prefix="/editions")


@bp.before_request
@auth_tools.admin_required
def before_request():
    pass


@bp.route("/create", methods=("GET", "POST"))
def create():
    if request.method == "POST":
        name = request.form["name"]
        league_id = int(request.form["league"])
        edicao = Edition(name=name, league_id=league_id)
        edicao.create()
        return redirect(url_for("main.index"))
    leagues = League.query.all()
    return render_template("editions/edition_create.html", leagues=leagues)


@bp.route("/delete/<id>", methods=["POST"])
def delete(id):
    edition = Edition.query.get(id)
    edition.delete()
    return redirect(url_for("main.index"))
