from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer , String , Text , ForeignKey , Boolean
from sqlalchemy.orm import relationship

from flask_login import UserMixin

class User(db.Model , UserMixin, model.Model, model.Base):
    __tablename__ = 'users'
    __table_args__ = {'extend_existing': True}
    page_title = 'Users'
    model_name = 'User'
    
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    password = Column(Text, nullable=False)
    is_admin = Column(Boolean, default=False)
    generated_code = Column(Integer)
    player_id = Column(Integer, ForeignKey('players.id'))

    player = relationship('Player', back_populates="user")
    
    orders = relationship('Order', back_populates="user")