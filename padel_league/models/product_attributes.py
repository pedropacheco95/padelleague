from sqlalchemy import Boolean, Column, Integer, Text
from sqlalchemy.orm import relationship

from padel_league import model
from padel_league.sql_db import db


class ProductAttribute(db.Model, model.Model):
    __tablename__ = "product_attributes"
    __table_args__ = {"extend_existing": True}
    page_title = "Atributos de produto"
    model_name = "ProductAttribute"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text)
    user_input = Column(
        Boolean, default=False
    )  # Assumed to be a text input; example: Name on shirt: ________

    values = relationship("ProductAttributeValue", back_populates="product_attribute")
    products_relations = relationship(
        "Association_ProductProductAttribute", back_populates="product_attribute"
    )
