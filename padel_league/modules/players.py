import datetime

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
    if request.method == 'POST':
        user = player.user
        user_info = {
            'username': request.form['username'],
            'email': request.form['email']
        }
        player_info = {
            'name': request.form['name'],
            'full_name': request.form['full_name'],
            'prefered_hand': request.form['prefered_hand'],
            'prefered_position': request.form['prefered_position'],
            'height': request.form['height'],
            'birthday': datetime.datetime.strptime(request.form['birth_date'], '%Y-%m-%d') if request.form['birth_date'] else None
        }

        for key in user_info.keys():
            if user_info[key] and getattr(user, key) != user_info[key]:
                setattr(user, key, user_info[key])
        user.save()

        for key in player_info.keys():
            if player_info[key] and getattr(player, key) != player_info[key]:
                setattr(player, key, player_info[key])
        player.save()
        return redirect(url_for('players.player',id = player.id))

    if 'user' not in session.keys() or not session['user'].player_id == player.id:
        session['error'] = "Não podes editar um jogador que não és tu oh burro."
        return redirect(url_for('main.index'))

    return render_template('players/edit_player.html',player=player)