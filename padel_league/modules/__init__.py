from . import (
    api,
    auth,
    editions,
    editor,
    main,
    matches,
    news,
    players,
    products,
    products_attributes,
    registrations,
    shop,
    sponsors,
    tournaments,
    uploads,
    users,
    startup,
    chatbot_api,
)
from .frontend_api.v1 import auth as api_v1_auth
from .frontend_api.v1 import main as api_v1_main


# Register Blueprints
def register_blueprints(app):
    app.register_blueprint(main.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(players.bp)
    app.register_blueprint(tournaments.bp)
    app.register_blueprint(matches.bp)
    app.register_blueprint(uploads.bp)
    app.register_blueprint(users.bp)
    app.register_blueprint(news.bp)
    app.register_blueprint(registrations.bp)
    app.register_blueprint(products.bp)
    app.register_blueprint(products_attributes.bp)
    app.register_blueprint(shop.bp)
    app.register_blueprint(editions.bp)
    app.register_blueprint(editor.bp)
    app.register_blueprint(sponsors.bp)
    app.register_blueprint(chatbot_api.bp)

    app.register_blueprint(api_v1_auth.bp)
    app.register_blueprint(api_v1_main.bp)

    return True


__all__ = [
    "api",
    "auth",
    "editions",
    "editor",
    "main",
    "matches",
    "news",
    "players",
    "products",
    "products_attributes",
    "registrations",
    "shop",
    "sponsors",
    "tournaments",
    "uploads",
    "users",
    "startup",
    "chatbot_api",
]
