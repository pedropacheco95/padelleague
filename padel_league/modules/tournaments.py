from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from padel_league.models import User , Division , Association_PlayerMatch

bp = Blueprint('tournaments', __name__,url_prefix='/tournaments')

@bp.route('/', methods=('GET', 'POST'))
def tournaments():
    divisions_to_play = Division.query.filter_by(has_ended=False).all()
    divisions_ended = Division.query.filter_by(has_ended=True).all()
    return render_template('tournaments/tournaments.html',divisions_to_play=divisions_to_play, divisions_ended=divisions_ended)

@bp.route('/<id>', methods=('GET', 'POST'))
@bp.route('/<id>/<recalculate>', methods=('GET', 'POST'))
def tournament(id,recalculate=False):
    if recalculate=='recalculate':
        recalculate = True
    division = Division.query.filter_by(id=id).first()
    division.update_table(recalculate)
    return render_template('tournaments/tournament.html',tournament=division)

@bp.route('/edit/<id>', methods=('GET', 'POST'))
def edit(id):
    return render_template('tournaments/edit_tournament.html')