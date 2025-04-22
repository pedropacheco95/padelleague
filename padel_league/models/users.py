from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer , String , Text , ForeignKey , Boolean
from sqlalchemy.orm import relationship
from padel_league.tools.input_tools import Field, Block , Form

from flask_login import UserMixin

class User(db.Model , UserMixin, model.Model, model.Base):
    __tablename__ = 'users'
    __table_args__ = {'extend_existing': True}
    page_title = 'Users'
    model_name = 'User'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(80), unique=True, nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    password = Column(Text, nullable=False)
    is_admin = Column(Boolean, default=False)
    generated_code = Column(Integer)
    player_id = Column(Integer, ForeignKey('players.id'))

    player = relationship('Player', back_populates="user")
    
    orders = relationship('Order', back_populates="user")
        
    def display_all_info(self):
        searchable_column = {'field': 'username', 'label': 'Username'}
        table_columns = [
            searchable_column,
            {'field': 'email', 'label': 'Email'},
            {'field': 'is_admin', 'label': 'Administrador?'},
            {'field': 'player', 'label': 'Jogador Associado'},
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
            get_field(name='username', label='Username', type='Text', required=True),
            get_field(name='email', label='Email', type='Text', required=True),
            get_field(name='password', label='Password', type='Password', required=True),
            get_field(name='is_admin', label='Administrador?', type='Boolean'),
            get_field(name='generated_code', label='Código Gerado', type='Integer'),
            get_field(name='player', label='Jogador Associado', type='ManyToOne', related_model='Player'),
        ]
        info_block = Block('info_block', fields)
        form.add_block(info_block)

        return form
