from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from padel_league.models import User

bp = Blueprint('users', __name__,url_prefix='/users')

@bp.route('/<id>', methods=('GET', 'POST'))
def user(id):
    user = User.query.filter_by(id=id).first()
    return render_template('users/user.html',user=user)

@bp.route('/edit/<id>', methods=('GET', 'POST'))
def edit(id):
    return render_template('players/edit_player.html')