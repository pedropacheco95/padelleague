from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer, ForeignKey , Text
from sqlalchemy.orm import relationship 

class OrderLine(db.Model ,model.Model, model.Base):
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