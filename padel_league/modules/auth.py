import functools

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import null

from padel_league.models import User , Player

bp = Blueprint('auth', __name__, url_prefix='/auth')

@bp.route('/', methods=('GET', 'POST'))
def index():
    return render_template('index.html')

@bp.route('/register', methods=('GET', 'POST'))
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        player = Player.query.filter_by(id = int(request.form['player'])).first() if request.form['player'] else None
        password = generate_password_hash(request.form['password'])
        error = None
        if not username:
            error = 'Tens que por um username oh burro.'
        elif not password:
            error = 'Tens que por uma password oh burro.'
        elif not player:
            error = 'Tens que escolher um jogador oh burro.'
        elif User.query.filter_by(username=username).first() is not None:
            error = f"O username {username} já está registado oh burro."
        elif User.query.filter_by(email=email).first() is not None:
            error = f"O email {email} já está registado oh burro."

        if error is None:
            user = User(username=username, email=email , password= password, player_id=player.id)
            user.create()
            return redirect(url_for('auth.login'))

        flash(error)

    players = Player.query.filter_by(user = null()).all()

    return render_template('auth/register.html',players=players)


@bp.route('/login', methods=('GET', 'POST'))
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        error = None

        user = User.query.filter_by(username=username).first()

        if user is None:
            error = 'Enganaste-te no username oh burro.'
        elif not check_password_hash(user.password, password):
            error = 'Enganaste-te na password oh burro.'

        if error is None:
            session.clear()
            session['user'] = user
            if username == 'admin':
                session['admin_logged'] = True
            return redirect(url_for('main.index'))

        flash(error)

    return render_template('auth/login.html')

@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('main.index'))

def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if session['user'] is None:
            return redirect(url_for('auth.login'))

        return view(**kwargs)

    return wrapped_view
