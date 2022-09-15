from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
import os
import unidecode

from padel_league.models import Product , ProductAttribute , Association_ProductProductAttribute , Association_ProductProductAttributeValue , ProductImage , ProductAttributeValue , OrderLine
from padel_league.tools import image_tools

bp = Blueprint('products', __name__,url_prefix='/products')

@bp.route('/create', methods=('GET', 'POST'))
def create():
    if request.method == 'POST':

        name = request.form['name']
        price = request.form['price']
        small_description = request.form['small_description']
        big_description = request.form['big_description']
        features = request.form.getlist('features')
        features = [feature.split(': ') for feature in features if feature]

        features = {feature[0]:feature[1] for feature in features}

        product = Product(name=name,price=price,small_description=small_description,big_description=big_description,features=features)
        product.create()

        attributes = request.form.getlist('attribute')
        attribute_values = request.form.getlist('value')

        for attribute in attributes:
            if attribute:
                association = Association_ProductProductAttribute(product_id=product.id,product_attribute_id=int(attribute))
                association.create()

        for value in attribute_values:
            if value:
                association = Association_ProductProductAttributeValue(product_id=product.id,product_attribute_value_id=int(value))
                association.create()

        final_files = request.files.getlist('finalFile')
        for index in range(len(final_files)):
            file = final_files[index]
            if file.filename != '':
                image_name = str(product.name).replace(" ", "").lower()
                image_name = unidecode.unidecode(image_name)
                image_name = '{image_name}_{product_id}_{index}.png'.format(image_name=image_name,product_id=product.id,index=index)

                filename = os.path.join('products',image_name)

                image_tools.save_file(file, filename)
                #image_tools.remove_background(filename)
                image_tools.resize(filename, 500, 500)
                
                product_image = ProductImage(path=filename,product_id=product.id)
                product_image.create()


        return redirect(url_for('main.index'))
    attributes = ProductAttribute.query.all()
    return render_template('products/create.html',attributes=attributes)

@bp.route('/<id>', methods=('GET', 'POST'))
def show(id):
    product = Product.query.get(id)
    if request.method == 'POST':
        user = session.get('user')
        error = None
        if not user:
            error = 'Tens de estar logado para poder adicionar produtos ao carrinho'
            
        if error is None:
            values = {}
            for relation in product.product_attributes_relations:
                attribute = relation.product_attribute
                value = request.form[attribute.name]
                if value:
                    if attribute.user_input:
                        values[attribute.name] = value
                    else:
                        values[attribute.name] = ProductAttributeValue.query.get(int(value)).value
            values_string = ['{key}: {value}'.format(key=key,value=values[key]) for key in values.keys()]
            specification = '; '.join(values_string)
            order = [order for order in user.orders if not order.closed][-1]

            if order:
                order_line = OrderLine(product_id=product.id,order_id=order.id,quantity=1,specification=specification)
                all_order_lines = OrderLine.query.filter_by(order_id=order.id).all()
                if order_line in all_order_lines:
                    order_line = all_order_lines[all_order_lines.index(order_line)]
                    order_line.quantity += 1
                    order_line.save()
                else:
                    order_line.create()
            return redirect(url_for('shop.cart',order_id = order.id))
        flash(error)
    return render_template('products/product.html',product=product)

@bp.route('/delete/<id>', methods=('GET', 'POST'))
def delete(id):
    product = Product.query.get(id)
    product.delete()
    return redirect(url_for('main.index'))