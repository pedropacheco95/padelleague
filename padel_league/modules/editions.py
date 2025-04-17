from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from padel_league.models import Edition, League, Division, Association_PlayerDivision, Player
from sqlalchemy import desc
import datetime

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

@bp.route('/auto_create', methods=('GET', 'POST'))
def auto_create():
    leagues = League.query.all()
    last_edition = Edition.query.order_by(Edition.id.desc()).first()

    if request.method == 'POST':
        edition_name = request.form['name']
        league_id = int(request.form['league'])
        num_divisions = int(request.form['num_divisions'])
        division_base_name = request.form['division_base_name']  # e.g. "Inverno 2025"
        beggining_date= datetime.datetime.strptime(request.form['beggining_date'], '%Y-%m-%d') if request.form['beggining_date'] else None

        last_divisions = (
            Division.query.filter_by(edition_id=last_edition.id).order_by(Division.name).all()
            if last_edition else []
        )

        all_players_by_div = {}
        for div in last_divisions:
            associations = Association_PlayerDivision.query.filter_by(division_id=div.id).all()
            players = div.players_classification()
            all_players_by_div[div.name] = players

        new_divs = []
        promoted_to_above = []
        relagated_to_this = []
        for i in range(num_divisions):
            div_name = f"{division_base_name} - {i+1}ª Divisão"
            players = []
            if last_divisions and i < len(last_divisions):
                previous_div = last_divisions[i]
                current_players = all_players_by_div.get(previous_div.name, [])

                relegated_from_this = current_players[-2:] if i < len(last_divisions) - 1 else []

                promoted_to_this = []
                if i+1 < len(last_divisions):
                    below_div = last_divisions[i + 1]
                    below_players = all_players_by_div.get(below_div.name, [])
                    promoted_to_this = below_players[:2]
                
                players = [player for player in current_players if player not in relegated_from_this]
                if promoted_to_above:
                    players = [player for player in players if player not in promoted_to_above]
                players += promoted_to_this
                if relagated_to_this:
                    players += relagated_to_this
                
                promoted_to_above = promoted_to_this
                relagated_to_this = relegated_from_this

            new_divs.append({
                'name': div_name,
                'players': players,
                'beggining_date': beggining_date,
                'rating': 2000/ (2**i) 
            })

        return render_template(
            'editions/edition_auto_create.html',
            edition_name=edition_name,
            league_id=league_id,
            division_base_name=division_base_name,
            divisions=new_divs,
            leagues=leagues,
            all_players=Player.query.all()
        )

    return render_template('editions/edition_auto_form.html', leagues=leagues)

@bp.route('/delete/<id>', methods=('GET', 'POST'))
def delete(id):
    edition = Edition.query.get(id)
    edition.delete()
    return redirect(url_for('main.index'))
