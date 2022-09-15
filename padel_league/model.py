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
