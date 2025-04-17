from .sql_db import db
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import class_mapper
from sqlalchemy.ext.hybrid import hybrid_property
from flask import url_for

from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, inspect
from sqlalchemy.orm import relationship

Base = declarative_base()

class Model():

    _name = None
    _description = None
    __tablename__ = None

    def __repr__(self):
        try:
            return f"{self.model_name}: {self.name}"
        except:
            ValueError('This model has no defined name, choose another way of representing')
    
    def __str__(self):
        try:
            return f"{self.model_name}: {self.name}"
        except:
            ValueError('This model has no defined name, choose another way of representing')

    def create(self):
        db.session.add(self)
        db.session.commit()
        return True

    def add_to_session(self):
        db.session.add(self)
        return True

    def delete(self):
        db.session.delete(self)
        db.session.commit()
        return True

    def save(self):
        db.session.commit()
        return True

    def logout(self):
        db.session.expunge_all()
        db.session.close()
        return True
    
    def refresh(self):
        db.session.refresh(self)
        return True

    def expire(self):
        db.session.expire(self)
        return True

    def merge(self):
        new = db.session.merge(self)
        db.session.commit()
        return new

    def flush(self):
        db.session.flush(self)
        return True

    def get_table(self,model):
        return db.session.query(self.table_object(table_name=model))

    def table_object(self,table_name):
        tables_dict = {table.__tablename__: table for table in db.Model.__subclasses__()}
        return tables_dict.get(table_name)

    def all_tables_object(self):
        return {table.__tablename__: table for table in db.Model.__subclasses__()}

    def get_all_tables(self):
        return {table.__tablename__: db.session.query(table) for table in db.Model.__subclasses__()}

    def update_with_dict(self,values):
        relationships = class_mapper(type(self)).relationships
        for key in values.keys():
            if key in relationships.keys():
                if values[key]:
                    relationship = relationships[key]
                    relationship_type = relationship.direction.name
                    if key == 'imageable':
                        if values[key]:
                            images = getattr(self, 'images')
                            if images:
                                images.clear()
                            for image in values[key]:
                                images.append(image)
                    elif relationship_type == 'MANYTOONE':
                        obj = self.get_related_object(key)
                        related_instance = obj.query.filter(obj.id.in_(values[key])).first()
                        #related_instance = self.get_related_object(key).query.filter_by(id=values[key]).first()
                        if getattr(self,key) != related_instance:
                            setattr(self,key,related_instance)
                    elif relationship_type in ['MANYTOMANY','ONETOMANY']:
                        obj = self.get_related_object(key)
                        instances = obj.query.filter(obj.id.in_(values[key])).all()
                        field = getattr(self,key)
                        for instance in instances:
                            if instance not in field:
                                field.append(instance)

            elif isinstance(getattr(self,key),bool) and values[key] != getattr(self,key) :
                setattr(self,key,values[key])

            elif values[key] is not None and values[key] != getattr(self,key):
                setattr(self,key,values[key])
            else:
                mapper = inspect(self.__class__)
                column = mapper.columns.get(key)
                #Deal with unset boolean values
                if column is not None and isinstance(column.type, Boolean) and values[key] != getattr(self, key):
                    setattr(self,key,values[key])
        self.save()
        return True

    def get_related_object(self,field_name):
        return getattr(self.__class__, field_name).property.mapper.entity
    
    def get_create_form(self):
        # Define this method in each derived class
        raise NotImplementedError
    
    def display_all_info(self):
        # Define this method in each derived class
        raise NotImplementedError
    
    def get_basic_create_form(self):
        # Define this method in each derived class
        raise NotImplementedError

    def get_display_all_data(self):
        searchable_column , table_columns = self.display_all_info()
        data = {
            'dispalay_all_url': url_for('editor.display_all', model=self.model_name),
            'title': self.page_title,
            'create_url': url_for('editor.create', model=self.model_name),
            'searchable_column': searchable_column,
            'table_columns': table_columns,
            'objects': self.query.all(),
            'general_delete_url': url_for('api.delete', model=self.model_name, id=''),
            'download_csv_url': url_for('api.download_csv', model=self.model_name),
            'upload_csv_url': url_for('api.upload_csv_to_db', model=self.model_name),
        }
        return data
    
    def get_edit_form(self):
        form = self.get_create_form()
        for field in form.fields:
            field.value = getattr(self, field.name)
        return form

    def get_display_data(self):
        data = {
            'dispalay_all_url': url_for('editor.display_all', model=self.model_name),
            'title': self.page_title,
            'post_url': url_for('api.edit', model=self.model_name, id=self.id),
            'delete_url': url_for('api.delete', model=self.model_name, id=self.id),
            'form': self.get_edit_form().get_form_dict(),
        }
        return data

    def get_create_data(self,form = None):
        if not form:
            form = self.get_create_form()
        data = {
            'dispalay_all_url': url_for('editor.display_all', model=self.model_name),
            'title': self.page_title,
            'post_url': url_for('editor.create', model=self.model_name),
            'form': form.get_form_dict(),
        }
        return data
    
    def get_basic_create_data(self,form = None):
        if not form:
            form = self.get_basic_create_form()
        data = {
            'post_url': url_for('api.modal_create_page', model=self.model_name),
            'form': form.get_form_dict(),
        }
        return data

    def editor_url(self):
        return url_for('editor.display', model=self.model_name, id=self.id)
    
    def get_dict(self):
        instance_dict = {c.name: getattr(self, c.name) for c in self.__table__.columns}

        for key, value in self.__class__.__dict__.items():
            if isinstance(value, hybrid_property):
                instance_dict[key] = getattr(self, key)
        return instance_dict
    
    def get_model_names(self):
        print(':::::::::::::::::::::::::::::::')
        print(':::::::::::::::::::::::::::::::')
        print(self.all_tables_object().values())
        print(':::::::::::::::::::::::::::::::')
        print(':::::::::::::::::::::::::::::::')
        return [obj.model_name for obj in self.all_tables_object().values() if hasattr(obj, 'model_name')]

class Image(db.Model, Base):
    __tablename__ = 'images'
    id = Column(Integer, primary_key=True)
    filename = Column(String)
    imageable_id = Column(Integer, ForeignKey('imageables.imageable_id'))
    imageable = relationship('Imageable', back_populates='images')

    def create(self):
        db.session.add(self)
        db.session.commit()
        return True

    def add_to_session(self):
        db.session.add(self)
        return True

    def delete(self):
        db.session.delete(self)
        db.session.commit()
        return True

    def save(self):
        db.session.commit()
        return True

class Imageable(db.Model, Base):
    __tablename__ = 'imageables'
    imageable_id = Column(Integer, primary_key=True)
    type = Column(String(50))
    __mapper_args__ = {
        'polymorphic_identity': 'imageable',
        'polymorphic_on': type
    }
    images = relationship('Image', back_populates='imageable', cascade="all")

    def create(self):
        db.session.add(self)
        db.session.commit()
        return True
    
    def delete(self):
        db.session.expunge(self)
        db.session.delete(self)
        db.session.commit()
        return True
    