import os
import json
import functools
from datetime import datetime

from flask import (Flask, render_template, request, redirect, url_for,
                    session, flash, g)
from flask_login import (LoginManager, login_user, logout_user,
                          login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from models import db, User, Product, BuyerRequest, Order, Notification, Rating
from ai import price_recommender, quality_checker, product_matcher, transport_optimizer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-secret-change-me"
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(BASE_DIR, 'agrimarket.db')}"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ---------- i18n helper ----------
TRANSLATIONS = {}
for lang in ("en", "ta"):
    with open(os.path.join(BASE_DIR, "translations", f"{lang}.json"), encoding="utf-8") as f:
        TRANSLATIONS[lang] = json.load(f)


@app.before_request
def set_lang():
    g.lang = session.get("lang", "en")


def t(key):
    return TRANSLATIONS.get(g.lang, TRANSLATIONS["en"]).get(key, key)


app.jinja_env.globals.update(t=t)


@app.context_processor
def inject_globals():
    return {"lang": g.get("lang", "en"), "current_user": current_user}


@app.route("/set_language/<lang>")
def set_language(lang):
    if lang in TRANSLATIONS:
        session["lang"] = lang
        if current_user.is_authenticated:
            current_user.language = lang
            db.session.commit()
    return redirect(request.referrer or url_for("index"))


