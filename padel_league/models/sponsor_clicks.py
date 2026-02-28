from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from padel_league import model
from padel_league.sql_db import db
from padel_league.tools.input_tools import Block, Field, Form


class SponsorClick(db.Model, model.Model):
    __tablename__ = "sponsor_clicks"
    __table_args__ = {"extend_existing": True}

    page_title = "Sponsor Clicks"
    model_name = "SponsorClick"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    sponsor_id = Column(Integer, ForeignKey("sponsors.id"), nullable=False)
    sponsor = relationship("Sponsor", back_populates="sponsor_clicks")

    ip_address = Column(String(45))
    user_agent = Column(Text)
    referer = Column(Text)
    session_id = Column(String(128))
    from_page = Column(String(255))

    def display_all_info(self):
        searchable_column = {"field": "sponsor_id", "label": "Sponsor ID"}
        table_columns = [
            searchable_column,
            {"field": "created_at", "label": "Click Timestamp"},
            {"field": "ip_address", "label": "IP"},
            {"field": "referer", "label": "Referer"},
            {"field": "user_agent", "label": "User Agent"},
            {"field": "from_page", "label": "User Agent"},
        ]
        return searchable_column, table_columns

    def get_create_form(self):
        def get_field(name, label, type, required=False, related_model=None):
            return Field(
                instance_id=getattr(self, "id", None),
                model=self.model_name,
                name=name,
                label=label,
                type=type,
                required=required,
                related_model=related_model,
            )

        form = Form()
        fields = [
            get_field(
                name="sponsor",
                label="Sponsor",
                type="ManyToOne",
                required=True,
                related_model="Sponsor",
            ),
            get_field(name="created_at", label="Click Timestamp", type="DateTime"),
            get_field(name="ip_address", label="IP", type="Text"),
            get_field(name="user_agent", label="User Agent", type="Text"),
            get_field(name="referer", label="Referer", type="Text"),
            get_field(name="session_id", label="Session ID", type="Text"),
            get_field(name="from_page", label="From Page", type="Text"),
        ]
        info_block = Block("info_block", fields)
        form.add_block(info_block)
        return form
