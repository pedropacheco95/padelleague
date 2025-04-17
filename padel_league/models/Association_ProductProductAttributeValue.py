from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer, ForeignKey 
from sqlalchemy.orm import relationship 

class Association_ProductProductAttributeValue(db.Model ,model.Model, model.Base):
    __tablename__ = 'product_attribute_values_in_product'
    __table_args__ = {'extend_existing': True}
    page_title = 'Relação de Produto e valor de atributo'
    model_name = 'Association_ProductProductAttributeValue'
    
    product_id = Column(Integer, ForeignKey('products.id'), primary_key=True)
    product_attribute_value_id = Column(Integer, ForeignKey('product_attribute_values.id'), primary_key=True)

    product_attribute_value = relationship('ProductAttributeValue', back_populates='products_relations')
    product = relationship('Product', back_populates='product_attribute_values_relations')
