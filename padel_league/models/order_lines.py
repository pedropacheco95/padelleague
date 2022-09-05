from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer, ForeignKey, Enum 
from sqlalchemy.orm import relationship 

class OrderLine(db.Model ,model.Model, model.Base):
    __tablename__ = 'order_lines'
    __table_args__ = {'extend_existing': True}
    player_id = Column(Integer, ForeignKey('players.id'), primary_key=True)
    product_id = Column(Integer, ForeignKey('products.id'), primary_key=True)
    quantity = Column(Integer, nullable=False)

    product = relationship('Product', back_populates='players_relations')
    player = relationship('Player', back_populates='products_relations')

    order_relations = relationship('Association_OrderOrderLine', back_populates='order_line')