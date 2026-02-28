from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from padel_league import model
from padel_league.sql_db import db
from padel_league.tools.input_tools import Block, Field, Form


class Association_ProductProductAttributeValue(db.Model, model.Model):
    __tablename__ = "product_attribute_values_in_product"
    __table_args__ = {"extend_existing": True}
    page_title = "Relação de Produto e valor de atributo"
    model_name = "Association_ProductProductAttributeValue"

    id = Column(Integer, primary_key=True, autoincrement=True)

    product_id = Column(Integer, ForeignKey("products.id"), primary_key=True)
    product_attribute_value_id = Column(
        Integer, ForeignKey("product_attribute_values.id"), primary_key=True
    )

    product_attribute_value = relationship(
        "ProductAttributeValue", back_populates="products_relations"
    )
    product = relationship(
        "Product", back_populates="product_attribute_values_relations"
    )

    def display_all_info(self):
        searchable_column = {"field": "product", "label": "Produto"}
        table_columns = [
            searchable_column,
            {"field": "product_attribute_value", "label": "Valor de atributo"},
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
                name="product",
                label="Produto",
                type="ManyToOne",
                required=True,
                related_model="Product",
            ),
            get_field(
                name="product_attribute_value",
                label="Valor de atributo",
                type="ManyToOne",
                required=True,
                related_model="ProductAttributeValue",
            ),
        ]
        info_block = Block("info_block", fields)
        form.add_block(info_block)
        return form
