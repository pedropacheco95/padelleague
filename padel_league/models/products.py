from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer , String , Text , ForeignKey , Float
from sqlalchemy.orm import relationship

class Product(db.Model ,model.Model,model.Base):
    __tablename__ = 'products'
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True)
    name = Column(String(80), unique=True, nullable=False)
    price = Column(Float, nullable=False)
    pictures = Column(Text, nullable=True)
