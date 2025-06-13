# app/routes/public.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from app.extensions import db
from sqlalchemy import func
from datetime import datetime, date
from app.models import Beach, Favorite  # Favorite burada olmalı
from flask_login import login_required
from flask_login import current_user
from flask_mail import Message
from app.extensions import mail
from app.models import BeachComment, db
from transformers import pipeline
import os
import requests
from dotenv import load_dotenv
load_dotenv()

public_bp = Blueprint('public', __name__)

HF_API_TOKEN = os.getenv("HF_TOKEN")



@public_bp.route('/')
def index():
    # Son eklenen plajlar
    latest_beaches = Beach.query.order_by(Beach.id.desc()).limit(5).all()

    # Tüm plajlar için favori sayısı ve sentiment ortalaması topla
    results = db.session.query(
        Beach.id.label("beach_id"),
        func.count(Favorite.id).label("fav_count"),
        func.avg(BeachComment.sentiment_score).label("avg_sentiment")
    ).outerjoin(Favorite, Beach.id == Favorite.beach_id
    ).outerjoin(BeachComment, Beach.id == BeachComment.beach_id
    ).group_by(Beach.id
    ).all()

    # Skor hesapla
    scored_beaches = []
    for row in results:
        fav_count = float(row.fav_count or 0)
        avg_sent = float(row.avg_sentiment or 0)
        score = fav_count * 0.6 + avg_sent * 0.4
        scored_beaches.append((row.beach_id, fav_count, avg_sent, score))

    # Beach objelerini getir
    beach_map = {b.id: b for b in Beach.query.all()}

    # render'a uygun hale getir
    enriched_beaches = []
    for beach_id, fav_count, avg_sent, score in scored_beaches:
        beach = beach_map.get(beach_id)
        if beach:
            enriched_beaches.append({
                'beach': beach,
                'times_favorited': fav_count,
                'avg_sentiment': round(avg_sent, 2),
                'rank_score': round(score, 2)
            })

    return render_template(
        'index.html',
        beaches=enriched_beaches,
        latest_beaches=latest_beaches
    )



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
                    sender=current_app.config['MAIL_USERNAME'],
                    recipients=["edrelax.beach@gmail.com"],
                    # Kullanıcının e-postasını "yanıtla" adresi olarak ayarlayın
                    reply_to=email)
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
    """
    Belirtilen plajın detay sayfasını gösterir ve mevcut kullanıcının
    bu plajı favorilerine ekleyip eklemediğini kontrol eder.
    """
    beach = Beach.query.filter_by(slug=slug).first_or_404()

    is_favorited = False
    if current_user.is_authenticated:
        is_favorited = db.session.query(
            Favorite.query.filter_by(
                user_id=current_user.id,
                beach_id=beach.id
            ).exists()
        ).scalar()

    return render_template(
        'beach_detail.html',
        beach=beach,
        is_favorited=is_favorited,
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
    user_id = current_user.get_id()

    user_favorite_entries = Favorite.query.filter_by(user_id=user_id).all()
    current_user_favorite_beaches = [fav.beach for fav in user_favorite_entries if fav.beach]

    # 🔥 Popüler plajları hem favori sayısı hem de yorum skoru ile sıralayacağız
    top_n = 3

    # 1. Plaj başına favori ve yorum ortalaması topla
    results = db.session.query(
        Beach.id.label("beach_id"),
        func.count(Favorite.id).label("fav_count"),
        func.avg(BeachComment.sentiment_score).label("avg_sentiment")
    ).outerjoin(Favorite, Beach.id == Favorite.beach_id
    ).outerjoin(BeachComment, Beach.id == BeachComment.beach_id
    ).group_by(Beach.id
    ).all()

    # 2. Skor hesapla ve sırala
    scored_beaches = []
    for row in results:
        fav_count = float(row.fav_count or 0)
        avg_sent = float(row.avg_sentiment or 0)
        score = fav_count * 0.6 + avg_sent * 0.4
        scored_beaches.append((row.beach_id, fav_count, avg_sent, score))

    # 3. En yüksek skor alan top_n plajı seç
    scored_beaches.sort(key=lambda x: x[3], reverse=True)
    top_beach_ids = [item[0] for item in scored_beaches[:top_n]]
    beach_map = {b.id: b for b in Beach.query.filter(Beach.id.in_(top_beach_ids)).all()}

    # 4. Şablona göndermek için liste hazırla
    top_popular_beaches = []
    for beach_id, fav_count, avg_sent, score in scored_beaches[:top_n]:
        beach = beach_map.get(beach_id)
        if beach:
            top_popular_beaches.append({
                'beach_obj': beach,
                'times_favorited': fav_count,
                'avg_sentiment': round(avg_sent, 2),
                'rank_score': round(score, 2)
            })

    return render_template(
        "my_favorites.html", 
        beaches=current_user_favorite_beaches,
        popular_beaches=top_popular_beaches
    )



@public_bp.route('/privacy')
def privacy():
    return render_template('about/privacy.html')

@public_bp.route('/kredi')
@login_required
def kredi():
    return render_template('kredi.html')

@public_bp.route('/beach-application', methods=['GET', 'POST'])
def beach_application():
    if request.method == 'POST':
        # Formdan gelen verileri al
        applicant_name = request.form.get('applicant_name')
        applicant_email = request.form.get('applicant_email')
        applicant_phone = request.form.get('applicant_phone')
        beach_name = request.form.get('beach_name')
        location = request.form.get('location')
        description = request.form.get('description')
        long_description = request.form.get('long_description')
        price = request.form.get('price')
        bed_count = request.form.get('bed_count')
        latitude = request.form.get('latitude')
        longitude = request.form.get('longitude')
        image_file = request.files.get('image_upload')

        # Checkbox verilerini al
        features = {
            'Rezerve Edilebilir': 'evet' if request.form.get('has_booking') else 'hayır',
            'Yiyecek & İçecek': 'evet' if request.form.get('has_food') else 'hayır',
            'Otopark': 'evet' if request.form.get('has_parking') else 'hayır',
            'Evcil Hayvan İzni': 'evet' if request.form.get('allows_pets') else 'hayır',
            'Wi-Fi': 'evet' if request.form.get('has_wifi') else 'hayır',
            'Su Sporları': 'evet' if request.form.get('has_water_sports') else 'hayır',
            'Engelli Dostu': 'evet' if request.form.get('is_disabled_friendly') else 'hayır',
        }

        # E-posta içeriğini oluştur
        subject = f"Yeni Plaj Başvurusu: {beach_name}"
        
        html_body = f"""
            <h2>Yeni Bir Plaj Başvurusu Aldınız!</h2>
            <p>Lütfen aşağıdaki bilgileri inceleyip admin panelinden sisteme ekleyin.</p>
            <hr>
            <h3>Başvuran Bilgileri</h3>
            <ul>
                <li><strong>Adı Soyadı:</strong> {applicant_name}</li>
                <li><strong>E-posta:</strong> {applicant_email}</li>
                <li><strong>Telefon:</strong> {applicant_phone}</li>
            </ul>
            <h3>Plaj Bilgileri</h3>
            <ul>
                <li><strong>Plaj Adı:</strong> {beach_name}</li>
                <li><strong>Konum:</strong> {location}</li>
                <li><strong>Başlangıç Fiyatı:</strong> {price} TL</li>
                <li><strong>Şezlong Sayısı:</strong> {bed_count}</li>
                <li><strong>Koordinatlar:</strong> Lat: {latitude}, Lon: {longitude}</li>
            </ul>
            <h4>Kısa Açıklama:</h4>
            <p>{description}</p>
            <h4>Detaylı Açıklama:</h4>
            <div>{long_description}</div>
            <h4>Özellikler:</h4>
            <ul>
                {"".join([f"<li><strong>{feature}:</strong> {status}</li>" for feature, status in features.items()])}
            </ul>
        """
        
        # E-posta gönderme işlemi
        try:
            # Yönetici e-postasını config dosyasından al
            admin_email = current_app.config.get('ADMIN_EMAIL', 'edrelax.beach@gmail.com')
            
            msg = Message(subject,
                          sender=current_app.config['MAIL_USERNAME'],
                          recipients=[admin_email])
            msg.html = html_body

            # Eğer görsel yüklendiyse e-postaya ekle
            if image_file:
                msg.attach(
                    image_file.filename,
                    image_file.content_type,
                    image_file.read()
                )

            mail.send(msg)
            flash('Başvurunuz başarıyla gönderildi. En kısa sürede incelenecektir.', 'success')
            return redirect(url_for('public.index'))

        except Exception as e:
            # Hata durumunda logla ve kullanıcıya bilgi ver
            current_app.logger.error(f"E-posta gönderim hatası: {e}")
            flash('Başvurunuz gönderilirken bir hata oluştu. Lütfen daha sonra tekrar deneyin.', 'danger')

    # GET request için formu göster
    return render_template('public/beach_application.html')

def get_sentiment_score(comment_text):
    api_url = "https://api-inference.huggingface.co/models/tabularisai/multilingual-sentiment-analysis"
    headers = {
        "Authorization": f"Bearer " + HF_API_TOKEN
    }
    payload = {"inputs": comment_text}

    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        result = response.json()

        print(f"[INFO] HuggingFace cevabı: {result}")

        label_to_score = {
            "Very Negative": 1,
            "Negative": 2,
            "Neutral": 3,
            "Positive": 4,
            "Very Positive": 5
        }

        label = None

        # Çoklu olasılık (en yaygın)
        if isinstance(result, list):
            if isinstance(result[0], list):
                label = result[0][0]["label"]
            elif isinstance(result[0], dict):
                label = result[0]["label"]

        score = label_to_score.get(label, 3)
        print(f"[INFO] Yorum: '{comment_text}' → {label} → {score}")
        return score

    except Exception as e:
        print(f"❌ Sentiment API hatası: {e}")
        return 3



# 🔻 Flask route
@public_bp.route("/submit-beach-comment/<int:beach_id>", methods=["POST"])
@login_required
def submit_beach_comment(beach_id):
    comment_text = request.form.get("comment_text", "").strip()
    slug = request.form.get("slug")  # 🔄 slug'ı formdan alıyoruz

    if not comment_text:
        flash("Yorum boş bırakılamaz.", "danger")
        return redirect(url_for("public.beach_detail", slug=slug))

    # 🔸 Modelden gelen puanı al
    sentiment_score = get_sentiment_score(comment_text)

    new_comment = BeachComment(
        user_id=current_user.id,
        beach_id=beach_id,
        comment_text=comment_text,
        sentiment_score=sentiment_score
    )

    db.session.add(new_comment)
    db.session.commit()

    flash("Yorumunuz alındı, teşekkürler!", "success")
    return redirect(url_for("public.beach_detail", slug=slug))
