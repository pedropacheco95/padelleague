from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import inspect

from padel_league.models import Product , Order , User

bp = Blueprint('shop', __name__,url_prefix='/shop')

@bp.route('/', methods=('GET', 'POST'))
def index():
    products = Product.query.all()
    return render_template('shop/home.html',products=products)

@bp.route('/cart/<order_id>', methods=('GET', 'POST'))
def cart(order_id):
    user = session.get('user')
    error = None
    if not user:
        error = 'Não podes aceder ao carrinho sem estar logado'
    if order_id is None:
        #Check if user has an open order
        if not [order for order in user.orders if not order.closed]:
            order = Order(user_id=user.id)
            order.add_to_session()
        else:
            order = [order for order in user.orders if not order.closed][-1]
        return redirect(url_for('shop.cart',order_id=order.id))
    order = Order.query.get(order_id)
    if user and user.id != order.user_id:
        error = 'Não podes aceder a carrinho que não são teus'
    if error is not None:
        flash(error)
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        order.closed = True
        for order_line in order.order_lines:
            new_quantity = request.form['orderline_{id}'.format(id = order_line.id)]
            order_line.quantity = new_quantity
            order_line.save()
        new_order = Order(user_id=user.id)
        #Also commits the order right?
        new_order.create()
        #Should refresh the user so it would be calculated again?

        return redirect(url_for('shop.cart_sucess'))
    return render_template('shop/cart.html',order=order)

@bp.route('/cart_sucess', methods=('GET', 'POST'))
def cart_sucess():
    return render_template('shop/cart_sucess.html')