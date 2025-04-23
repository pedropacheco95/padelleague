from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from padel_league.models import User , News, Edition, Division, Sponsor

bp = Blueprint('main', __name__)

@bp.route('/', methods=('GET', 'POST'))
def index():
    if 'error' in session.keys():
        flash(session['error'])
    latest_news = News.query.filter_by(latest=True).order_by(News.id.desc()).first()
    all_news = News.query.filter_by(latest=False).order_by(News.id.desc()).limit(3).all()
    last_edition = Edition.query.order_by(Edition.id.desc()).first()
    divisions_to_play = Division.query.filter_by(has_ended=False).order_by(Division.id.asc()).all()
    sponsors = Sponsor.query.all()
    return render_template('index.html',latest_news=latest_news, all_news=all_news, last_edition = last_edition, tournaments=divisions_to_play, sponsors=sponsors)

@bp.route('/calendar', methods=('GET', 'POST'))
def calendar():
    return render_template('calendar.html')

@bp.route('/statues', methods=('GET', 'POST'))
def statues():
    return render_template('statues.html')