from . import auth
from . import main


def register_api_blueprints(app):
    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)


__all__ = ["auth", "main"]
