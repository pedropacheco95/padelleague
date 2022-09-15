import functools
import os
import datetime
import csv

from flask import Blueprint, redirect, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from padel_league.sql_db import db
from padel_league.models import User , Match , League , Edition , Division , Player , Association_PlayerDivision , Association_PlayerMatch , Registration , News

bp = Blueprint('uploads', __name__, url_prefix='/uploads')

@bp.route('/upload_csv_to_db', methods=['GET', 'POST'])
def upload_csv_to_db():

    leagues = dict()
    f = open(os.path.join('padel_league/static/data/csv', 'leagues.csv'))
    for line in f:
        line = line.strip('\n')
        columns = line.split(",")
        if columns[0] != 'id':
            id = columns[0]
            name = columns[1]
            liga = League(name=name)
            liga.create()
            leagues[id] = liga
    f.close()

    editions = dict()
    f = open(os.path.join('padel_league/static/data/csv', 'editions.csv'))
    for line in f:
        line = line.strip('\n')
        columns = line.split(",")
        if columns[0] != 'id':
            id = columns[0]
            name = columns[1]
            league = leagues[columns[2]]
            edicao = Edition(name=columns[1],league_id=league.id)
            edicao.create()
            editions[id] = edicao
    f.close()

    all_news = dict()
    f = open(os.path.join('padel_league/static/data/csv', 'news.csv'))
    for line in f:
        line = line.strip('\n')
        columns = line.split("|")
        if columns[0] != 'id':
            id = columns[0]
            title = columns[1]
            cover_path = columns[2]
            author = columns[3]
            text = columns[4]
            news = News(title=title,cover_path=cover_path,author=author,text=text)

            news.create()
            all_news[id] = news
    f.close()

    divisions = dict()
    f = open(os.path.join('padel_league/static/data/csv', 'divisions.csv'))
    for line in f:
        line = line.strip('\n')
        columns = line.split(",")
        if columns[0] != 'id':
            id = columns[0]
            name = columns[1]
            beginning_datetime = datetime.datetime.strptime(columns[2], '%Y-%m-%d %H:%M:%S') if columns[2] else None
            rating = int(columns[3])
            end_date = datetime.datetime.strptime(columns[4], '%Y-%m-%d') if columns[3] else None
            logo_image_path = columns[5]
            large_picture_path = columns[6]
            open_division = True if columns[8] == 'True' else False
            edition = editions[columns[9]]
            
            division = Division(name=name,
            beginning_datetime=beginning_datetime,
            end_date = end_date,
            logo_image_path=logo_image_path,
            large_picture_path=large_picture_path,
            has_ended=False,
            open_division=open_division,
            rating=rating,
            edition_id = edition.id)

            division.create()
            divisions[id] = division
    f.close()

    players = dict()
    f = open(os.path.join('padel_league/static/data/csv', 'players.csv'))
    for line in f:
        line = line.strip('\n')
        columns = line.split(",")
        if columns[0] != 'id':
            id = columns[0]
            name=columns[1]
            full_name=columns[2]
            birthday = datetime.datetime.strptime(columns[3], '%Y-%m-%d') if columns[3] else None
            picture_path = columns[4]
            large_picture_path = columns[5]
            ranking_points = int(columns[6]) if columns[6] else None
            ranking_position = int(columns[7]) if columns[7] else None
            height = float(columns[8]) if columns[8] else None
            prefered_hand = columns[9]
            player = Player(name=columns[1])
            
            if full_name:
                player.full_name = full_name
            if birthday:
                player.birthday = birthday
            if picture_path:
                player.picture_path = picture_path
            if ranking_points:
                player.ranking_points = ranking_points
            if ranking_position:
                player.ranking_position = ranking_position
            if height:
                player.height = height
            if prefered_hand:
                player.prefered_hand = prefered_hand
            player.create()
            players[id] = player
    f.close()

    matches = dict()
    f = open(os.path.join('padel_league/static/data/csv', 'matches.csv'))
    for line in f:
        line = line.strip('\n')
        columns = line.split(",")
        if columns[0] != 'id':
            id = columns[0]
            games_home_team = int(columns[1]) if columns[1] else None
            games_away_team = int(columns[2]) if columns[2] else None
            date_hour = datetime.datetime.strptime(columns[3], '%Y-%m-%d %H:%M:%S') if columns[3] else None
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
            matches[id] = match
    f.close()

    users = dict()
    f = open(os.path.join('padel_league/static/data/csv', 'users.csv'))
    for line in f:
        line = line.strip('\n')
        columns = line.split(",")
        if columns[0] != 'id':
            id = columns[0]
            username = columns[1]
            email = columns[2]
            password = columns[3]
            player = players[columns[4]]
            user = User(username=username,email=email,password=password,player_id=player.id)
            
            user.create()
            users[id] = user
    f.close()

    f = open(os.path.join('padel_league/static/data/csv', 'players_in_division.csv'))
    for line in f:
        line = line.strip('\n')
        columns = line.split(",")
        if columns[0] != 'player_id':
            player = players[columns[0]]
            division = divisions[columns[1]]
            players_divisions = Association_PlayerDivision(player=player,division=division)
            
            players_divisions.create()
    f.close()

    f = open(os.path.join('padel_league/static/data/csv', 'players_in_match.csv'))
    for line in f:
        line = line.strip('\n')
        columns = line.split(",")
        if columns[0] != 'player_id':
            player = players[columns[0]]
            match = matches[columns[1]]
            team = columns[2]
            players_matches = Association_PlayerMatch(player=player,match=match,team = team)
            
            players_matches.create()
    f.close()

    f = open(os.path.join('padel_league/static/data/csv', 'registrations.csv'))
    for line in f:
        line = line.strip('\n')
        columns = line.split(",")
        if columns[0] != 'player_id':
            player = players[columns[0]]
            edition = editions[columns[1]]
            registration = Registration(player=player,edition=edition)
            
            registration.create()
    f.close()

    return redirect(url_for('main.index'))

@bp.route('/export_db_to_csv', methods=['GET', 'POST'])
def export_db_to_csv():
    models = User.query.first().all_tables_object()
    instances = User.query.first().get_all_tables()
    for model in models.keys():
        models[model] = models[model].__table__.columns.keys()
    for model in instances.keys():
        instances[model] = instances[model].all()

    values = {}
    for model in models.keys():
        values[model] = []
        for instance in instances[model]:
            instance_values = []
            for field in models[model]:
                instance_values.append(getattr(instance, field))
            values[model].append(instance_values)


    for model in models.keys():
        file = os.path.join('padel_league/static/data/csv', '%s.csv' % model)
        fields = models[model]
        rows = values[model]

        with open(file, 'w') as f:
            write = csv.writer(f)
            
            write.writerow(fields)
            write.writerows(rows)
    return redirect(url_for('main.index'))


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'csv'}
