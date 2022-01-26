from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from padel_league.models import League , Player

bp = Blueprint('players', __name__,url_prefix='/players')

@bp.route('/', methods=('GET', 'POST'))
def players():
    #This should be changed if more leagues are added
    players = League.query.first().players_rankings_position()
    return render_template('players/players.html',players=players)

@bp.route('/<id>', methods=('GET', 'POST'))
def player(id):
    player = Player.query.filter_by(id=id).first()
    return render_template('players/player.html',player=player)

@bp.route('/edit/<id>', methods=('GET', 'POST'))
def edit(id):
    return render_template('players/edit_player.html')