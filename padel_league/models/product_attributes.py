from email.policy import default
from xmlrpc.client import Boolean
from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer , Text , Boolean
from sqlalchemy.orm import relationship

class ProductAttribute(db.Model ,model.Model,model.Base):
    __tablename__ = 'product_attributes'
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True)
    name = Column(Text)
    user_input = Column(Boolean, default=False) # Assumed to be a text input; example: Name on shirt: ________ 

    values = relationship('ProductAttributeValue', back_populates="product_attribute")
    products_relations = relationship('Association_ProductProductAttribute', back_populates="product_attribute")
