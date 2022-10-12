import os
import datetime
import unidecode
from flask import Blueprint, render_template, request , flash

from padel_league.models import Division , Player , Association_PlayerDivision , Match , Association_PlayerMatch , Edition
from padel_league.tools import image_tools , tools

bp = Blueprint('tournaments', __name__,url_prefix='/tournaments')

@bp.route('/', methods=('GET', 'POST'))
def tournaments():
    divisions_to_play = Division.query.filter_by(has_ended=False).order_by(Division.end_date.desc()).all()
    divisions_ended = Division.query.filter_by(has_ended=True).order_by(Division.end_date.desc()).all()
    return render_template('tournaments/tournaments.html',divisions_to_play=divisions_to_play, divisions_ended=divisions_ended)

@bp.route('/<id>', methods=('GET', 'POST'))
@bp.route('/<id>/<recalculate>', methods=('GET', 'POST'))
def tournament(id,recalculate=False):
    if recalculate=='recalculate':
        recalculate = True
    division = Division.query.filter_by(id=id).first()
    division.update_table(recalculate)
    players = [rel.player for rel in division.players_relations]
    return render_template('tournaments/tournament.html',tournament=division,players=players)

@bp.route('/edit/<id>', methods=('GET', 'POST'))
def edit(id):
    return render_template('tournaments/edit_tournament.html')

@bp.route('/create', methods=('GET', 'POST'))
def create():
    if request.method == 'POST':
        name = request.form['name']
        beggining_date= datetime.datetime.strptime(request.form['beggining_date'], '%Y-%m-%d') if request.form['beggining_date'] else None
        picture = request.files.getlist('picture')
        large_picture = request.files.getlist('large_picture')
        edition_id = int(request.form['edition'])
        players_ids = []
        for i in range(8):
            players_ids.append(int(request.form['player_'+str(i)]))

        if len(list(set(players_ids))) != 8:
            error = 'Puseste o mesmo jogador duas vezes'
            flash(error)
            return render_template('tournaments/create_tournament.html',players=players)

        file = picture[0]
        if file.filename != '':
            image_name = name.replace(" ", "").lower()
            image_name = unidecode.unidecode(image_name)
            image_name = '{image_name}.png'.format(image_name=image_name)
            image_tools.save_file(file, image_name)

        file = large_picture[0]
        if file.filename != '':
            large_image_name = name.replace(" ", "").lower()
            large_image_name = unidecode.unidecode(image_name)
            large_image_name = '{image_name}.png'.format(image_name=image_name)
            image_tools.save_file(file, large_image_name)

        tournament = Division(name=name,beginning_datetime=beggining_date,logo_image_path=image_name,large_picture_path=large_image_name,edition_id=edition_id)
        tournament.create()

        for player_id in players_ids:
            association = Association_PlayerDivision(player_id=player_id,division_id=tournament.id)
            association.create()

        matchweeks = tools.create_chamionship_games(players_ids)
        for index,matchweek in enumerate(matchweeks):
            d = datetime.timedelta(days=7*index)
            date = beggining_date + d
            games = tools.get_games_from_matchweek(matchweek)
            for game_index in range(len(games)):
                match = Match(division_id = tournament.id)

                match.date_hour = date
                match.matchweek = index + 1
                match.field = 'Campo 1' if game_index < 3 else 'Campo 2'
                match.played = False
                match.create()

                home_players = games[game_index][0]
                away_players = games[game_index][1]

                for player_id in home_players:
                    association = Association_PlayerMatch(player_id=player_id,match_id=match.id,team='Home')
                    association.create()
                for player_id in away_players:
                    association = Association_PlayerMatch(player_id=player_id,match_id=match.id,team='Away')
                    association.create()
                match.save()
        return render_template('tournaments/tournament.html',tournament=tournament)
        
    players = Player.query.all()
    editions = Edition.query.all()
    return render_template('tournaments/create_tournament.html',players=players,editions=editions)
