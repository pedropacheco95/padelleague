from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from padel_league.models import ProductAttribute , ProductAttributeValue

bp = Blueprint('products_attributes', __name__,url_prefix='/products_attributes')

@bp.route('/create', methods=('GET', 'POST'))
def create():
    if request.method == 'POST':

        name = request.form['name']
        user_input = True if request.form.get('user_input') == 'on' else False
    
        values = request.form.getlist('attribute_value_name')

        product_attribute = ProductAttribute(name=name,user_input=user_input)
        product_attribute.create()
        for value in values:
            if value:
                product_value = ProductAttributeValue(value=value,product_attribute_id=product_attribute.id)
                product_value.create()

        return redirect(url_for('main.index'))
    return render_template('product_attributes/create.html')
