from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from padel_league.models import Edition , League 

bp = Blueprint('editions', __name__,url_prefix='/editions')

@bp.route('/create', methods=('GET', 'POST'))
def create():
    if request.method == 'POST':
        name = request.form['name']
        league_id = int(request.form['league'])
        edicao = Edition(name=name,league_id=league_id)
        edicao.create()
        return redirect(url_for('main.index'))
    leagues = League.query.all()
    return render_template('editions/edition_create.html',leagues=leagues)
