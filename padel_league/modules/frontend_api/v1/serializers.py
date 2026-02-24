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


def serialize_user(user):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "isAdmin": user.is_admin,
        "playerId": user.player_id,
    }
