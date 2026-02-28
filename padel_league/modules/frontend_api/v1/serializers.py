"""
serializers.py - TypeScript-friendly serializers for all models.
Each returns a plain dict with camelCase keys matching the TypeScript interfaces.
"""


def serialize_image(image):
    if not image:
        return None
    return image.url()


def serialize_player(player, short=False):
    if not player:
        return {
            "id": None,
            "name": "Substituto",
            "fullName": "Jogador substituto",
            "pictureUrl": "/static/images/Player/default_player.jpg",
            "rankingPoints": 0,
            "link": None,
        }
    base = {
        "id": player.id,
        "name": player.name,
        "fullName": player.full_name or player.name,
        "pictureUrl": player.picture_url,
        "rankingPoints": round(player.ranking_points) if player.ranking_points else 0,
    }
    if short:
        return base
    return {
        **base,
        "email": player.email if hasattr(player, "email") else None,
        "preferedHand": player.prefered_hand,
        "preferedPosition": player.prefered_position,
        "height": player.height,
        "birthday": player.birthday.isoformat() if player.birthday else None,
    }


def serialize_news(news, short=False):
    if not news:
        return None
    base = {
        "id": news.id,
        "title": news.title,
        "author": news.author,
        "coverImageUrl": news.cover_image_url,
        "latest": news.latest,
    }
    if short:
        return base
    return {
        **base,
        "text": news.text,
    }


def serialize_match_line(match):
    """Minimal match representation used in edition result cards."""
    players = match.players_formatted()
    return {
        "id": match.id,
        "home": {
            "player1": players["home"]["player1"],
            "player2": players["home"]["player2"],
            "result": players["home"]["result"],
        },
        "away": {
            "player1": players["away"]["player1"],
            "player2": players["away"]["player2"],
            "result": players["away"]["result"],
        },
    }


def serialize_match(match, short=False):
    home_players = match.home_players()
    away_players = match.away_players()

    def get_player(players, index):
        return serialize_player(
            players[index] if index < len(players) else None, short=True
        )

    base = {
        "id": match.id,
        "dateHour": match.date_hour.isoformat() if match.date_hour else None,
        "gamesHomeTeam": match.games_home_team,
        "gamesAwayTeam": match.games_away_team,
        "winner": match.winner,
        "matchweek": match.matchweek,
        "field": match.field,
        "played": match.played,
        "divisionId": match.division_id,
        "homePlayers": [get_player(home_players, 0), get_player(home_players, 1)],
        "awayPlayers": [get_player(away_players, 0), get_player(away_players, 1)],
    }
    return base


def serialize_division(division, short=False):
    base = {
        "id": division.id,
        "name": division.name,
        "rating": division.rating,
        "hasEnded": division.has_ended,
        "openDivision": division.open_division,
        "logoImageUrl": division.logo_image_url,
        "largePictureUrl": division.large_picture_url,
        "editionId": division.edition_id,
        # These mirror what tournament_index_card uses
        "editionName": division.edition.name if division.edition else None,
        "editionShortDateString": (
            division.edition.short_date_string() if division.edition else None
        ),
        "beginningDatetime": (
            division.beginning_datetime.isoformat()
            if division.beginning_datetime
            else None
        ),
        "endDate": division.end_date.isoformat() if division.end_date else None,
    }
    if short:
        return base
    return {
        **base,
        "lastPlayedMatches": [
            serialize_match_line(m) for m in division.last_played_matches()
        ],
    }


def serialize_edition(edition, short=False):
    base = {
        "id": edition.id,
        "name": edition.name,
        "fullName": edition.get_full_name(),
        "shortDateString": edition.short_date_string(),
        "hasEnded": edition.has_ended(),
        "leagueId": edition.league_id,
        "leagueName": edition.league.name if edition.league else None,
    }
    if short:
        return base
    return {
        **base,
        "divisions": [
            {
                **serialize_division(d, short=True),
                "lastPlayedMatches": [
                    serialize_match_line(m) for m in d.last_played_matches()
                ],
            }
            for d in edition.divisions
        ],
    }


def serialize_sponsor(sponsor):
    return {
        "id": sponsor.id,
        "name": sponsor.name,
        "url": sponsor.url,
        "imageUrl": sponsor.image_url,
    }


def serialize_standings_row(rel, position):
    return {
        "position": position,
        "player": serialize_player(rel.player, short=True),
        "points": round(rel.points) if rel.points else 0,
        "wins": rel.wins,
        "draws": rel.draws,
        "losts": rel.losts,
        # Template divides appearances by 3 to convert match-appearances → matchweek-appearances
        "appearances": int(rel.appearances / 3) if rel.appearances else 0,
    }


def serialize_player_ranking(player):
    return {
        **serialize_player(player, short=True),
        "rankingPosition": player.ranking_position,
    }


