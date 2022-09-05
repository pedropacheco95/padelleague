from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from padel_league.models import  Edition , registration

bp = Blueprint('registrations', __name__,url_prefix='/registrations')

@bp.route('/create/<edition_id>', methods=('GET', 'POST'))
def create(edition_id):
    if 'user' not in session.keys():
        return render_template('registrations/no_user.html')
    edition = Edition.query.filter_by(id=edition_id).first()
    if not edition:
        return 'error'
    player = session['user'].player
    registration = registration(edition_id=edition_id, player_id=player.id)
    registration.create()

    return render_template('registrations/done.html')
