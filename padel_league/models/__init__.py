from .leagues import League
from .editions import Edition
from .divisions import Division
from .users import User
from .players import Player
from .matches import Match
from .shuffle_tournaments import ShuffleTournament
from .shuffle_matches import ShuffleMatch
from .news import News
from .registrations import Registration
from .products import Product
from .product_images import ProductImage
from .product_attributes import ProductAttribute
from .product_attribute_values import ProductAttributeValue
from .orders import Order
from .order_lines import OrderLine
from .backend_apps import Backend_App
from .sponsors import Sponsor
from .sponsor_clicks import SponsorClick
from .Association_PlayerDivision import Association_PlayerDivision
from .Association_PlayerMatch import Association_PlayerMatch
from .Association_PlayerShuffleTournament import Association_PlayerShuffleTournament
from .Association_PlayerShuffleMatch import Association_PlayerShuffleMatch
from .Association_ProductProductAttribute import Association_ProductProductAttribute
from .Association_ProductProductAttributeValue import (
    Association_ProductProductAttributeValue,
)

MODELS = {
    "Backend_App": Backend_App,
    "League": League,
    "Edition": Edition,
    "Division": Division,
    "Player": Player,
    "Match": Match,
    "ShuffleTournament": ShuffleTournament,
    "ShuffleMatch": ShuffleMatch,
    "News": News,
    "Registration": Registration,
    "Product": Product,
    "User": User,
    "ProductImage": ProductImage,
    "ProductAttribute": ProductAttribute,
    "ProductAttributeValue": ProductAttributeValue,
    "Order": Order,
    "OrderLine": OrderLine,
    "Sponsor": Sponsor,
    "SponsorClick": SponsorClick,
    "Association_PlayerDivision": Association_PlayerDivision,
    "Association_PlayerMatch": Association_PlayerMatch,
    "Association_PlayerShuffleTournament": Association_PlayerShuffleTournament,
    "Association_PlayerShuffleMatch": Association_PlayerShuffleMatch,
    "Association_ProductProductAttribute": Association_ProductProductAttribute,
    "Association_ProductProductAttributeValue": Association_ProductProductAttributeValue,
}
