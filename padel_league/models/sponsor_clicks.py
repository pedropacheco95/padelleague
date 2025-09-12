from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer, ForeignKey, DateTime, String, Text
from sqlalchemy.orm import relationship
from datetime import datetime

class SponsorClick(db.Model, model.Model):
    __tablename__ = 'sponsor_clicks'
    __table_args__ = {'extend_existing': True}

    page_title = 'Sponsor Clicks'
    model_name = 'SponsorClick'

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    sponsor_id = Column(Integer, ForeignKey('sponsors.id'), nullable=False)
    sponsor = relationship('Sponsor', back_populates="sponsor_clicks")

    ip_address = Column(String(45))
    user_agent = Column(Text)
    referer = Column(Text)
    session_id = Column(String(128))
    from_page = Column(String(255))
    
    def display_all_info(self):
        searchable_column = {'field': 'sponsor_id', 'label': 'Sponsor ID'}
        table_columns = [
            searchable_column,
            {'field': 'created_at', 'label': 'Click Timestamp'},
            {'field': 'ip_address', 'label': 'IP'},
            {'field': 'referer', 'label': 'Referer'},
            {'field': 'user_agent', 'label': 'User Agent'},
            {'field': 'from_page', 'label': 'User Agent'},
        ]
        return searchable_column, table_columns
