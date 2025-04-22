from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer , Text ,ForeignKey
from sqlalchemy.orm import relationship

class ProductImage(db.Model ,model.Model,model.Base):
    __tablename__ = 'product_images'
    __table_args__ = {'extend_existing': True}
    page_title = 'Images de Produto'
    model_name = 'ProductImage'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    path = Column(Text)
    product_id = Column(Integer, ForeignKey('products.id'))

    product = relationship('Product', back_populates="images")
