from .sql_db import db
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.sql import text

Base = declarative_base()

class Model():

    _name = None
    _description = None
    __tablename__ = None

    def create(self):
        db.session.add(self)
        db.session.commit()
        return True

    def delete(self):
        db.session.delete(self)
        db.session.commit()
        return True

    def save(self):
        db.session.commit()
        return True

    def refresh(self):
        db.session.refresh(self)
        return True

    def get_table(self,model):
        return db.session.query(self.table_object(table_name=model))

    def table_object(self,table_name):
        tables_dict = {table.__tablename__: table for table in db.Model.__subclasses__()}
        return tables_dict.get(table_name)
