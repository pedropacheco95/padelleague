from flask_login import UserMixin
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from padel_league import model
from padel_league.sql_db import db
from padel_league.tools.input_tools import Block, Field, Form


class User(db.Model, UserMixin, model.Model):
    __tablename__ = "users"
    __table_args__ = {"extend_existing": True}
    page_title = "Users"
    model_name = "User"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(80), unique=True, nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    password = Column(Text, nullable=False)
    is_admin = Column(Boolean, default=False)
    super_admin = Column(Boolean, default=False)
    generated_code = Column(Integer)
    # Wrong guesses at the current emailed code; the code dies after MAX_CODE_ATTEMPTS.
    code_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    player_id = Column(Integer, ForeignKey("players.id"))

    player = relationship("Player", back_populates="user")

    MAX_CODE_ATTEMPTS = 5

    def new_code(self):
        """A fresh 5-digit code for the forgot-password email. Not committed."""
        import secrets

        self.generated_code = 10000 + secrets.randbelow(90000)
        self.code_attempts = 0
        return self.generated_code

    def use_code(self, code):
        """True and the code is spent if it matches; a wrong guess counts. Not committed."""
        if self.generated_code is None:
            return False
        if code is not None and int(code) == self.generated_code:
            self.generated_code = None
            self.code_attempts = 0
            return True
        self.code_attempts = (self.code_attempts or 0) + 1
        if self.code_attempts >= self.MAX_CODE_ATTEMPTS:
            self.generated_code = None
        return False

    orders = relationship("Order", back_populates="user")

    def display_all_info(self):
        searchable_column = {"field": "username", "label": "Username"}
        table_columns = [
            searchable_column,
            {"field": "email", "label": "Email"},
            {"field": "is_admin", "label": "Administrador?"},
            {"field": "super_admin", "label": "Super Administrador?"},
            {"field": "player", "label": "Jogador Associado"},
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
                related_model=related_model,
            )

        form = Form()

        fields = [
            get_field(name="username", label="Username", type="Text", required=True),
            get_field(name="email", label="Email", type="Text", required=True),
            get_field(
                name="password", label="Password", type="Password", required=True
            ),
            get_field(name="is_admin", label="Administrador?", type="Boolean"),
            get_field(
                name="player",
                label="Jogador Associado",
                type="ManyToOne",
                related_model="Player",
            ),
            get_field(name="super_admin", label="Super Administrador?", type="Boolean"),
        ]
        info_block = Block("info_block", fields)
        form.add_block(info_block)

        return form

    def serialize(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "isAdmin": self.is_admin,
            "superAdmin": self.super_admin,
            "playerId": self.player_id,
        }
