import functools
import json

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from padel_league.models import Division , Match , Player , OrderLine

bp = Blueprint('api', __name__, url_prefix='/api')

@bp.route('/calendar', methods=('GET', 'POST'))
@bp.route('/calendar/<division_id>',methods=('GET', 'POST'))
def calendar(division_id=None):
    #Eventually this function should take into consideration the month
    #When clicking to change the month on the front end another call to the API would be made
    if division_id:
        division = Division.query.filter_by(id=division_id).first()
        matches = division.matches
    else:
        matches = Match.query.all()
    
    info = []
    for match in matches:
        info.append(
            { 'eventName': match.name(),
            'calendar': 'Jogos',
            'color': 'blue' ,
            'date':match.date_hour.strftime("%Y/%m/%d"),
            'href':url_for('matches.match',id=match.id)}
        )
    
    return json.dumps(info)


@bp.route('/points_by_matchweek/<division_id>',methods=('GET', 'POST'))
def points_by_matchweek(division_id):
    division = Division.query.filter_by(id=division_id).first()
    points_by_matchweek = {}
    for relation in division.players_relations:
        points_by_matchweek[relation.player.id] = relation.player.points_by_matchweek_for_graph(division)
    
    points_by_matchweek['matchweek'] = division.last_updated_matchweek()
    return json.dumps(points_by_matchweek)

@bp.route('/delete_order_line/<id>',methods=('GET', 'POST'))
def delete_order_line(id):
    order_line = OrderLine.query.filter_by(id=id).first()
    order_line.delete()
    return True

@bp.route('/delete_player/<id>', methods=('GET', 'POST'))
def delete_player(id):
    player = Player.query.filter_by(id=id).first()

    for association in player.divisions_relations:
        association.delete()
    player.delete()
    return True