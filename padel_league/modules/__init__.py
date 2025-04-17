from . import main
from . import players
from . import matches
from . import tournaments
from . import auth
from . import api
from . import startup
from . import uploads
from . import users
from . import news
from . import registrations
from . import products
from . import products_attributes
from . import shop
from . import editions
from . import editor

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
    return True