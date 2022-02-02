import datetime 
from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from padel_league.models import Association_PlayerMatch , Match , Player , Division

bp = Blueprint('matches', __name__,url_prefix='/matches')

@bp.route('/', methods=('GET', 'POST'))
def matches():
    matches = Match.query.all()
    return render_template('matches/matches.html',matches=matches)

@bp.route('/matchweek/<matchweek>', methods=('GET', 'POST'))
@bp.route('/matchweek/<division>/<matchweek>', methods=('GET', 'POST'))
def by_matchweek(matchweek,division=None):
    division = Division.query.filter_by(name=division).first() if division else None
    if not division:
        matches = Match.query.filter_by(matchweek=matchweek).all()
    else:
        matches = [match for match in division.matches if match.matchweek == int(matchweek)]
    return render_template('matches/matches.html',matches=matches)

@bp.route('/for_edit/<division_id>', methods=('GET', 'POST'))
def for_edit(division_id):
    division = Division.query.filter_by(id=division_id).first() if division_id else None
    matchweek = division.get_ordered_matches_played()[-1].matchweek + 1
    matches = [match for match in division.matches if match.matchweek == int(matchweek) and ( not match.played)]
    return render_template('matches/matches.html',matches=matches)


@bp.route('/<id>', methods=('GET', 'POST'))
def match(id):
    match = Match.query.filter_by(id=id).first()
    return render_template('matches/match.html',match=match)

@bp.route('player/<player_id>', methods=('GET', 'POST'))
@bp.route('player/<player_id>/<type>', methods=('GET', 'POST'))
@bp.route('player/<player_id>/<type>/<division_id>', methods=('GET', 'POST'))
def player(player_id,type=None,division_id=None):
    division = Division.query.filter_by(id=division_id).first() if division_id else None
    player = Player.query.filter_by(id=player_id).first()
    if not type:
        return redirect(url_for('matches.player',player_id=player_id,type='all'))
    elif type == 'all':
        matches = player.get_match_relations(division)
    elif type == 'played':
        matches = player.matches_played(division)
    elif type == 'won':
        matches = player.matches_won(division)
    elif type == 'lost':
        matches = player.matches_lost(division)
    elif type == 'drawn':
        matches = player.matches_drawn(division)
    else:
        raise AttributeError(type)
    return render_template('matches/matches.html',matches=matches)

@bp.route('/edit/<id>', methods=('GET', 'POST'))
def edit(id):
    match = Match.query.filter_by(id=id).first()
    if request.method == 'POST':
        eliminated_players = [player for player in request.form['players_eliminated'].split(';') if player]
        if eliminated_players:
            home_players = match.home_players()
            away_players = match.away_players()
            players = {
                'homeplayer0': home_players[0], 
                'homeplayer1': home_players[1], 
                'awayplayer0': away_players[0], 
                'awayplayer1': away_players[1]
            }
            for player in eliminated_players:
                association = Association_PlayerMatch.query.filter_by(match_id=match.id,player_id=players[player].id).first()
                association.delete()
        hometeam_games = int(request.form['hometeam_games_input'])
        awayteam_games = int(request.form['awayteam_games_input'])
        match_field = request.form['match_field']

        match.games_home_team = hometeam_games
        match.games_away_team = awayteam_games
        match.winner = 1 if hometeam_games > awayteam_games else -1 if awayteam_games > hometeam_games else 0
        match.field = match_field
        if not match.played:
            match.division.add_match_to_table(match)
            match.played = True
        match.save()

        match.division.add_match_to_table(match)
        match.division.edition.league.ranking_add_match(match)

        return redirect(url_for('matches.match',id=match.id))
    return render_template('matches/edit_match.html',match=match)