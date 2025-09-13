from sqlalchemy import Boolean, Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from padel_league import model
from padel_league.sql_db import db
from padel_league.tools.input_tools import Block, Field, Form


class Order(db.Model, model.Model):
    __tablename__ = "orders"
    __table_args__ = {"extend_existing": True}
    page_title = "Encomendas"
    model_name = "Order"

    id = Column(Integer, primary_key=True, autoincrement=True)
    closed = Column(Boolean, default=False)
    delivered = Column(Boolean, default=False)
    user_id = Column(Integer, ForeignKey("users.id"))

    user = relationship("User", back_populates="orders")

    order_lines = relationship("OrderLine", back_populates="order")

    def display_all_info(self):
        searchable_column = {"field": "user", "label": "Utilizador"}
        table_columns = [
            searchable_column,
            {"field": "closed", "label": "Fechada?"},
            {"field": "delivered", "label": "Entregue?"},
        ]
        return searchable_column, table_columns

    def get_create_form(self):
        def get_field(name, label, type, required=False, related_model=None):
            return Field(
                instance_id=self.id,
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
                name="user",
                label="Utilizador",
                type="ManyToOne",
                required=True,
                related_model="User",
            ),
            get_field(name="closed", label="Fechada?", type="Boolean"),
            get_field(name="delivered", label="Entregue?", type="Boolean"),
        ]
        info_block = Block("info_block", fields)
        form.add_block(info_block)

        return form
