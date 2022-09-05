from flask import Blueprint, render_template, request

from padel_league.models import Division , Player

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
    return render_template('tournaments/tournament.html',tournament=division)

@bp.route('/edit/<id>', methods=('GET', 'POST'))
def edit(id):
    return render_template('tournaments/edit_tournament.html')

@bp.route('/create', methods=('GET', 'POST'))
def create():
    if request.method == 'POST':
        print('::::::::::')
        print('::::::::::')
        print(request.form)
        print('::::::::::')
        print('::::::::::')
    players = Player.query.all()
    return render_template('tournaments/create_tournament.html',players=players)
