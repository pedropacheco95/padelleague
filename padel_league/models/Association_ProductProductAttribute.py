from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer, ForeignKey, Enum 
from sqlalchemy.orm import relationship 

class Association_ProductProductAttribute(db.Model ,model.Model, model.Base):
    __tablename__ = 'product_attributes_in_product'
    __table_args__ = {'extend_existing': True}
    product_id = Column(Integer, ForeignKey('products.id'), primary_key=True)
    product_attribute_id = Column(Integer, ForeignKey('product_attributes.id'), primary_key=True)

    product_attribute = relationship('ProductAttribute', back_populates='products_relations')
    product = relationship('Product', back_populates='product_attributes_relations')
