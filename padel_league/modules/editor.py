from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from padel_league.models import (
    MODELS,
    Association_PlayerDivision,
    Association_PlayerMatch,
    Backend_App,
    Division,
    Player,
)
from padel_league.sql_db import db
from padel_league.tools import auth_tools

bp = Blueprint("editor", __name__, url_prefix="/editor")


@bp.before_request
@auth_tools.admin_required
def before_request():
    pass


@bp.route("/", methods=("GET", "POST"))
def index():
    apps = Backend_App.query.all()
    return render_template("editor/index.html", page="editor_index", apps=apps)


@bp.route("/display/<model>", methods=("GET", "POST"))
def display_all(model):
    page_num = request.args.get("page", 1, type=int)
    per_page = 100

    page = f"editor_{model}_all"
    model = MODELS[model]
    empty_instance = model()
    data = empty_instance.get_display_all_data(page=page_num, per_page=per_page)

    return render_template("editor/display_all.html", page=page, data=data)


@bp.route("/display/<model>/<id>", methods=("GET", "POST"))
def display(model, id):
    page = f"editor_{model}"
    model = MODELS[model]
    instance = model.query.filter_by(id=id).first()
    data = instance.get_display_data()
    return render_template("editor/display.html", page=page, data=data)


@bp.route("/create/<model>", methods=("GET", "POST"))
def create(model):
    page = f"editor_{model}_create"
    model_name = model
    model = MODELS[model_name]
    empty_instance = model()
    form = empty_instance.get_create_form()
    if request.method == "POST":
        values = form.set_values(request)
        empty_instance.update_with_dict(values)
        empty_instance.create()
        return redirect(url_for("editor.display_all", model=model_name))
    data = empty_instance.get_create_data(form)
    return render_template("editor/create.html", page=page, data=data)


# ---------------------------------------------------------------------------
# Division admin actions
# ---------------------------------------------------------------------------


def _swap_player_in_division(division, player_a, player_b):
    """Replace player_a with player_b in the division roster and in every
    Association_PlayerMatch row for matches that belong to the division.

    Uses db.session.add/delete + flush; does NOT commit, does NOT call
    update_table. Caller is responsible for committing the session and
    invoking update_table afterwards.
    """
    pd_row = Association_PlayerDivision.query.filter_by(
        division_id=division.id, player_id=player_a.id
    ).first()
    if pd_row is None:
        raise ValueError("Jogador A não pertence à divisão.")

    place = pd_row.place
    db.session.delete(pd_row)
    db.session.flush()

    new_pd = Association_PlayerDivision(
        player_id=player_b.id,
        division_id=division.id,
        place=place,
    )
    db.session.add(new_pd)
    db.session.flush()

    match_ids = [m.id for m in division.matches]
    if match_ids:
        pm_rows = Association_PlayerMatch.query.filter(
            Association_PlayerMatch.player_id == player_a.id,
            Association_PlayerMatch.match_id.in_(match_ids),
        ).all()
        for row in pm_rows:
            team = row.team
            match_id = row.match_id
            db.session.delete(row)
            db.session.flush()
            new_pm = Association_PlayerMatch(
                player_id=player_b.id,
                match_id=match_id,
                team=team,
            )
            db.session.add(new_pm)
            db.session.flush()

    return len(match_ids)


def _readd_player_to_matchweek(division, player, partner, matchweek):
    """For every match in the given matchweek of the division, add a
    players_in_match row binding `player` to the same team as `partner`.

    Skips matches where partner is not present or where player is already
    present. Uses db.session.add + flush only; does NOT commit.
    """
    results = {
        "reinserted": [],
        "skipped_no_partner": [],
        "skipped_already_present": [],
    }

    matches = [m for m in division.matches if int(m.matchweek) == int(matchweek)]
    for match in matches:
        partner_rel = Association_PlayerMatch.query.filter_by(
            match_id=match.id, player_id=partner.id
        ).first()
        if not partner_rel:
            results["skipped_no_partner"].append(match.id)
            continue

        existing = Association_PlayerMatch.query.filter_by(
            match_id=match.id, player_id=player.id
        ).first()
        if existing:
            results["skipped_already_present"].append(match.id)
            continue

        new_rel = Association_PlayerMatch(
            player_id=player.id,
            match_id=match.id,
            team=partner_rel.team,
        )
        db.session.add(new_rel)
        db.session.flush()
        results["reinserted"].append(match.id)

    return results


def _division_roster(division):
    """Sorted list of Player instances currently registered in the division."""
    players = [rel.player for rel in division.players_relations if rel.player]
    players.sort(key=lambda p: (p.name or "").lower())
    return players


def _division_matchweeks(division):
    """Sorted distinct int matchweeks among the division's matches."""
    weeks = set()
    for m in division.matches:
        try:
            weeks.add(int(m.matchweek))
        except (TypeError, ValueError):
            continue
    return sorted(weeks)


