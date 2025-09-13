from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from padel_league.models import Order, Product

bp = Blueprint("shop", __name__, url_prefix="/shop")


@bp.route("/", methods=("GET", "POST"))
def index():
    products = Product.query.all()
    return render_template("shop/home.html", products=products)


@bp.route("/cart/<order_id>", methods=("GET", "POST"))
def cart(order_id):
    user = session.get("user")
    error = None
    if not user:
        error = "Não podes aceder ao carrinho sem estar logado"
    if order_id is None:
        # Check if user has an open order
        if not [order for order in user.orders if not order.closed]:
            order = Order(user_id=user.id)
            order.add_to_session()
        else:
            order = [order for order in user.orders if not order.closed][-1]
        return redirect(url_for("shop.cart", order_id=order.id))
    order = Order.query.get(order_id)
    if user and user.id != order.user_id:
        error = "Não podes aceder a carrinho que não são teus"
    if error is not None:
        flash(error)
        return redirect(url_for("main.index"))

    if request.method == "POST":
        order.closed = True
        for order_line in order.order_lines:
            new_quantity = request.form["orderline_{id}".format(id=order_line.id)]
            order_line.quantity = new_quantity
            order_line.save()
        new_order = Order(user_id=user.id)
        # Also commits the order right?
        new_order.create()
        # Should refresh the user so it would be calculated again?

        return redirect(url_for("shop.cart_sucess"))
    return render_template("shop/cart.html", order=order)


@bp.route("/cart_sucess", methods=("GET", "POST"))
def cart_sucess():
    return render_template("shop/cart_sucess.html")


@bp.route("/admin_orders", methods=("GET", "POST"))
def admin_orders():
    user = session.get("user")
    error = None

    if not user:
        error = "Não podes aceder ao carrinho sem estar logado"
        flash(error)
        return redirect(url_for("main.index"))

    if not user.is_admin:
        error = "Não podes ver esta página"
        flash(error)
        return redirect(url_for("main.index"))

    if request.method == "POST":
        order_id = request.form.get("order_id")
        delivered = request.form.get("delivered") == "true"

        order = Order.query.get(order_id)
        if order:
            order.delivered = delivered
            order.save()
            flash(
                f'Estado do pedido #{order.id} atualizado para {"Entregue" if delivered else "Não entregue"}.'
            )

        return redirect(url_for("shop.admin_orders"))

    orders = Order.query.order_by(Order.id.desc()).all()
    orders = [order for order in orders if order.order_lines]

    # Split into delivered and not delivered
    delivered_orders = [order for order in orders if order.delivered]
    undelivered_orders = [order for order in orders if not order.delivered]

    return render_template(
        "shop/admin_orders.html",
        delivered_orders=delivered_orders,
        undelivered_orders=undelivered_orders,
    )
