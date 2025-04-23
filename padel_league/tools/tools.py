import random
import os
import csv

from flask import current_app, url_for
from datetime import datetime
from sqlalchemy.ext.hybrid import hybrid_property, hybrid_method


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

def is_float(value):
    try:
        float(value)
        return True
    except:
        return False
    

def create_csv_for_model(model):
    model_name = model.__name__.lower()
    instances = model.query.all()

    filename = f'data/csv/{model_name}.csv'
    file_path = current_app.root_path + url_for('static', filename = filename)
    instances = [instance.get_dict() for instance in instances]
    if instances:
        fieldnames = instances[0].keys() 

        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for row in instances:
                writer.writerow(row)

    return url_for('static', filename = filename)

def upload_csv_to_model(model):
    model_name = model.__name__.lower()
    filename = f'data/csv/{model_name}.csv'
    file_path = current_app.root_path + url_for('static', filename = filename)

    hybrid_properties = get_hybrid_properties(model)
    headers = {'Content-Type': 'application/json'}

    with open(file_path, mode='r') as csvfile:
        reader = csv.DictReader(csvfile)

        for row in reader:
            filtered_data = {k: try_convert(v) for k, v in row.items() if k not in hybrid_properties}
            if filtered_data.get('name'):
                existing_instance = model.query.filter_by(name=filtered_data.get('name')).first()
            else:
                existing_instance = model.query.filter_by(id=filtered_data.get('id')).first()

            if existing_instance:
                existing_instance.update_with_dict(filtered_data)
                existing_instance.save()
            else:
                empty_instance = model()
                empty_instance.update_with_dict(filtered_data)
                empty_instance.create()
                            
    return True

def get_hybrid_properties(model):
    hybrid_properties = []
    for name, attr in model.__dict__.items():
        if isinstance(attr, (hybrid_property, hybrid_method)):
            hybrid_properties.append(name)
    return hybrid_properties

def try_convert(value):
    if value  == '':
        return None
    converters = [int, float, str_to_bool, str_to_date, str_to_datetime]
    for conv in converters:
        try:
            return conv(value)
        except ValueError:
            pass
    return value

def str_to_bool(s):
    if s.lower() == 'true':
        return True
    elif s.lower() == 'false':
        return False
    else:
        raise ValueError(f"Cannot convert {s} to boolean")
    
def str_to_date(s):
    string_formats = {
            'Date': [
            '%d/%m/%Y',    # 01/01/2023
            '%m/%d/%Y',    # 01/01/2023 US format
            '%Y-%m-%d',    # 2023-01-01 ISO 8601
            '%d-%m-%Y',    # 01-01-2023
            '%d.%m.%Y',    # 01.01.2023
            '%B %d, %Y',   # January 01, 2023
        ],
    }
    for format in string_formats['Date']:
        try:
            date_obj = datetime.strptime(s, format)
            return date_obj
        except ValueError:
            pass
    raise ValueError(f"Cannot convert {s} to Date")

def str_to_datetime(s):
    string_formats = {
        'DateTime': [
            '%d/%m/%Y, %H:%M',             # 01/01/2023, 12:00
            '%Y-%m-%dT%H:%M',              # 2023-01-01T12:00 ISO 8601 without seconds
            '%Y-%m-%dT%H:%M:%S',           # 2023-01-01T12:00:00 ISO 8601 with seconds
            '%Y-%m-%dT%H:%M:%S.%f',        # 2023-01-01T12:00:00.000000 ISO 8601 with microseconds
            '%d-%m-%Y %H:%M',              # 01-01-2023 12:00
            '%m/%d/%Y %I:%M %p',           # 01/01/2023 12:00 PM US format with AM/PM
            '%d %B, %Y %H:%M',             # 01 January, 2023 12:00
            '%A, %d %B %Y %H:%M:%S %Z',    # Tuesday, 01 January 2023 12:00:00 UTC
        ],
    }
    for format in string_formats['DateTime']:
        try:
            date_obj = datetime.strptime(s, format)
            return date_obj
        except ValueError:
            pass
    raise ValueError(f"Cannot convert {s} to Date")
