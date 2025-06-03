# app/routes/public.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from app.extensions import db
from sqlalchemy import func
from datetime import datetime, date
from app.models import Beach, Favorite  # Favorite burada olmalı
from flask_mail import Message
from app.extensions import mail


public_bp = Blueprint('public', __name__)

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("You must be logged in to access this page.", "warning")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated_function

@public_bp.route('/')
def index():
    beaches = Beach.query.all()
    latest_beaches = Beach.query.order_by(Beach.id.desc()).limit(2).all()
    return render_template('index.html', beaches=beaches, latest_beaches=latest_beaches)

@public_bp.route('/about')
def about():
    return render_template('about.html')



@public_bp.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        message = request.form.get("message")

        msg = Message(subject=f"New Contact Form Message from {name}",
                      sender=email,
                      recipients=["edrelax.beach@gmail.com"])
        msg.body = f"From: {name} <{email}>\n\n{message}"
        try:
            mail.send(msg)
            flash("Your message has been sent successfully.", "success")
        except Exception as e:
            flash("An error occurred while sending your message.", "danger")

        return redirect(url_for("public.contact"))

    return render_template("contact.html")


@public_bp.route('/beach/<slug>')
@login_required
def beach_detail(slug):
    beach = Beach.query.filter_by(slug=slug).first_or_404()

    # 🔥 Favori kontrolü eklendi
    is_favorited = False
    if 'user_id' in session:
        is_favorited = Favorite.query.filter_by(
            user_id=session['user_id'], beach_id=beach.id
        ).first() is not None

    beach.is_favorited = is_favorited

    return render_template(
        'beach_detail.html',
        beach=beach,
        now=datetime.now(),
        current_date=date.today().isoformat()
    )


@public_bp.route('/search_suggestions')
def search_suggestions():
    term = request.args.get('term', '').lower()
    results = Beach.query.filter(Beach.name.ilike(f'%{term}%')).limit(5).all()
    return jsonify([{
        'name': b.name,
        'location': b.location,
        'slug': b.slug
    } for b in results])

@public_bp.route('/advanced-search')
def advanced_search():
    name_query = request.args.get('term', '')
    location_query = request.args.get('location', '')

    has_booking = request.args.get('has_booking') == 'on'
    has_food = request.args.get('has_food') == 'on'
    has_parking = request.args.get('has_parking') == 'on'
    allows_pets = request.args.get('allows_pets') == 'on'
    has_wifi = request.args.get('has_wifi') == 'on'
    has_water_sports = request.args.get('has_water_sports') == 'on'
    is_disabled_friendly = request.args.get('is_disabled_friendly') == 'on'

    query = Beach.query
    if name_query:
        query = query.filter(Beach.name.ilike(f"%{name_query}%"))
    if location_query:
        query = query.filter(Beach.location.ilike(f"%{location_query}%"))

    if has_booking: query = query.filter_by(has_booking=True)
    if has_food: query = query.filter_by(has_food=True)
    if has_parking: query = query.filter_by(has_parking=True)
    if allows_pets: query = query.filter_by(allows_pets=True)
    if has_wifi: query = query.filter_by(has_wifi=True)
    if has_water_sports: query = query.filter_by(has_water_sports=True)
    if is_disabled_friendly: query = query.filter_by(is_disabled_friendly=True)

    beaches = query.all()
    beach_data = [
        {
            'name': b.name,
            'location': b.location,
            'slug': b.slug,
            'latitude': b.latitude,
            'longitude': b.longitude,
            'has_booking': b.has_booking,
            'has_food': b.has_food,
            'has_parking': b.has_parking,
            'allows_pets': b.allows_pets,
            'has_wifi': b.has_wifi,
            'has_water_sports': b.has_water_sports,
            'is_disabled_friendly': b.is_disabled_friendly
        }
        for b in beaches if b.latitude and b.longitude
    ]
    return render_template("advanced_search.html", beaches=beaches, beach_data=beach_data)

@public_bp.route('/api/beaches')
def api_beaches():
    beaches = Beach.query.all()
    return jsonify([
        {
            'name': b.name,
            'location': b.location,
            'latitude': b.latitude,
            'longitude': b.longitude,
            'slug': b.slug
        } for b in beaches
    ])

@public_bp.route('/toggle-favorite/<int:beach_id>', methods=['POST'])
@login_required
def toggle_favorite(beach_id):
    user_id = session['user_id']
    favorite = Favorite.query.filter_by(user_id=user_id, beach_id=beach_id).first()

    if favorite:
        db.session.delete(favorite)
        db.session.commit()
        return jsonify({"status": "removed"})
    else:
        new_fav = Favorite(user_id=user_id, beach_id=beach_id)
        db.session.add(new_fav)
        db.session.commit()
        return jsonify({"status": "added"})

@public_bp.route("/my-favorites")
@login_required
def my_favorites():
    user_id = session["user_id"]
    
    # Kullanıcının kendi favori plajları (mevcut kodunuz)
    user_favorite_entries = Favorite.query.filter_by(user_id=user_id).all()
    current_user_favorite_beaches = [fav.beach for fav in user_favorite_entries if fav.beach]

    # ---- YENİ: En Çok Favorilenen Plajları Hesaplama ----
    top_n_favorites = 3 # Kaç tane popüler plaj göstermek istediğiniz

    # beach_id'ye göre favori sayısını say, en çok olanları al
    popular_beach_ids_with_counts = db.session.query(
        Favorite.beach_id, 
        func.count(Favorite.beach_id).label('favorite_count')
    ).group_by(Favorite.beach_id).order_by(func.count(Favorite.beach_id).desc()).limit(top_n_favorites).all()
    # Bu sorgu [(beach_id_1, count_1), (beach_id_2, count_2), ...] şeklinde bir liste döndürür.

    top_popular_beaches = []
    if popular_beach_ids_with_counts:
        popular_beach_ids = [item[0] for item in popular_beach_ids_with_counts]
        
        # En basit yol, ID'leri alıp sonra Beach objelerini çekmek:
        beaches_from_db = Beach.query.filter(Beach.id.in_(popular_beach_ids)).all()
        # Veritabanından gelen plajları bir sözlüğe atayalım ki kolayca erişebilelim
        beach_map_for_popular = {b.id: b for b in beaches_from_db}
        
        # Orijinal sıralamayı (favori sayısına göre) koruyarak listeyi oluşturalım
        for beach_id, fav_count in popular_beach_ids_with_counts:
            beach = beach_map_for_popular.get(beach_id)
            if beach:
                # İsteğe bağlı olarak favori sayısını da plaj nesnesine ekleyebiliriz
                # setattr(beach, 'times_favorited', fav_count) # Veya yeni bir dict içinde gönder
                top_popular_beaches.append({
                    'beach_obj': beach,
                    'times_favorited': fav_count
                })
    return render_template(
        "my_favorites.html", 
        beaches=current_user_favorite_beaches, # Kullanıcının kendi favorileri
        popular_beaches=top_popular_beaches  # YENİ: En popüler plajlar listesi
    )

@public_bp.route('/privacy')
def privacy():
    return render_template('about/privacy.html')

@public_bp.route('/kredi')
@login_required
def kredi():
    return render_template('kredi.html')
