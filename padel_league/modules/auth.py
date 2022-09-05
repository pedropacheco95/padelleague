import functools
import datetime
import os
import unidecode

from flask import Blueprint, flash, redirect, render_template, request, session, url_for , current_app
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
        password = generate_password_hash(request.form['password'])

        name = request.form['name']
        full_name= request.form['full_name']
        prefered_hand= request.form['prefered_hand']
        prefered_position= request.form['prefered_position']
        height= request.form['height']
        birthday= datetime.datetime.strptime(request.form['birth_date'], '%Y-%m-%d') if request.form['birth_date'] else None

        files = request.files.getlist('pictures')

        error = None
        if not username:
            error = 'Tens que por um username oh burro.'
        elif not password:
            error = 'Tens que por uma password oh burro.'
        elif User.query.filter_by(username=username).first() is not None:
            error = f"O username {username} já está registado oh burro."
        elif User.query.filter_by(email=email).first() is not None:
            error = f"O email {email} já está registado oh burro."
        elif not name:
            error = 'Tens que por um nome oh burro.'

        if error is None:
            player = Player(name=name)
            player.create()
            if full_name:
                player.full_name = full_name
            if birthday:
                player.birthday = birthday
            if height:
                player.height = height
            if prefered_hand:
                player.prefered_hand = prefered_hand
            if prefered_position:
                player.prefered_position = prefered_position
            player.save()
            for index in range(len(files)):
                file = files[index]
                if file.filename != '':
                    image_name = str(player.name).replace(" ", "").lower()
                    image_name = unidecode.unidecode(image_name)
                    image_name = '{image_name}_{player_id}.jpg'.format(image_name=image_name,player_id=player.id)

                    filename = os.path.join('images',image_name)
                    path = current_app.root_path + url_for('static', filename = filename)
                    file_exists = os.path.exists(path)
                    if not file_exists:
                        img_file = open(path,'wb')
                        img_file.close()
                    file.save(path)

                    player.picture_path = image_name
                    player.save()
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
