from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer , Text ,ForeignKey
from sqlalchemy.orm import relationship
from padel_league.tools.input_tools import Field, Block , Form

class ProductImage(db.Model ,model.Model):
    __tablename__ = 'product_images'
    __table_args__ = {'extend_existing': True}
    page_title = 'Images de Produto'
    model_name = 'ProductImage'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    path = Column(Text)
    product_id = Column(Integer, ForeignKey('products.id'))

    product = relationship('Product', back_populates="images")

    def display_all_info(self):
        searchable_column = {'field': 'name', 'label': 'Nome'}
        table_columns = [
            searchable_column,
            {'field': 'path', 'label': 'Path'},
            {'field': 'product', 'label': 'Produto'},
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
            get_field(name='path', label='Path', type='Text', required=True),
            get_field(name='product', label='Produto', type='ManyToOne', required=True, related_model='Product'),
        ]
        info_block = Block('info_block', fields)
        form.add_block(info_block)

        return form