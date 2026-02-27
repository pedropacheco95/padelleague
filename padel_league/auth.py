from padel_league.models import User


def register_jwt_handlers(jwt):

    @jwt.unauthorized_loader
    def unauthorized(reason):
        return {"error": "Missing or invalid token"}, 401

    @jwt.invalid_token_loader
    def invalid(reason):
        return {"error": "Invalid token"}, 422

    @jwt.expired_token_loader
    def expired(jwt_header, jwt_payload):
        return {"error": "Token expired"}, 401


def setup_login_manager(login_manager):
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
