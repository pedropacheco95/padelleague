from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from padel_league.models import (
    MODELS,
    Backend_App,
    Division,
    Player,
)
from padel_league.models.v2 import (
    Absence,
    Award,
    CompetitionGroup,
    CompetitionMatch,
    Entry,
    GroupMember,
    MatchParticipant,
    Round,
)
from padel_league.modules.compat_guard import compat_write_message, is_compat_model
from padel_league.services.results import _audit, _match_state, unfreeze_group_standings
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
        if is_compat_model(model):
            flash(compat_write_message(model), "error")
            return redirect(url_for("editor.display_all", model=model_name))
        values = form.set_values(request)
        empty_instance.update_with_dict(values)
        empty_instance.create()
        return redirect(url_for("editor.display_all", model=model_name))
    data = empty_instance.get_create_data(form)
    return render_template("editor/create.html", page=page, data=data)


# ---------------------------------------------------------------------------
# Division admin actions
# ---------------------------------------------------------------------------


def _member_of(group, player_id):
    return (
        GroupMember.query.join(Entry, GroupMember.entry_id == Entry.id)
        .filter(GroupMember.group_id == group.id, Entry.player_id == player_id)
        .first()
    )


def _swap_player_in_division(division, player_a, player_b, actor_user_id=None):
    """Replace player_a with player_b in the group and in every match of it.

    B takes A's group member row (same seed and position), A's slots in every
    match of the group (played or not), A's recorded absences in the group's
    rounds and A's awards for the group; A's entry is kept as "replaced".
    Frozen standings are unfrozen so they are recomputed live, as the old
    update_table did. Flushes only; the caller commits.
    """
    group = db.session.get(CompetitionGroup, division.id)
    member = _member_of(group, player_a.id) if group else None
    if member is None:
        raise ValueError("Jogador A não pertence à divisão.")
    entry_a = member.entry
    competition_id = entry_a.competition_id

    entry_b = Entry.query.filter_by(competition_id=competition_id, player_id=player_b.id).first()
    if entry_b is None:
        entry_b = Entry(competition_id=competition_id, player_id=player_b.id)
        db.session.add(entry_b)
        db.session.flush()
    entry_b.status = "active"

    matches = CompetitionMatch.query.filter_by(group_id=group.id).all()
    clash = [m.id for m in matches if any(p.player_id == player_b.id for p in m.participants)]
    if clash:
        raise ValueError(f"O novo jogador já joga (como substituto) nos jogos {clash}.")

    for match in matches:
        participant = next((p for p in match.participants if p.player_id == player_a.id), None)
        if participant is None:
            continue
        before = _match_state(match)
        # A new row, as the old code inserted one: B is listed after the partner.
        side, slot, role = participant.side, participant.slot, participant.role
        match.participants.remove(participant)
        db.session.delete(participant)
        db.session.flush()
        match.participants.append(
            MatchParticipant(
                side=side, slot=slot, role=role, player_id=player_b.id,
                entry_id=entry_b.id if role == "member" else None,
            )
        )
        db.session.flush()
        _audit(actor_user_id, "match", match.id, "replace_player", before, _match_state(match))

    round_ids = [r.id for r in Round.query.filter_by(stage_id=group.stage_id)]
    if round_ids:
        Absence.query.filter(Absence.entry_id == entry_a.id, Absence.round_id.in_(round_ids)).update(
            {"entry_id": entry_b.id}, synchronize_session=False
        )
    Award.query.filter_by(group_id=group.id, entry_id=entry_a.id).update(
        {"entry_id": entry_b.id, "player_id": player_b.id}, synchronize_session=False
    )

    unfreeze_group_standings(group.id)
    member.entry_id = entry_b.id
    entry_a.status = "replaced"
    group.standings_up_to_date = True
    _audit(
        actor_user_id, "group", group.id, "replace_player",
        {"player_id": player_a.id, "entry_id": entry_a.id},
        {"player_id": player_b.id, "entry_id": entry_b.id},
    )
    db.session.flush()
    return len(matches)


def _readd_player_to_matchweek(division, player, partner, matchweek, actor_user_id=None):
    """Put ``player`` back next to ``partner`` in every match of a jornada.

    The undo of an absence: skips matches where the partner is not present or
    the player already is; a substitute standing in on the partner's side
    gives their slot back. Clears the recorded absence for that round.
    Flushes only; the caller commits.
    """
    results = {
        "reinserted": [],
        "skipped_no_partner": [],
        "skipped_already_present": [],
    }
    group = db.session.get(CompetitionGroup, division.id)
    member = _member_of(group, player.id)
    matches = (
        CompetitionMatch.query.filter_by(group_id=group.id)
        .join(CompetitionMatch.round)
        .filter(Round.number == int(matchweek))
        .order_by(CompetitionMatch.id)
        .all()
    )
    played_affected = False
    for match in matches:
        partner_rel = next((p for p in match.participants if p.player_id == partner.id), None)
        if partner_rel is None:
            results["skipped_no_partner"].append(match.id)
            continue
        if any(p.player_id == player.id for p in match.participants):
            results["skipped_already_present"].append(match.id)
            continue

        before = _match_state(match)
        side = [p for p in match.participants if p.side == partner_rel.side]
        stand_in = next((p for p in side if p.role == "substitute"), None)
        if stand_in is not None:
            slot = stand_in.slot
            match.participants.remove(stand_in)
            db.session.delete(stand_in)
            db.session.flush()
        else:
            taken = {p.slot for p in side}
            free = [s for s in (1, 2) if s not in taken]
            if not free:
                results["skipped_already_present"].append(match.id)
                continue
            slot = free[0]
        match.participants.append(
            MatchParticipant(side=partner_rel.side, slot=slot, role="member", entry_id=member.entry_id, player_id=player.id)
        )
        db.session.flush()
        played_affected = played_affected or match.played
        _audit(actor_user_id, "match", match.id, "readd_player", before, _match_state(match))
        results["reinserted"].append(match.id)

    if results["reinserted"]:
        Absence.query.filter_by(entry_id=member.entry_id, round_id=matches[0].round_id).delete(synchronize_session=False)
    if played_affected:
        unfreeze_group_standings(group.id)
    return results


def _actor_id():
    from flask_login import current_user

    return current_user.id if current_user.is_authenticated else None


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
        match_count = _swap_player_in_division(division, player_a, player_b, actor_user_id=_actor_id())
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
            division, player, partner, matchweek, actor_user_id=_actor_id()
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
