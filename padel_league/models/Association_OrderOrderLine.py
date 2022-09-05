from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer, ForeignKey, Float
from sqlalchemy.orm import relationship 

class Association_OrderOrderLine(db.Model ,model.Model, model.Base):
    __tablename__ = 'lines_in_order'
    __table_args__ = {'extend_existing': True}
    order_id = Column(Integer, ForeignKey('orders.id'), primary_key=True)
    order_line_id = Column(Integer, ForeignKey('order_lines.id'), primary_key=True)

    order = relationship('Order', back_populates='order_line_relations')
    order_line = relationship('OrderLine', back_populates='order_relations')