def role_required(role):
    def decorator(fn):
        @functools.wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            if current_user.role != role:
                flash("Access restricted.")
                return redirect(url_for("index"))
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ---------- Landing / Auth ----------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"].lower().strip()
        password = request.form["password"]
        role = request.form["role"]
        sub_type = request.form.get("sub_type")

        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists.")
            return redirect(url_for("register"))

        user = User(
            name=name, email=email,
            password_hash=generate_password_hash(password),
            role=role, sub_type=sub_type,
            language=session.get("lang", "en"),
        )
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect(url_for("farmer_dashboard" if role == "farmer" else "buyer_dashboard"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].lower().strip()
        password = request.form["password"]
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            session["lang"] = user.language or "en"
            return redirect(url_for("farmer_dashboard" if user.role == "farmer" else "buyer_dashboard"))
        flash("Invalid email or password.")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


# ---------- Farmer ----------
@app.route("/farmer/dashboard")
@role_required("farmer")
def farmer_dashboard():
    products = Product.query.filter_by(farmer_id=current_user.id).order_by(Product.created_at.desc()).all()
    total_expense = 0  # placeholder ledger hook
    orders = Order.query.filter_by(farmer_id=current_user.id).order_by(Order.created_at.desc()).limit(10).all()
    notifications = Notification.query.filter_by(user_id=current_user.id, is_read=False).all()
    return render_template("farmer_dashboard.html", products=products,
                            total_expense=total_expense, orders=orders,
                            notifications=notifications)


@app.route("/farmer/product/new", methods=["GET", "POST"])
@role_required("farmer")
def product_new():
    ai_price = None
    quality = None
    if request.method == "POST":
        name = request.form["name"]
        category = request.form["category"]
        description = request.form.get("description", "")
        quantity_kg = float(request.form["quantity_kg"])
        your_price = float(request.form["your_price"])

        photo_path = None
        quality_score, quality_grade = None, None
        file = request.files.get("photo")
        if file and file.filename:
            filename = secure_filename(f"{current_user.id}_{datetime.utcnow().timestamp()}_{file.filename}")
            save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(save_path)
            photo_path = f"uploads/{filename}"
            quality = quality_checker.check_quality(save_path)
            quality_score, quality_grade = quality["score"], quality["grade"]

        # Personalize AI price using this farmer's own past average sale price for the category
        past = (db.session.query(Product)
                .filter(Product.farmer_id == current_user.id, Product.category == category)
                .all())
        farmer_hist_avg = (sum(p.price_per_kg for p in past) / len(past)) if past else None

        ai_price = price_recommender.recommend_price(
            category, quantity_kg, quality_score or 75, farmer_hist_avg
        )

        product = Product(
            farmer_id=current_user.id, name=name, category=category,
            description=description, quantity_kg=quantity_kg,
            price_per_kg=your_price, ai_suggested_price=ai_price["suggested_price"],
            quality_score=quality_score, quality_grade=quality_grade,
            photo_path=photo_path, status="active",
        )
        db.session.add(product)
        db.session.commit()

        # Fulfil any matching open buyer requests (demand-sensing loop)
        open_requests = BuyerRequest.query.filter_by(status="open").all()
        if open_requests:
            candidates = [{"id": r.id, "text": r.product_text} for r in open_requests]
            ranked, _ = product_matcher.rank_products(product.searchable_text(), candidates, top_k=5)
            for r in ranked:
                if r["match_score"] > 0.15:
                    req = db.session.get(BuyerRequest, r["id"])
                    db.session.add(Notification(
                        user_id=req.buyer_id,
                        message=f"'{product.name}' just became available matching your request '{req.product_text}'."
                    ))
        db.session.commit()

        flash("Product listed successfully.")
        return redirect(url_for("farmer_dashboard"))

    return render_template("product_new.html", ai_price=ai_price, quality=quality)


@app.route("/farmer/requests")
@role_required("farmer")
def farmer_requests():
    open_requests = BuyerRequest.query.filter_by(status="open").order_by(BuyerRequest.created_at.desc()).all()
    my_products = Product.query.filter_by(farmer_id=current_user.id).all()
    candidates = [{"id": p.id, "text": p.searchable_text()} for p in my_products]

    scored = []
    for r in open_requests:
        _, best = product_matcher.rank_products(r.product_text, candidates, top_k=1) if candidates else ([], 0.0)
        scored.append((r, round(best * 100, 1)))
    scored.sort(key=lambda x: -x[1])
    return render_template("farmer_requests.html", scored=scored)


@app.route("/farmer/requests/<int:req_id>/respond", methods=["POST"])
@role_required("farmer")
def respond_request(req_id):
    req = db.session.get(BuyerRequest, req_id)
    if req:
        db.session.add(Notification(
            user_id=req.buyer_id,
            message=f"{current_user.name} responded to your request for '{req.product_text}'. Check contact details."
        ))
        db.session.commit()
        flash("Buyer notified.")
    return redirect(url_for("farmer_requests"))


# ---------- Buyer ----------
@app.route("/buyer/dashboard")
@role_required("buyer")
def buyer_dashboard():
    orders = Order.query.filter_by(buyer_id=current_user.id).order_by(Order.created_at.desc()).all()
    notifications = Notification.query.filter_by(user_id=current_user.id, is_read=False).all()
    return render_template("buyer_dashboard.html", orders=orders, notifications=notifications)


@app.route("/buyer/search", methods=["GET", "POST"])
@role_required("buyer")
def buyer_search():
    results = []
    query = ""
    demand_gap = False
    if request.method == "POST":
        query = request.form["query"].strip()
        products = Product.query.filter_by(status="active").all()
        candidates = [{"id": p.id, "text": p.searchable_text()} for p in products]
        ranked, best_score = product_matcher.rank_products(query, candidates, top_k=20)

        by_id = {p.id: p for p in products}
        results = [{"product": by_id[r["id"]], "match_score": r["match_score"]} for r in ranked]
        demand_gap = product_matcher.is_demand_gap(best_score)

    return render_template("buyer_search.html", results=results, query=query, demand_gap=demand_gap)


@app.route("/buyer/request", methods=["POST"])
@role_required("buyer")
def buyer_request():
    text = request.form["product_text"].strip()
    qty = request.form.get("quantity_needed")
    req = BuyerRequest(buyer_id=current_user.id, product_text=text,
                        quantity_needed=float(qty) if qty else None)
    db.session.add(req)
    db.session.commit()

    # Notify farmers whose past listings match this request (demand-sensing AI)
    all_products = Product.query.all()
    candidates = [{"id": p.farmer_id, "text": p.searchable_text()} for p in all_products]
    ranked, _ = product_matcher.rank_products(text, candidates, top_k=10)
    notified = set()
    for r in ranked:
        if r["match_score"] > 0.1 and r["id"] not in notified:
            db.session.add(Notification(
                user_id=r["id"],
                message=f"A buyer is looking for '{text}'. You may be able to supply this - check Requests."
            ))
            notified.add(r["id"])
    db.session.commit()
    flash(t("requests_sent"))
    return redirect(url_for("buyer_search"))


@app.route("/buyer/product/<int:product_id>")
@role_required("buyer")
def product_detail(product_id):
    product = db.session.get(Product, product_id)
    return render_template("product_detail.html", product=product)


@app.route("/buyer/order/<int:product_id>/pay", methods=["GET", "POST"])
@role_required("buyer")
def order_pay(product_id):
    product = db.session.get(Product, product_id)
    if request.method == "POST":
        quantity = float(request.form["quantity_kg"])
        payment_method = request.form["payment_method"]
        total = round(quantity * product.price_per_kg, 2)

        order = Order(buyer_id=current_user.id, product_id=product.id,
                       farmer_id=product.farmer_id, quantity_kg=quantity,
                       total_price=total, payment_method=payment_method,
                       status="paid" if payment_method == "online" else "pending")
        db.session.add(order)

        product.quantity_kg = max(0, product.quantity_kg - quantity)
        if product.quantity_kg <= 0:
            product.status = "sold"

        db.session.add(Notification(
            user_id=product.farmer_id,
            message=f"New order: {quantity}kg of {product.name} from {current_user.name}."
        ))
        db.session.commit()
        flash(t("order_placed"))
        return redirect(url_for("buyer_dashboard"))

    return render_template("order_pay.html", product=product)


@app.route("/order/<int:order_id>/rate", methods=["GET", "POST"])
@role_required("buyer")
def rate_order(order_id):
    order = db.session.get(Order, order_id)
    if request.method == "POST":
        stars = int(request.form["stars"])
        feedback = request.form.get("feedback", "")
        rating = Rating(order_id=order.id, farmer_id=order.farmer_id,
                         buyer_id=current_user.id, stars=stars, feedback=feedback)
        db.session.add(rating)

        farmer = db.session.get(User, order.farmer_id)
        total = farmer.rating_avg * farmer.rating_count + stars
        farmer.rating_count += 1
        farmer.rating_avg = round(total / farmer.rating_count, 2)
        order.status = "rated"
        db.session.commit()
        flash("Thanks for your feedback!")
        return redirect(url_for("buyer_dashboard"))

    return render_template("rate_order.html", order=order)


# ---------- Shared / Notifications / Transport ----------
@app.route("/notifications/read/<int:notif_id>")
@login_required
def mark_notification_read(notif_id):
    notif = db.session.get(Notification, notif_id)
    if notif and notif.user_id == current_user.id:
        notif.is_read = True
        db.session.commit()
    return redirect(request.referrer or url_for("index"))


@app.route("/transport")
@login_required
def transport_view():
    """Demo view: runs the AI shared-transport optimizer across all
    active listings that are ready for pickup."""
    products = Product.query.filter_by(status="active").all()
    shipments = []
    for p in products:
        farmer = db.session.get(User, p.farmer_id)
        shipments.append({
            "id": p.id, "farmer_name": farmer.name, "product": p.name,
            "quantity_kg": p.quantity_kg, "lat": farmer.lat, "lon": farmer.lon,
        })
    groups = transport_optimizer.optimize_shipments(shipments)
    return render_template("transport.html", groups=groups)


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0", port=5000)
