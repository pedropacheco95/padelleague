def compute_head_to_head(
    played_matches,
    player1_id,
    player2_id,
    *,
    source,
    source_label,
    get_scores,
    get_division,
    get_division_label=None,
):
    head_to_head = []
    p1 = str(player1_id)
    p2 = str(player2_id)
    division_label_getter = get_division_label or (lambda _match: None)

    for match in played_matches:
        home_rels = [rel for rel in match.players_relations if rel.team == "Home"]
        away_rels = [rel for rel in match.players_relations if rel.team == "Away"]
        home_ids = [str(rel.player_id) for rel in home_rels]
        away_ids = [str(rel.player_id) for rel in away_rels]

        p1_home = p1 in home_ids
        p2_home = p2 in home_ids
        p1_away = p1 in away_ids
        p2_away = p2 in away_ids

        if (p1_home and p2_home) or (p1_away and p2_away):
            continue
        if not ((p1_home and p2_away) or (p1_away and p2_home)):
            continue

        p1_in_home = p1_home
        p1_team_rels = home_rels if p1_in_home else away_rels
        p2_team_rels = away_rels if p1_in_home else home_rels

        p1_partner_rel = next(
            (rel for rel in p1_team_rels if str(rel.player_id) != p1), None
        )
        p2_partner_rel = next(
            (rel for rel in p2_team_rels if str(rel.player_id) != p2), None
        )

        p1_score, p2_score = get_scores(match, p1_in_home)
        winner = "draw"
        if p1_score > p2_score:
            winner = "p1"
        elif p2_score > p1_score:
            winner = "p2"

        head_to_head.append(
            {
                "matchId": int(match.id),
                "source": source,
                "sourceLabel": source_label,
                "matchweek": int(match.matchweek or 0),
                "division": int(get_division(match)),
                "divisionLabel": division_label_getter(match),
                "p1PartnerId": (
                    str(p1_partner_rel.player_id) if p1_partner_rel else "sub"
                ),
                "p1PartnerName": (
                    p1_partner_rel.player.name
                    if p1_partner_rel and p1_partner_rel.player
                    else "Substituto"
                ),
                "p2PartnerId": (
                    str(p2_partner_rel.player_id) if p2_partner_rel else "sub"
                ),
                "p2PartnerName": (
                    p2_partner_rel.player.name
                    if p2_partner_rel and p2_partner_rel.player
                    else "Substituto"
                ),
                "p1Score": int(p1_score),
                "p2Score": int(p2_score),
                "winner": winner,
            }
        )

    return head_to_head


