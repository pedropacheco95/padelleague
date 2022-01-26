import functools
import os
import datetime

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from padel_league.sql_db import db
from padel_league.models import User , Match , League , Edition , Division , Player , Association_PlayerDivision , Association_PlayerMatch

bp = Blueprint('uploads', __name__, url_prefix='/uploads')

@bp.route('/upload_csv_to_db', methods=['GET', 'POST'])
def upload_csv_to_db():

    leagues = dict()
    f = open(os.path.join('padel_league/static/data', 'leagues.csv'))
    for line in f:
        line = line.strip('\n')
        columns = line.split(",")
        if columns[0] != 'id':
            name = columns[1]
            liga = League(name=name)
            liga.create()
            leagues[name] = liga
    f.close()

    editions = dict()
    f = open(os.path.join('padel_league/static/data', 'editions.csv'))
    for line in f:
        line = line.strip('\n')
        columns = line.split(",")
        if columns[0] != 'id':
            name = columns[1]
            league = leagues[columns[2]]
            edicao = Edition(name=columns[1],league_id=league.id)
            edicao.create()
            editions[name] = edicao
    f.close()

    divisions = dict()
    f = open(os.path.join('padel_league/static/data', 'divisions.csv'))
    for line in f:
        line = line.strip('\n')
        columns = line.split(",")
        if columns[0] != 'id':
            name = columns[1]
            beginning_datetime = datetime.datetime.strptime(columns[2], '%d/%m/%Y %H:%M') if columns[2] else None
            end_date = datetime.datetime.strptime(columns[3], '%d/%m/%Y') if columns[3] else None
            logo_image_path = columns[4]
            large_picture_path = columns[5]
            has_ended = True if columns[6] == 'True' else False
            rating = int(columns[7])
            edition = editions[columns[8]]
            
            division = Division(name=name,
            beginning_datetime=beginning_datetime,
            end_date = end_date,
            logo_image_path=logo_image_path,
            large_picture_path=large_picture_path,
            has_ended=has_ended,
            rating=rating,
            edition_id = edition.id)

            division.create()
            divisions[name] = division
    f.close()

    players = dict()
    f = open(os.path.join('padel_league/static/data', 'players.csv'))
    for line in f:
        line = line.strip('\n')
        columns = line.split(",")
        if columns[0] != 'id':
            name=columns[1]
            full_name=columns[2]
            birthday = datetime.datetime.strptime(columns[3], '%d/%m/%Y') if columns[3] else None
            picture_path = columns[4]
            player = Player(name=columns[1])
            
            if full_name:
                player.full_name = full_name
            if birthday:
                player.birthday = birthday
            if picture_path:
                player.picture_path = picture_path
            player.create()
            players[full_name] = player
    f.close()

    matches = dict()
    f = open(os.path.join('padel_league/static/data', 'matches.csv'))
    for line in f:
        line = line.strip('\n')
        columns = line.split(",")
        if columns[0] != 'id':
            games_home_team = int(columns[1]) if columns[1] else None
            games_away_team = int(columns[2]) if columns[2] else None
            date_hour = datetime.datetime.strptime(columns[3], '%d/%m/%Y %H:%M') if columns[3] else None
            winner = int(columns[4]) if columns[4] else None
            matchweek = int(columns[5])
            field = columns[6]
            played = True if columns[7] == 'True' else False
            division = divisions[columns[8]]
            match = Match(division_id = division.id)

            if games_home_team:
                match.games_home_team = games_home_team
            if games_away_team:
                match.games_away_team = games_away_team
            if date_hour:
                match.date_hour = date_hour
            if winner or winner == 0:
                match.winner = winner
            if matchweek:
                match.matchweek = matchweek
            if field:
                match.field = field
            
            match.played = played
            match.create()
            matches[columns[0]] = match
    f.close()

    f = open(os.path.join('padel_league/static/data', 'players_divisions.csv'))
    for line in f:
        line = line.strip('\n')
        columns = line.split(",")
        if columns[0] != 'id':
            player = players[columns[1]]
            division = divisions[columns[2]]
            players_divisions = Association_PlayerDivision(player=player,division=division)
            
            players_divisions.create()
    f.close()

    f = open(os.path.join('padel_league/static/data', 'players_matches.csv'))
    for line in f:
        line = line.strip('\n')
        columns = line.split(",")
        if columns[0] != 'id':
            player = players[columns[1]]
            match = matches[columns[2]]
            team = columns[3]
            players_matches = Association_PlayerMatch(player=player,match=match,team = team)
            
            players_matches.create()
    f.close()

    return redirect(url_for('main.index'))


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'csv'}
