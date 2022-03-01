from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from padel_league.models import User

bp = Blueprint('main', __name__)

@bp.route('/', methods=('GET', 'POST'))
def index():
    if 'error' in session.keys():
        flash(session['error'])
    return render_template('index.html')

@bp.route('/calendar', methods=('GET', 'POST'))
def calendar():
    return render_template('calendar.html')