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

def dict_to_table(data):
    if not data:
        return None

    headers = list(data[0].keys())
    rows = [list(entry.values()) for entry in data]

    column_widths = [max(len(str(row[i])) for row in rows + [headers]) for i in range(len(headers))]
    table = []

    header_row = "| " + " | ".join(f"{headers[i]:<{column_widths[i]}}" for i in range(len(headers))) + " |"
    table.append(header_row)
    separator_row = "|-" + "-|-".join("-" * width for width in column_widths) + "-|"
    table.append(separator_row)

    for row in rows:
        data_row = "| " + " | ".join(f"{row[i]:<{column_widths[i]}}" for i in range(len(headers))) + " |"
        table.append(data_row)

    return "\n".join(table)