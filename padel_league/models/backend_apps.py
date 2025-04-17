from flask import url_for
from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer , String , Text , ForeignKey , Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from padel_league.tools.input_tools import Field, Block, Tab , Form

class Backend_App(db.Model ,model.Model,model.Base):
    __tablename__ = 'backend_app'
    __table_args__ = {'extend_existing': True}
    page_title = 'Aplicações de backend'
    model_name = 'Backend_App'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False, unique=True)
    app_model_name = Column(String(80), nullable=False, unique=True)
    app_image = Column(String(200))
    color = Column(String(10))

    @hybrid_property
    def style(self):
        return f"style=background-color:{self.color}"
    
    @hybrid_property
    def url(self):
        try:
            return url_for('editor.display_all',model=self.app_model_name)
        except:
            '/editor/display'

    @hybrid_property
    def image_filename(self):
        return f'images/{self.app_image}' if self.app_image else 'images/default_app_image.png'


    def display_all_info(self):
        searchable_column = {'field': 'name','label':'Nome'}
        table_columns = [
            {'field': 'id','label':'Numero'},
            searchable_column,
            {'field': 'app_image','label':'App Image'},
        ]
        return searchable_column , table_columns

    def get_create_form(self):
        def get_field(name,label,type,required=False,related_model=None,options=None,value=None):
            return Field(instance_id=self.id,model=self.model_name,name=name,label=label,type=type,required=required,related_model=related_model,options=options,value=value)
        form = Form()
        # Create Picture block
        fields = [get_field(name='app_image',label='Icone da app',type='Picture')]
        picture_block = Block('picture_block',fields)
        form.add_block(picture_block)
   
        # Create Info block
        fields = [
            get_field(name='app_model_name' ,label='Nome do modelo', type='Select', required=True, options=self.get_model_names()),
            get_field(name='name' ,label='Nome', type='Text', required=True),
            get_field(name='color',label='Cor', type='Color', required=True),
        ]
        info_block = Block('info_block',fields)
        form.add_block(info_block)

        return form