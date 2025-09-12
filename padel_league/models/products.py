from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer , String , Text , ForeignKey , Float ,JSON
from sqlalchemy.orm import relationship
import json
from padel_league.tools.input_tools import Field, Block , Form

class Product(db.Model ,model.Model):
    __tablename__ = 'products'
    __table_args__ = {'extend_existing': True}
    page_title = 'Produtos'
    model_name = 'Product'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(80), unique=True, nullable=False)
    price = Column(Float, nullable=False)
    small_description = Column(Text, nullable=True)
    big_description = Column(Text, nullable=True)
    features = Column(JSON, nullable=True)
    
    images = relationship('ProductImage', back_populates="product")
    order_lines = relationship('OrderLine', back_populates="product")
    product_attributes_relations = relationship('Association_ProductProductAttribute', back_populates="product")
    product_attribute_values_relations = relationship('Association_ProductProductAttributeValue', back_populates="product")

    def get_big_description_list(self):
        return self.big_description.split('. ')

    def dict_of_values(self):
        values_in_dict = {}
        for relation in self.product_attributes_relations:
            attribute = relation.product_attribute
            values_in_dict[attribute] = []

        for relation in self.product_attribute_values_relations:
            value = relation.product_attribute_value
            attribute = value.product_attribute
            values_in_dict[attribute].append((value.id,value.value))
        return values_in_dict
    
    @property
    def product_features(self):
        if isinstance(self.features, str):
            try:
                return json.loads(self.features)
            except Exception:
                return {}
        return self.features
    
    def display_all_info(self):
        searchable_column = {'field': 'name', 'label': 'Nome'}
        table_columns = [
            searchable_column,
            {'field': 'price', 'label': 'Preço'},
            {'field': 'small_description', 'label': 'Descrição Curta'},
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
                related_model=related_model
            )

        form = Form()

        fields = [
            get_field(name='name', label='Nome', type='Text', required=True),
            get_field(name='price', label='Preço', type='Float', required=True),
            get_field(name='small_description', label='Descrição Curta', type='Text'),
            get_field(name='big_description', label='Descrição Longa', type='Text'),
            get_field(name='images', label='Descrição Longa', type='OneToMany'),
        ]
        info_block = Block('info_block', fields)
        form.add_block(info_block)

        return form