def serialize_player_detail(player):
    n_played = len(player.matches_played())
    n_won = len(player.matches_won())
    n_lost = len(player.matches_lost())
    n_drawn = len(player.matches_drawn())
    efficiency = round(n_won / n_played * 100, 2) if n_played else 0

    n_tournaments = len(player.divisions_relations)
    matchweeks_played = round(n_played / 3) if n_played else 0
    matchweeks_missed = (
        round(n_tournaments * 7 - n_played / 3) if n_played and n_tournaments else 0
    )
    matchweeks_per_tournament = (
        round(n_played / 3 / n_tournaments, 2) if n_played and n_tournaments else 0
    )
    attendance = (
        round(n_played / (n_tournaments * 3 * 7) * 100, 2)
        if n_played and n_tournaments
        else 0
    )

    try:
        other_players = (
            player.previous_and_next_player() if player.divisions_relations else None
        )
    except Exception:
        other_players = None

    tournament_history = []
    for rel in player.divisions_relations:
        d = rel.division
        won = len(player.matches_won(d))
        played = len(player.matches_played(d))
        place = rel.place or "Por jogar"
        points = rel.compute_ranking_points()
        tournament_history.append(
            {
                "divisionId": d.id,
                "divisionName": d.name,
                "endDate": d.end_date.isoformat() if d.end_date else None,
                "won": won,
                "played": played,
                "place": place,
                "rankingPoints": points,
            }
        )

    return {
        "id": player.id,
        "name": player.name,
        "fullName": player.full_name or player.name,
        "pictureUrl": player.picture_url,
        "largePictureUrl": player.large_picture_url,
        "rankingPoints": round(player.ranking_points) if player.ranking_points else 0,
        "rankingPosition": player.ranking_position,
        "birthday": player.birthday.isoformat() if player.birthday else None,
        "height": player.height,
        "preferedHand": player.prefered_hand,
        "preferedPosition": player.prefered_position,
        "username": player.user.username if player.user else None,
        "previousPlayer": (
            serialize_player_ranking(other_players["previous"])
            if other_players
            else None
        ),
        "nextPlayer": (
            serialize_player_ranking(other_players["next"]) if other_players else None
        ),
        "matchesPlayed": n_played,
        "matchesWon": n_won,
        "matchesLost": n_lost,
        "matchesDrawn": n_drawn,
        "efficiency": efficiency,
        "tournamentsPlayed": n_tournaments,
        "matchweeksPlayed": matchweeks_played,
        "matchweeksMissed": matchweeks_missed,
        "matchweeksPerTournament": matchweeks_per_tournament,
        "attendance": attendance,
        "tournamentHistory": tournament_history,
    }


def serialize_player_short(player):

    return {
        "id": player.id,
        "name": player.name,
        "fullName": player.full_name or player.name,
        "pictureUrl": player.picture_url,
        "rankingPoints": round(player.ranking_points) if player.ranking_points else 0,
    }


def serialize_user(user):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "isAdmin": user.is_admin,
        "superAdmin": user.super_admin,
        "playerId": user.player_id,
    }


def serialize_shuffle_match(match):
    home_players = match.home_players()
    away_players = match.away_players()

    def player_id(players, idx):
        if idx < len(players) and players[idx]:
            return str(players[idx].id)
        return "sub"

    return {
        "id": str(match.id),
        "matchweek": match.matchweek,
        "division": match.division,
        "team1": [player_id(home_players, 0), player_id(home_players, 1)],
        "team2": [player_id(away_players, 0), player_id(away_players, 1)],
        "score1": match.score1,
        "score2": match.score2,
        "played": bool(match.played),
    }


def serialize_shuffle_tournament(tournament):
    players = []
    divisions = {}

    for rel in tournament.players_relations:
        pid = str(rel.player.id)
        players.append(
            {
                "id": pid,
                "name": rel.player.name,
                "fullName": rel.player.full_name or rel.player.name,
                "pictureUrl": rel.player.picture_url,
                "rankingPoints": (
                    round(rel.player.ranking_points)
                    if rel.player and rel.player.ranking_points
                    else 0
                ),
                "position": rel.position or 0,
                "points": rel.points or 0,
                "wins": rel.wins or 0,
                "draws": rel.draws or 0,
                "losses": rel.losses or 0,
                "gamesPlayed": rel.games_played or 0,
                "gamesWon": rel.games_won or 0,
                "gamesLost": rel.games_lost or 0,
            }
        )
        divisions.setdefault(rel.division_number, []).append(
            (rel.position or 9999, pid)
        )

    division_items = [
        {
            "number": number,
            "playerIds": [
                pid for _, pid in sorted(player_items, key=lambda x: (x[0], x[1]))
            ],
        }
        for number, player_items in sorted(divisions.items(), key=lambda x: x[0])
    ]

    return {
        "id": tournament.id,
        "title": tournament.title,
        "currentMatchweek": tournament.current_matchweek,
        "maxPlayers": tournament.max_players,
        "players": sorted(players, key=lambda p: ((p["position"] or 9999), p["id"])),
        "matches": [
            serialize_shuffle_match(m)
            for m in sorted(
                tournament.matches, key=lambda m: (m.matchweek, m.division, m.id)
            )
        ],
        "divisions": division_items,
        "divisionMultipliers": tournament.division_multipliers,
    }
