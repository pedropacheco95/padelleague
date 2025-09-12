from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer, ForeignKey , Text
from sqlalchemy.orm import relationship
from padel_league.tools.input_tools import Field, Block , Form


class OrderLine(db.Model ,model.Model):
    __tablename__ = 'order_lines'
    __table_args__ = {'extend_existing': True}
    page_title = 'Itens de encomenda'
    model_name = 'OrderLine'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.id'))
    product_id = Column(Integer, ForeignKey('products.id'))
    quantity = Column(Integer, nullable=False)
    specification = Column(Text)

    product = relationship('Product', back_populates='order_lines')
    order = relationship('Order', back_populates="order_lines")

    def __eq__(self, other):
        if isinstance(other, OrderLine):
            return self.product_id == other.product_id and self.order_id == other.order_id and self.specification == other.specification
        return False

    def get_specification_list(self):
        return self.specification.split('; ')
    
    def display_all_info(self):
        searchable_column = {'field': 'product', 'label': 'Produto'}
        table_columns = [
            {'field': 'order', 'label': 'Encomenda'},
            searchable_column,
            {'field': 'quantity', 'label': 'Quantidade'},
            {'field': 'specification', 'label': 'Especificações'},
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
            get_field(name='order', label='Encomenda', type='ManyToOne', required=True, related_model='Order'),
            get_field(name='product', label='Produto', type='ManyToOne', required=True, related_model='Product'),
            get_field(name='quantity', label='Quantidade', type='Integer', required=True),
            get_field(name='specification', label='Especificações', type='Text'),
        ]
        info_block = Block('info_block', fields)
        form.add_block(info_block)

        return form
