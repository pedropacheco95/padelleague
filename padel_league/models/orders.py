from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer, ForeignKey, Enum 
from sqlalchemy.orm import relationship 

class Order(db.Model ,model.Model, model.Base):
    __tablename__ = 'orders'
    __table_args__ = {'extend_existing': True}

    order_line_relations = relationship('Association_OrderOrderLine', back_populates='order')
