from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer , String , Text , ForeignKey , Boolean, Date
from sqlalchemy.orm import relationship
from padel_league.tools.input_tools import Field, Block , Form
from sqlalchemy.ext.hybrid import hybrid_property


class Newsletter(db.Model, model.Model, model.Base):
    __tablename__ = 'newsletters'
    __table_args__ = {'extend_existing': True}
    page_title = 'Newsletters'
    model_name = 'Newsletter'

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(120), unique=True, nullable=False)
    date = Column(Date, nullable=False)
    image_path = Column(String(120), default='Newsletters/default_newsletter.jpg')
    
    @hybrid_property
    def name(self):
        return f"{self.title}"
