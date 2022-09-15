from email.policy import default
from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer, ForeignKey, Enum , Boolean
from sqlalchemy.orm import relationship 

class Order(db.Model ,model.Model, model.Base):
    __tablename__ = 'orders'
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True)
    closed = Column(Boolean, default=False)
    delivered = Column(Boolean, default=False)
    user_id = Column(Integer, ForeignKey('users.id'))

    user = relationship('User', back_populates="orders")

    order_lines = relationship('OrderLine', back_populates="order")