def compute_player_comparison_stats(
    *,
    player_id,
    relation_by_player_id,
    played_matches,
    all_matches,
    matches_by_matchweek,
    ranking_position_by_player_id,
    serialize_player_relation,
    get_scores,
    get_division,
    get_multiplier,
    get_relation_points,
):
    results = []
    divisions_played = set()
    normalized_player_id = str(player_id)

    for match in played_matches:
        home_ids = [
            str(rel.player_id) for rel in match.players_relations if rel.team == "Home"
        ]
        away_ids = [
            str(rel.player_id) for rel in match.players_relations if rel.team == "Away"
        ]
        in_home = normalized_player_id in home_ids
        in_away = normalized_player_id in away_ids

        if not in_home and not in_away:
            continue

        divisions_played.add(int(get_division(match)))
        team_ids = home_ids if in_home else away_ids
        opp_ids = away_ids if in_home else home_ids

        partner_candidates = [pid for pid in team_ids if pid != normalized_player_id]
        partner_id = partner_candidates[0] if partner_candidates else "sub"
        opponent_1 = opp_ids[0] if len(opp_ids) > 0 else "sub"
        opponent_2 = opp_ids[1] if len(opp_ids) > 1 else "sub"

        team_score, opp_score = get_scores(match, in_home)
        team_score = int(team_score)
        opp_score = int(opp_score)

        results.append(
            {
                "matchweek": int(match.matchweek or 0),
                "division": int(get_division(match)),
                "partnerId": partner_id,
                "opponentIds": [opponent_1, opponent_2],
                "teamScore": team_score,
                "oppScore": opp_score,
                "won": team_score > opp_score,
                "drew": team_score == opp_score,
            }
        )

    wins = len([r for r in results if r["won"]])
    draws = len([r for r in results if r["drew"]])
    losses = len(results) - wins - draws
    win_rate = round((wins / len(results)) * 100) if results else 0
    divisions_sorted = sorted(divisions_played)

    current_streak = {"type": "W", "count": 0}
    ordered_results = sorted(
        results,
        key=lambda r: (r["matchweek"], r["teamScore"], r["oppScore"]),
        reverse=True,
    )
    if ordered_results:
        first = ordered_results[0]
        streak_type = "W" if first["won"] else ("D" if first["drew"] else "L")
        streak_count = 1
        for r in ordered_results[1:]:
            item_type = "W" if r["won"] else ("D" if r["drew"] else "L")
            if item_type == streak_type:
                streak_count += 1
            else:
                break
        current_streak = {"type": streak_type, "count": streak_count}

    best_win_diff = 0
    for r in results:
        if r["won"]:
            best_win_diff = max(best_win_diff, r["teamScore"] - r["oppScore"])

    worst_loss_diff = 0
    for r in results:
        if (not r["won"]) and (not r["drew"]):
            worst_loss_diff = max(worst_loss_diff, r["oppScore"] - r["teamScore"])

    def avg_opponent_position(result):
        opp1 = result["opponentIds"][0] if result["opponentIds"][0] != "sub" else "sub"
        opp2 = result["opponentIds"][1] if result["opponentIds"][1] != "sub" else "sub"
        return (
            ranking_position_by_player_id.get(opp1, 9999)
            + ranking_position_by_player_id.get(opp2, 9999)
        ) / 2

    biggest_wins = sorted(
        [r for r in results if r["won"]],
        key=avg_opponent_position,
    )[:3]
    worst_losses = sorted(
        [r for r in results if (not r["won"]) and (not r["drew"])],
        key=avg_opponent_position,
        reverse=True,
    )[:3]

    max_matchweek = max([int(m.matchweek or 0) for m in all_matches], default=0)
    all_player_ids = list(relation_by_player_id.keys())
    cumulative_points = {}

    for pid in all_player_ids:
        points_by_mw = {}
        running_points = 0
        for mw in range(1, max_matchweek + 1):
            for match in matches_by_matchweek.get(mw, []):
                home_ids = [
                    str(rel.player_id)
                    for rel in match.players_relations
                    if rel.team == "Home"
                ]
                away_ids = [
                    str(rel.player_id)
                    for rel in match.players_relations
                    if rel.team == "Away"
                ]
                in_home = pid in home_ids
                in_away = pid in away_ids
                if not in_home and not in_away:
                    continue

                team_score, opp_score = get_scores(match, in_home)
                team_score = int(team_score)
                opp_score = int(opp_score)
                multiplier = int(get_multiplier(match))
                if team_score > opp_score:
                    running_points += 3 * multiplier
                elif team_score == opp_score:
                    running_points += 1 * multiplier
            points_by_mw[mw] = running_points
        cumulative_points[pid] = points_by_mw

    snapshots = []
    for mw in range(1, max_matchweek + 1):
        rankings = sorted(
            all_player_ids,
            key=lambda pid: (
                -(cumulative_points.get(pid, {}).get(mw, 0)),
                ranking_position_by_player_id.get(pid, 9999),
                pid,
            ),
        )
        snapshots.append(
            {
                "matchweek": mw,
                "points": cumulative_points.get(normalized_player_id, {}).get(mw, 0),
                "position": (
                    rankings.index(normalized_player_id) + 1
                    if normalized_player_id in rankings
                    else 0
                ),
            }
        )

    player_rel = relation_by_player_id[normalized_player_id]
    relation_points = get_relation_points(player_rel)
    unique_matchweeks = len(set([r["matchweek"] for r in results]))
    avg_points_per_matchweek = (
        round((relation_points or 0) / unique_matchweeks, 1)
        if unique_matchweeks > 0
        else 0
    )

    return {
        "player": serialize_player_relation(player_rel),
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "winRate": win_rate,
        "totalGames": len(results),
        "points": relation_points or 0,
        "bestWinDiff": best_win_diff,
        "worstLossDiff": worst_loss_diff,
        "currentStreak": current_streak,
        "divisionsPlayed": divisions_sorted,
        "highestDivision": min(divisions_sorted) if divisions_sorted else 0,
        "lowestDivision": max(divisions_sorted) if divisions_sorted else 0,
        "biggestWins": biggest_wins,
        "worstLosses": worst_losses,
        "avgPointsPerMatchweek": avg_points_per_matchweek,
        "snapshots": snapshots,
    }


def compute_head_to_head_totals(all_head_to_head):
    p1_wins = len([item for item in all_head_to_head if item.get("winner") == "p1"])
    p2_wins = len([item for item in all_head_to_head if item.get("winner") == "p2"])
    draws = len([item for item in all_head_to_head if item.get("winner") == "draw"])
    return {
        "total": len(all_head_to_head),
        "p1Wins": p1_wins,
        "p2Wins": p2_wins,
        "draws": draws,
        "p1Losses": p2_wins,
        "p2Losses": p1_wins,
    }
