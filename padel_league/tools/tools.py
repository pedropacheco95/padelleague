import random

def create_chamionship_games(players):
    all_teams = []
    for i in range(len(players)):
        for j in range(i,len(players)):
            if i != j:
                all_teams.append([players[i],players[j]])
    matchweeks = []
    for i in range(len(players)-1):
        count = 0
        matchweek_teams = []
        available_teams = all_teams.copy()
        while len(matchweek_teams) < 4:
            if count > 50:
                count = 0
                all_teams += matchweek_teams
                matchweek_teams = []
                available_teams = all_teams.copy()
            count += 1
            team = random.choice(available_teams)
            remaining = [x for x in available_teams if not any(y in x for y in team)]
            if remaining or len(matchweek_teams)==3:
                all_teams.remove(team)
                matchweek_teams.append(team)
                available_teams = remaining
        matchweeks.append(matchweek_teams)
    return matchweeks

def get_games_from_matchweek(matchweek):
    games = []
    for i in range(len(matchweek)):
        for j in range(i+1,len(matchweek)):
            games.append([matchweek[i],matchweek[j]])
    return games