@bp.route(
    "/division/<int:division_id>/replace-player", methods=("GET", "POST")
)
def division_replace_player(division_id):
    division = Division.query.get_or_404(division_id)
    current_players = _division_roster(division)
    current_ids = {p.id for p in current_players}
    available_players = [
        p
        for p in Player.query.order_by(Player.name.asc()).all()
        if p.id not in current_ids
    ]

    def render_form():
        return render_template(
            "editor/division_actions/replace_player.html",
            page=f"editor_Division_{division.id}_replace_player",
            division=division,
            current_players=current_players,
            available_players=available_players,
        )

    if request.method == "GET":
        return render_form()

    # POST
    try:
        player_a_id = int(request.form.get("player_a_id") or 0)
        player_b_id = int(request.form.get("player_b_id") or 0)
    except ValueError:
        flash("Identificadores de jogador inválidos.", "error")
        return render_form()

    confirm_has_ended = request.form.get("confirm_has_ended") == "1"

    if division.has_ended and not confirm_has_ended:
        flash(
            "A divisão está encerrada. Marca a confirmação para prosseguir.",
            "error",
        )
        return render_form()

    if not player_a_id or not player_b_id:
        flash("Selecciona os dois jogadores.", "error")
        return render_form()

    if player_a_id == player_b_id:
        flash("O jogador a sair e o novo jogador têm de ser diferentes.", "error")
        return render_form()

    player_a = Player.query.get(player_a_id)
    player_b = Player.query.get(player_b_id)
    if not player_a or not player_b:
        flash("Jogador não encontrado.", "error")
        return render_form()

    if player_a.id not in current_ids:
        flash("O jogador a sair não pertence a esta divisão.", "error")
        return render_form()

    if player_b.id in current_ids:
        flash("O novo jogador já pertence a esta divisão.", "error")
        return render_form()

    try:
        match_count = _swap_player_in_division(division, player_a, player_b)
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception(
            "[admin-action] replace_player failed division=%s a=%s b=%s: %s",
            division.id,
            player_a.id,
            player_b.id,
            exc,
        )
        flash(f"Falha ao substituir jogador: {exc}", "error")
        return render_form()

    try:
        division.update_table(force_update=True)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception(
            "[admin-action] replace_player update_table failed division=%s: %s",
            division.id,
            exc,
        )

    current_app.logger.info(
        "[admin-action] replace_player division=%s a=%s b=%s matches=%s",
        division.id,
        player_a.id,
        player_b.id,
        match_count,
    )

    flash("Jogador substituído com sucesso.", "success")
    return redirect(url_for("editor.display", model="Division", id=division.id))


@bp.route(
    "/division/<int:division_id>/readd-player", methods=("GET", "POST")
)
def division_readd_player(division_id):
    division = Division.query.get_or_404(division_id)
    roster_players = _division_roster(division)
    roster_ids = {p.id for p in roster_players}
    matchweeks = _division_matchweeks(division)

    def render_form():
        return render_template(
            "editor/division_actions/readd_player.html",
            page=f"editor_Division_{division.id}_readd_player",
            division=division,
            roster_players=roster_players,
            matchweeks=matchweeks,
        )

    if request.method == "GET":
        return render_form()

    # POST
    try:
        player_id = int(request.form.get("player_id") or 0)
        partner_id = int(request.form.get("partner_id") or 0)
        matchweek = int(request.form.get("matchweek") or 0)
    except ValueError:
        flash("Valores inválidos no formulário.", "error")
        return render_form()

    confirm_has_ended = request.form.get("confirm_has_ended") == "1"

    if division.has_ended and not confirm_has_ended:
        flash(
            "A divisão está encerrada. Marca a confirmação para prosseguir.",
            "error",
        )
        return render_form()

    if not player_id or not partner_id or not matchweek:
        flash("Preenche todos os campos.", "error")
        return render_form()

    if player_id == partner_id:
        flash("O jogador e o parceiro têm de ser diferentes.", "error")
        return render_form()

    if matchweek not in matchweeks:
        flash("Jornada inválida para esta divisão.", "error")
        return render_form()

    if player_id not in roster_ids or partner_id not in roster_ids:
        flash("Jogador ou parceiro não pertence à divisão.", "error")
        return render_form()

    player = Player.query.get(player_id)
    partner = Player.query.get(partner_id)
    if not player or not partner:
        flash("Jogador não encontrado.", "error")
        return render_form()

    try:
        results = _readd_player_to_matchweek(
            division, player, partner, matchweek
        )
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception(
            "[admin-action] readd_player failed division=%s player=%s matchweek=%s: %s",
            division.id,
            player.id,
            matchweek,
            exc,
        )
        flash(f"Falha ao readicionar jogador: {exc}", "error")
        return render_form()

    try:
        division.update_table(force_update=True)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception(
            "[admin-action] readd_player update_table failed division=%s: %s",
            division.id,
            exc,
        )

    current_app.logger.info(
        "[admin-action] readd_player division=%s player=%s matchweek=%s results=%s",
        division.id,
        player.id,
        matchweek,
        results,
    )

    flash(
        "Readicionado em {n} jogos. {m} ignorados sem parceiro. "
        "{k} ignorados (jogador já presente).".format(
            n=len(results["reinserted"]),
            m=len(results["skipped_no_partner"]),
            k=len(results["skipped_already_present"]),
        ),
        "success",
    )
    return redirect(url_for("editor.display", model="Division", id=division.id))
