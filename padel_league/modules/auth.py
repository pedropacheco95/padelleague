import functools
import datetime
import os
import unidecode

from flask import Blueprint, flash, redirect, render_template, request, session, url_for , current_app
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import null, inspect

from padel_league.models import User , Player , Order , Association_PlayerDivision , Division
from padel_league.tools import image_tools

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

        final_files = request.files.getlist('finalFile')

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
            for file in final_files:
                if file.filename != '':
                    image_name = str(player.name).replace(" ", "").lower()
                    image_name = unidecode.unidecode(image_name)
                    image_name = '{image_name}_{player_id}.png'.format(image_name=image_name,player_id=player.id)

                    filename = os.path.join('players',image_name)

                    image_tools.save_file(file, filename)
                    #image_tools.remove_background(filename)

                    player.picture_path = image_name
                    player.save()
            division = Division.query.filter_by(id=5).first()
            players_divisions = Association_PlayerDivision(player=player,division=division)
            players_divisions.create()
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
            #Check if user has an open order
            if not [order for order in user.orders if not order.closed]:
                order = Order(user_id=user.id)
                order.create()
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
