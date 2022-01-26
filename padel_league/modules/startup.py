from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from padel_league.models import User

def add_to_session():
    #ADD NECESSARY THINGS TO SESSION
    return 0