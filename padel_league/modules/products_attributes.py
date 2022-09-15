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


@bp.route('/edit', methods=('GET', 'POST'))
@bp.route('/edit/<id>', methods=('GET', 'POST'))
def edit(id=None):
    if not id:
        product_attributes = ProductAttribute.query.all()
        return render_template('product_attributes/edit_choose.html',product_attributes=product_attributes)
    product_attribute = ProductAttribute.query.filter_by(id=id).first()
    if request.method == 'POST':
        name = request.form['name']
        user_input = True if request.form.get('user_input') == 'on' else False
    
        values = request.form.getlist('attribute_value_name')

        if name != product_attribute.name and name:
            product_attribute.name = name
        if user_input != product_attribute.user_input:
            product_attribute.user_input = user_input

        product_attribute.save()
        for value in values:
            exists = ProductAttributeValue.query.filter_by(value=value).first()
            if not exists:
                product_value = ProductAttributeValue(value=value,product_attribute_id=product_attribute.id)
                product_value.create()

        return redirect(url_for('product_attributes.edit.html'))
    return render_template('product_attributes/edit.html',product_attribute=product_attribute)


@bp.route('/delete/<id>', methods=('GET', 'POST'))
def delete(id):
    product_attribute = ProductAttribute.query.get(id)
    for value in product_attribute.values:
        value.delete()
    product_attribute.delete()
    return redirect(url_for('main.index'))
