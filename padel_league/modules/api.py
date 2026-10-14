import csv
import io
import json

from flask import (
    Blueprint,
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user
from sqlalchemy.orm import joinedload

from padel_league.model import Image
from padel_league.models import Division, Match, OrderLine, Player, MODELS
from padel_league.tools import auth_tools, tools

bp = Blueprint("api", __name__, url_prefix="/api")

# Read-only endpoints used by public Jinja pages. Everything else in this
# blueprint is the admin editor's backend and needs a logged-in admin.
PUBLIC_ENDPOINTS = {
    "api.calendar",
    "api.points_by_matchweek",
    "api.image_by_id",
}
# A user's own cart deletes its order lines; ownership is checked in the view.
LOGGED_IN_ENDPOINTS = {"api.delete_order_line"}

# Credentials (password hash, reset code) are never written to a CSV export.
CSV_EXCLUDED_COLUMNS = {"password", "generated_code"}


def _allow():
    return None


@bp.before_request
def require_admin():
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if request.endpoint in LOGGED_IN_ENDPOINTS:
        return auth_tools.login_required(_allow)()
    return auth_tools.admin_required(_allow)()


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
    order_line = OrderLine.query.filter_by(id=id).first_or_404()
    order = order_line.order
    if not current_user.is_admin and (order is None or order.user_id != current_user.id):
        abort(403)
    order_line.delete()
    return True


@bp.route("/delete_player/<id>", methods=["POST"])
def delete_player(id):
    player = Player.query.filter_by(id=id).first()
    for association in player.divisions_relations:
        association.delete()
    player.delete()
    return True


@bp.route("/delete_tournament/<id>", methods=["POST"])
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

    if request.is_json:
        data = request.get_json() or {}
        values = data.get("values", {})
    else:
        form = obj.get_edit_form()
        values = form.set_values(request)

    if values:
        obj.update_with_dict(values)
        obj.save()

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


@bp.route("/remove_relationship", methods=["POST"])
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
    # The editor fetches this, then downloads the URL it returns. The CSV used
    # to be written under static/ (publicly served); it is now built in memory
    # by csv_file, behind the same admin check.
    if model not in MODELS:
        abort(404)
    return url_for("api.csv_file", model=model)


@bp.get("/csv/<model>.csv")
def csv_file(model):
    model_cls = MODELS.get(model)
    if not model_cls:
        abort(404)
    rows = [
        {k: v for k, v in instance.get_dict().items() if k not in CSV_EXCLUDED_COLUMNS}
        for instance in model_cls.query.all()
    ]
    out = io.StringIO()
    if rows:
        writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return Response(
        out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={model}.csv"},
    )


@bp.route("/upload_csv_to_db/<model>", methods=["POST"])
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
