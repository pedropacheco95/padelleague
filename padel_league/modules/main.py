from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from padel_league.models import User , News

bp = Blueprint('main', __name__)

@bp.route('/', methods=('GET', 'POST'))
def index():
    if 'error' in session.keys():
        flash(session['error'])
    all_news = News.query.all()
    return render_template('index.html',all_news=all_news)

@bp.route('/calendar', methods=('GET', 'POST'))
def calendar():
    return render_template('calendar.html')