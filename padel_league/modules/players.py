from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from padel_league.models import League , Player

bp = Blueprint('players', __name__,url_prefix='/players')

@bp.route('/ranking', methods=('GET', 'POST'))
@bp.route('/ranking/<recalculate>', methods=('GET', 'POST'))
def players(recalculate=None):
    league = League.query.first()
    if recalculate=='recalculate':
        league.update_rankings()
    #This should be changed if more leagues are added
    players = league.players_rankings_position()
    return render_template('players/players.html',players=players)

@bp.route('/<id>', methods=('GET', 'POST'))
def player(id):
    player = Player.query.filter_by(id=id).first()
    return render_template('players/player.html',player=player)

@bp.route('/edit/<id>', methods=('GET', 'POST'))
def edit(id):
    player = Player.query.filter_by(id=id).first()
    return render_template('players/edit_player.html',player=player)