from sqlalchemy import Column, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from padel_league import model
from padel_league.sql_db import db


class ProductAttributeValue(db.Model, model.Model):
    __tablename__ = "product_attribute_values"
    __table_args__ = {"extend_existing": True}
    page_title = "Valores de atributos de produtos"
    model_name = "ProductAttributeValue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    value = Column(Text)
    product_attribute_id = Column(Integer, ForeignKey("product_attributes.id"))

    product_attribute = relationship("ProductAttribute", back_populates="values")

    products_relations = relationship(
        "Association_ProductProductAttributeValue",
        back_populates="product_attribute_value",
    )
