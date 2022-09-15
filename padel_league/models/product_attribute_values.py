from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer , Text ,ForeignKey
from sqlalchemy.orm import relationship

class ProductAttributeValue(db.Model ,model.Model,model.Base):
    __tablename__ = 'product_attribute_values'
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True)
    value = Column(Text)
    product_attribute_id = Column(Integer, ForeignKey('product_attributes.id'))

    product_attribute = relationship('ProductAttribute', back_populates="values")

    products_relations = relationship('Association_ProductProductAttributeValue', back_populates='product_attribute_value')
