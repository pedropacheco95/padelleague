from sqlalchemy import Boolean, Column, Integer, Text
from sqlalchemy.orm import relationship

from padel_league import model
from padel_league.sql_db import db
from padel_league.tools.input_tools import Block, Field, Form


class ProductAttribute(db.Model, model.Model):
    __tablename__ = "product_attributes"
    __table_args__ = {"extend_existing": True}
    page_title = "Atributos de produto"
    model_name = "ProductAttribute"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text)
    user_input = Column(
        Boolean, default=False
    )  # Assumed to be a text input; example: Name on shirt: ________

    values = relationship("ProductAttributeValue", back_populates="product_attribute")
    products_relations = relationship(
        "Association_ProductProductAttribute", back_populates="product_attribute"
    )

    def display_all_info(self):
        searchable_column = {"field": "name", "label": "Nome"}
        table_columns = [
            searchable_column,
            {"field": "user_input", "label": "Input livre"},
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
            get_field(name="name", label="Nome", type="Text", required=True),
            get_field(name="user_input", label="Input livre", type="Boolean"),
            get_field(
                name="values",
                label="Valores",
                type="OneToMany",
                related_model="ProductAttributeValue",
            ),
        ]
        info_block = Block("info_block", fields)
        form.add_block(info_block)
        return form
