import datetime
import os
import unidecode

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from padel_league.models import League , Player
from padel_league.tools import image_tools

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
            'email': request.form['email'],
            'password': generate_password_hash(request.form['password']) if request.form['password'] else None,
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
            if user_info[key] and getattr(user, key) != user_info[key] and getattr(user, key):
                setattr(user, key, user_info[key])
        user.save()

        for key in player_info.keys():
            if player_info[key] and getattr(player, key) != player_info[key] and getattr(player, key):
                setattr(player, key, player_info[key])
        player.save()

        final_files = request.files.getlist('finalFile')
        for index in range(len(final_files)):
                file = final_files[index]
                if file.filename != '':
                    image_name = str(player.name).replace(" ", "").lower()
                    image_name = unidecode.unidecode(image_name)
                    image_name = '{image_name}_{player_id}.png'.format(image_name=image_name,player_id=player.id)

                    filename = os.path.join('players',image_name)

                    image_tools.save_file(file, filename)
                    image_tools.remove_background(filename)

                    player.picture_path = image_name
                    player.save()
        return redirect(url_for('players.player',id = player.id))

    if 'user' not in session.keys() or not session['user'].player_id == player.id:
        session['error'] = "Não podes editar um jogador que não és tu oh burro."
        return redirect(url_for('main.index'))

    return render_template('players/edit_player.html',player=player)