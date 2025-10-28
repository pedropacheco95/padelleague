import json

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for
from sqlalchemy.orm import joinedload

from padel_league.model import Image
from padel_league.models import Division, Match, OrderLine, Player, MODELS
from padel_league.tools import tools

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.route("/calendar", methods=("GET", "POST"))
@bp.route("/calendar/<division_id>", methods=("GET", "POST"))
def calendar(division_id=None):
    # Eventually this function should take into consideration the month
    # When clicking to change the month on the front end another call to the API would be made
    if division_id:
        division = Division.query.options(joinedload(Division.matches)).get(division_id)
        matches = division.matches if division else []
    else:
        matches = Match.query.options(joinedload(Match.division)).all()

    info = []
    for match in matches:
        info.append(
            {
                "eventName": match.clean_name(),
                "calendar": "Jogos",
                "color": "blue",
                "date": match.date_hour.strftime("%Y/%m/%d"),
                "href": url_for("matches.match", id=match.id),
            }
        )

    return json.dumps(info)


@bp.route("/points_by_matchweek/<division_id>", methods=("GET", "POST"))
def points_by_matchweek(division_id):
    division = Division.query.filter_by(id=division_id).first()
    points_by_matchweek = {}
    for relation in division.players_relations:
        points_by_matchweek[relation.player.id] = (
            relation.player.points_by_matchweek_for_graph(division)
        )

    points_by_matchweek["matchweek"] = division.last_updated_matchweek()
    return json.dumps(points_by_matchweek)


@bp.route("/delete_order_line/<id>", methods=("GET", "POST"))
def delete_order_line(id):
    order_line = OrderLine.query.filter_by(id=id).first()
    order_line.delete()
    return True


@bp.route("/delete_player/<id>", methods=("GET", "POST"))
def delete_player(id):
    player = Player.query.filter_by(id=id).first()
    for association in player.divisions_relations:
        association.delete()
    player.delete()
    return True


@bp.route("/delete_tournament/<id>", methods=("GET", "POST"))
def delete_tournament(id):
    division = Division.query.filter_by(id=id).first()
    for association in division.players_relations:
        association.delete()
    for match in division.matches:
        for association in match.players_relations:
            association.delete()
        match.delete()
    division.delete()
    return True


@bp.route("/edit/<model>/<id>", methods=["POST"])
def edit(model, id):
    model_cls = MODELS.get(model)
    if not model_cls:
        return jsonify(success=False, error=f"Model {model} not found"), 404

    obj = model_cls.query.filter_by(id=id).first()
    if not obj:
        return jsonify(success=False, error=f"{model} with id {id} not found"), 404

    methods = []
    if request.is_json:
        data = request.get_json() or {}
        values = data.get("values", {})
        methods = data.get("methods", [])
    else:
        form = obj.get_edit_form()
        values = form.set_values(request)

    if values:
        obj.update_with_dict(values)
        obj.save()

    for method_name in methods:
        if hasattr(obj, method_name):
            getattr(obj, method_name)()
        else:
            return jsonify(success=False, error=f"Method {method_name} not found"), 400

    return jsonify(success=True, id=obj.id)


@bp.route("/delete/<model>/<id>", methods=("GET", "POST"))
def delete(model, id):
    model_name = model
    if request.method == "POST":
        model = MODELS[model]
        obj = model.query.filter_by(id=id).first()
        obj.delete()
        return jsonify(url_for("editor.display_all", model=model_name))
    return jsonify(sucess=False)


@bp.route("/query/<model>", methods=("GET", "POST"))
def query(model):
    model = MODELS[model]
    instances = model.query.all()
    instances = [
        {"value": instance.id, "name": str(instance.name)} for instance in instances
    ]
    return jsonify(instances)


@bp.route("/remove_relationship", methods=("GET", "POST"))
def remove_relationship():
    data = request.get_json()

    model_name1 = data.get("model_name1")
    model_name2 = data.get("model_name2")
    field_name = data.get("field_name")
    id1 = int(data.get("id1"))
    id2 = int(data.get("id2"))

    model1 = MODELS[model_name1]
    model2 = MODELS[model_name2]

    obj1 = model1.query.filter_by(id=id1).first()
    obj2 = model2.query.filter_by(id=id2).first()

    field = getattr(obj1, field_name)
    field.remove(obj2)
    obj1.save()
    return jsonify(sucess=True)


@bp.route("/modal_create_page/<model>", methods=("GET", "POST"))
def modal_create_page(model):
    model_name = model
    model = MODELS[model_name]
    empty_instance = model()
    form = empty_instance.get_basic_create_form()
    if request.method == "POST":
        values = form.set_values(request)
        empty_instance.update_with_dict(values)
        empty_instance.create()
        response = {"value": empty_instance.id, "name": empty_instance.name}
        return jsonify(response)
    data = empty_instance.get_basic_create_data(form)
    return render_template("editor/modal_create.html", data=data)


@bp.route("/download_csv/<model>", methods=["GET", "POST"])
def download_csv(model):
    model_name = model
    model = MODELS[model_name]
    filepath = tools.create_csv_for_model(model)
    return filepath


@bp.route("/upload_csv_to_db/<model>", methods=["GET", "POST"])
def upload_csv_to_db(model):
    model_name = model
    model = MODELS[model_name]
    check = tools.upload_csv_to_model(model)
    if check:
        return jsonify(url_for("editor.display_all", model=model_name))
    else:
        return jsonify(sucess=False)


@bp.get("/image/<int:image_id>")
def image_by_id(image_id):
    img = Image.query.get(image_id)
    if not img:
        abort(404)
    resp = redirect(img.url(), code=302)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp
