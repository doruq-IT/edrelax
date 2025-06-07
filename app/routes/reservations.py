# app/routes/reservations.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask_wtf.csrf import CSRFProtect, CSRFError
from app.extensions import db, csrf
from app.models import Beach, Reservation
from datetime import datetime, timedelta
from collections import defaultdict

reservations_bp = Blueprint('reservations', __name__)

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("You must be logged in to access this page.", "warning")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated_function

@reservations_bp.route('/beach/<slug>/select-beds')
@login_required
def select_beds(slug):
    beach = Beach.query.filter_by(slug=slug).first_or_404()

    date_str = request.args.get('date')
    start_str = request.args.get('start_time')
    end_str = request.args.get('end_time')

    if not date_str or not start_str or not end_str:
        flash("Please select a valid date and time range.", "warning")
        return redirect(url_for('public.beach_detail', slug=slug))

    try:
        selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        start_time = datetime.strptime(start_str, "%H:%M").time()
        end_time = datetime.strptime(end_str, "%H:%M").time()
    except ValueError:
        flash("Invalid date/time format.", "danger")
        return redirect(url_for('public.beach_detail', slug=slug))

    overlapping_reservations = Reservation.query.filter(
        Reservation.beach_id == beach.id,
        Reservation.date == selected_date,
        Reservation.start_time < end_time,
        Reservation.end_time > start_time,
        Reservation.status.in_(['reserved', 'used'])  # 🔥 Eklendi
    ).all()

    booked_beds = [r.bed_number for r in overlapping_reservations]

    return render_template(
        'select_beds.html',
        beach=beach,
        date=date_str,
        start_time=start_str,
        end_time=end_str,
        booked_beds=booked_beds
    )

@reservations_bp.route('/make-reservation', methods=['POST'])
@login_required
def make_reservation():
    data = request.get_json()

    beach_id = data.get("beach_id")
    bed_ids = data.get("bed_ids")
    date = data.get("date")
    start_time = data.get("start_time")
    end_time = data.get("end_time")

    if not (beach_id and bed_ids and date and start_time and end_time):
        return jsonify({"success": False, "message": "Eksik bilgi var."}), 400

    try:
        parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
        parsed_start = datetime.strptime(start_time, "%H:%M").time()
        parsed_end = datetime.strptime(end_time, "%H:%M").time()
        if parsed_end <= parsed_start:
            return jsonify({"success": False, "message": "Bitiş saati, başlangıç saatinden sonra olmalı."}), 400

    except ValueError:
        return jsonify({"success": False, "message": "Tarih veya saat biçimi hatalı."}), 400

    beach = Beach.query.get(beach_id)
    if not beach or beach.bed_count < 1:
        return jsonify({"success": False, "message": "Plajda şezlong tanımı yapılmamış. Contact Us bölümünden lütfen bize iletiniz."}), 400

    for bed_id in bed_ids:
        if bed_id < 1 or bed_id > beach.bed_count:
            return jsonify({"success": False, "message": f"Geçersiz şezlong numarası: {bed_id}"}), 400

    if not beach:
        return jsonify({"success": False, "message": "Plaj bulunamadı."}), 404

    for bed_id in bed_ids:
        existing = Reservation.query.filter_by(
            beach_id=beach_id,
            bed_number=bed_id,
            date=parsed_date
        ).filter(
            Reservation.start_time < parsed_end,
            Reservation.end_time > parsed_start
        ).first()

        if existing:
            return jsonify({"success": False, "message": f"Şezlong {bed_id} bu saat aralığında zaten rezerve edilmiş."}), 409

        new_reservation = Reservation(
            beach_id=beach_id,
            user_id=session['user_id'],
            bed_number=bed_id,
            date=parsed_date,
            start_time=parsed_start,
            end_time=parsed_end
        )
        db.session.add(new_reservation)

    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Rezervasyon başarıyla oluşturuldu.",
        "summary": {
            "date": parsed_date.strftime("%Y-%m-%d"),
            "start_time": parsed_start.strftime("%H:%M"),
            "end_time": parsed_end.strftime("%H:%M"),
            "bed_count": len(bed_ids),
            "total_price": beach.price * len(bed_ids)
        }
    })

@reservations_bp.route("/my-reservations")
@login_required
def my_reservations():
    user_id = session['user_id']
    user_reservations = Reservation.query.filter_by(user_id=user_id).order_by(
        Reservation.date.desc(), Reservation.start_time.desc()
    ).all()

    total_reservations_count = len(user_reservations)
    current_total_spent = 0
    beach_visit_counter = defaultdict(int)
    reservations_by_month = defaultdict(int)

    # N+1 sorgu problemini çözmek için plajları önceden çekelim
    if user_reservations:
        beach_ids = {res.beach_id for res in user_reservations} # Tekil plaj ID'leri
        beaches_involved = Beach.query.filter(Beach.id.in_(beach_ids)).all()
        beaches_map = {beach.id: beach for beach in beaches_involved} # ID ile hızlı erişim için map
    else:
        beaches_map = {}

    for res in user_reservations:
        beach_instance = beaches_map.get(res.beach_id)

        if beach_instance and beach_instance.price is not None:
            # Saatlik fiyatlandırma için süre hesaplaması
            # Rezervasyonun aynı gün içinde başlayıp bittiğini varsayıyoruz
            start_datetime = datetime.combine(res.date, res.start_time)
            end_datetime = datetime.combine(res.date, res.end_time)
            
            if end_datetime > start_datetime:
                duration_seconds = (end_datetime - start_datetime).total_seconds()
                duration_hours = duration_seconds / 3600
                current_total_spent += beach_instance.price * duration_hours
            # else: duration is zero or negative, so no cost added
        
        beach_name = beach_instance.name if beach_instance else "Bilinmeyen Plaj"
        beach_visit_counter[beach_name] += 1
        
        month_year_key = res.date.strftime("%Y-%m") # Örn: "2024-05"
        reservations_by_month[month_year_key] += 1

    # En çok ziyaret edilen plajı belirle (eşitlik durumunda alfabetik)
    top_beach_name = "Yok"
    if beach_visit_counter:
        # Önce ziyaret sayısına göre (çoktan aza), sonra plaj adına göre (alfabetik) sırala
        sorted_beaches = sorted(beach_visit_counter.items(), key=lambda item: (-item[1], item[0]))
        top_beach_name = sorted_beaches[0][0]

    # Aylık verileri kronolojik sırala
    sorted_monthly_data = dict(sorted(reservations_by_month.items()))

    stats_data = {
        "total_reservations": total_reservations_count,
        "total_spent": round(current_total_spent, 2),
        "top_beach": top_beach_name,
        "monthly_data": sorted_monthly_data # Sıralanmış aylık veri
    }

    return render_template("my_reservations.html", reservations=user_reservations, stats=stats_data)



@reservations_bp.route('/cancel-reservation/<int:res_id>', methods=['POST'])
@login_required
def cancel_reservation(res_id):
    reservation = Reservation.query.get_or_404(res_id)
    if reservation.user_id != session['user_id']:
        flash("Bu rezervasyonu iptal etmeye yetkiniz yok.", "danger")
        return redirect(url_for('reservations.my_reservations'))

    # 📅 Başlangıç zamanını hesapla
    start_datetime = datetime.combine(reservation.date, reservation.start_time)
    now = datetime.now()

    # ⏰ Başlangıç saatine 1 saatten az kalmışsa iptal engellenir
    if start_datetime - now < timedelta(hours=1):
        flash("Rezervasyonun başlamasına 1 saatten az kaldığı için iptal edilemez.", "warning")
        return redirect(url_for('reservations.my_reservations'))

    # ✅ İptal işlemi
    db.session.delete(reservation)
    db.session.commit()
    flash("Rezervasyon başarıyla iptal edildi.", "info")
    return redirect(url_for('reservations.my_reservations'))

@reservations_bp.route("/get-user-info/<int:reservation_id>")
@login_required
def get_user_info(reservation_id):
    reservation = Reservation.query.get_or_404(reservation_id)
    user = reservation.user

    if not user:
        return jsonify({"success": False, "message": "Kullanıcı bilgisi bulunamadı."}), 404

    return jsonify({
        "success": True,
        "full_name": f"{user.first_name} {user.last_name}",
        "email": user.email
    })

