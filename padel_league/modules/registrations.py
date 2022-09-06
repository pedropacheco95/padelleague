from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from padel_league.models import  Edition , Registration , Player

bp = Blueprint('registrations', __name__,url_prefix='/registrations')

@bp.route('/create/<edition_id>', methods=('GET', 'POST'))
def create(edition_id):
    if 'user' not in session.keys():
        return render_template('registrations/no_user.html')
    edition = Edition.query.filter_by(id=edition_id).first()
    if not edition:
        return 'error'
    player_id = session['user'].player_id
    old_registration = Registration.query.filter_by(player_id=player_id,edition_id=edition_id).first()
    if old_registration:
        return render_template('registrations/already_registered.html')
    registration = Registration(edition_id=edition_id, player_id=player_id)
    registration.create()

    return render_template('registrations/done.html')

@bp.route('/', methods=('GET', 'POST'))
def registrations():
    registrations = Registration.query.all()
    return render_template('registrations/registrations.html', registrations=registrations)

@bp.route('/delete/<id>', methods=('GET', 'POST'))
def delete(id):
    registration = Registration.query.filter_by(id=id).first()
    registration.delete()
    return redirect(url_for('main.index'))