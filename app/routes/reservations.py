# app/routes/reservations.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from app.models import User
from app.extensions import db, csrf
from app.models import Beach, Reservation
from app.extensions import socketio
from datetime import datetime, timedelta
import pytz
from collections import defaultdict

reservations_bp = Blueprint('reservations', __name__)

@reservations_bp.route('/beach/<slug>/select-beds')
@login_required
def select_beds(slug):
    beach = Beach.query.filter_by(slug=slug).first_or_404()

    date_str = request.args.get('date')
    start_str = request.args.get('start_time')
    end_str = request.args.get('end_time')

    if not date_str or not start_str or not end_str:
        flash("Lütfen geçerli bir tarih ve saat aralığı seçin.", "warning")
        return redirect(url_for('public.beach_detail', slug=slug))

    # --- YENİ: SAAT DİLİMİ YÖNETİMİ ---
    try:
        # Saat dilimini tanımla (kullanıcılarınızın bulunduğu bölge)
        local_tz = pytz.timezone('Europe/Istanbul')
        
        # Kullanıcıdan gelen "saf" tarih ve saatleri birleştirip yerel saat dilimini ata
        local_start_dt = local_tz.localize(datetime.strptime(f"{date_str} {start_str}", "%Y-%m-%d %H:%M"))
        
        # Veritabanı sorgusu için bu yerel saati evrensel saate (UTC) çevir
        utc_start_dt = local_start_dt.astimezone(pytz.utc)

    except (ValueError, pytz.exceptions.InvalidTimeError):
        flash("Geçersiz tarih veya saat formatı.", "danger")
        return redirect(url_for('public.beach_detail', slug=slug))
    # --- SAAT DİLİMİ YÖNETİMİ BİTİŞ ---

    # Veritabanındaki UTC'ye çevrilmiş saatlerle karşılaştırma yap
    overlapping_reservations = Reservation.query.filter(
        Reservation.beach_id == beach.id,
        # ÖNEMLİ: Veritabanındaki tarih ve saatlerin de UTC olarak kaydedildiğini varsayıyoruz.
        # Bir sonraki adımda make_reservation fonksiyonunu da bu şekilde güncelleyeceğiz.
        Reservation.date == utc_start_dt.date(),
        Reservation.start_time < datetime.strptime(end_str, "%H:%M").time(),
        Reservation.end_time > datetime.strptime(start_str, "%H:%M").time(),
        Reservation.status.in_(['reserved', 'used'])
    ).all()

    booked_beds = [r.bed_number for r in overlapping_reservations]

    # Hata ayıklama log'u (isteğe bağlı, sorun çözüldüğünde silebilirsiniz)
    print(f"DEBUG: User '{current_user.email}' viewing '{slug}'. Booked beds found: {booked_beds}")

    # Kullanıcının günlük limitini kendi yerel gününe göre hesapla
    user_reservations_today = Reservation.query.filter(
        Reservation.user_id == current_user.id,
        Reservation.date == local_start_dt.date(), # Burada yerel tarih kullanmak daha doğru
        Reservation.status.in_(['reserved', 'used'])
    ).count()
  
    return render_template(
        'select_beds.html',
        beach=beach,
        date=date_str,
        start_time=start_str,
        end_time=end_str,
        booked_beds=booked_beds,
        kullanicinin_o_gun_rezerve_ettigi_sezlong_sayisi=user_reservations_today
    )

@reservations_bp.route('/make-reservation', methods=['POST'])
@login_required
def make_reservation():
    data = request.get_json()

    beach_id = data.get("beach_id")
    bed_ids = data.get("bed_ids")
    date_str = data.get("date")
    start_str = data.get("start_time")
    end_str = data.get("end_time")

    if not (beach_id and bed_ids and date_str and start_str and end_str):
        return jsonify({"success": False, "message": "Eksik bilgi var."}), 400

    # --- YENİ: SAAT DİLİMİ YÖNETİMİ BAŞLANGIÇ ---
    try:
        # Saat dilimini tanımla (sizin ve kullanıcılarınızın bulunduğu bölge)
        local_tz = pytz.timezone('Europe/Istanbul')
        
        # Kullanıcıdan gelen "saf" tarih ve saatleri birleştirip yerel saat dilimini ata
        local_start_dt = local_tz.localize(datetime.strptime(f"{date_str} {start_str}", "%Y-%m-%d %H:%M"))
        local_end_dt = local_tz.localize(datetime.strptime(f"{date_str} {end_str}", "%Y-%m-%d %H:%M"))
        
        # Bu yerel saati evrensel saate (UTC) çevir. Tüm karşılaştırmalar ve kayıtlar UTC üzerinden yapılacak.
        utc_start_dt = local_start_dt.astimezone(pytz.utc)
        utc_end_dt = local_end_dt.astimezone(pytz.utc)
        
        if utc_end_dt <= utc_start_dt:
            return jsonify({"success": False, "message": "Bitiş saati, başlangıç saatinden sonra olmalı."}), 400

        # Veritabanı işlemleri için UTC tarih ve saatlerini ayrı değişkenlere ata
        parsed_date_utc = utc_start_dt.date()
        parsed_start_utc = utc_start_dt.time()
        parsed_end_utc = utc_end_dt.time()

    except (ValueError, pytz.exceptions.InvalidTimeError):
        return jsonify({"success": False, "message": "Tarih veya saat biçimi hatalı."}), 400
    # --- SAAT DİLİMİ YÖNETİMİ BİTİŞ ---

    beach = Beach.query.get(beach_id)
    if not beach:
        return jsonify({"success": False, "message": "Plaj bulunamadı."}), 404

    if beach.bed_count < 1:
        return jsonify({"success": False, "message": "Plajda şezlong tanımı yapılmamış. İletişim bölümünden lütfen bize iletiniz."}), 400

    for bed_id in bed_ids:
        try:
            if int(bed_id) < 1 or int(bed_id) > beach.bed_count:
                return jsonify({"success": False, "message": f"Geçersiz şezlong numarası: {bed_id}"}), 400
        except (ValueError, TypeError):
            return jsonify({"success": False, "message": f"Geçersiz şezlong ID formatı: {bed_id}"}), 400

    # --- İYİLEŞTİRME: Günlük limit sorgusu düzeltildi ---
    GUNLUK_MAKSIMUM_SEZLONG = 10
    user_id = current_user.id
    # Kullanıcının limiti, kendi yerel gününe göre hesaplanır ve 'cancelled' olanlar sayılmaz
    reservations_today_count = Reservation.query.filter(
        Reservation.user_id == user_id, 
        Reservation.date == local_start_dt.date(),
        Reservation.status.in_(['reserved', 'used'])
    ).count()

    if (reservations_today_count + len(bed_ids)) > GUNLUK_MAKSIMUM_SEZLONG:
        return jsonify({"success": False, "message": f"Bir günde en fazla {GUNLUK_MAKSIMUM_SEZLONG} şezlong rezerve edebilirsiniz."}), 400

    # Çifte rezervasyon kontrolü artık UTC zamanına göre yapılır
    existing_reservation = Reservation.query.filter(
        Reservation.beach_id == beach_id,
        Reservation.bed_number.in_(bed_ids),
        Reservation.date == parsed_date_utc,
        Reservation.start_time < parsed_end_utc,
        Reservation.end_time > parsed_start_utc,
        Reservation.status.in_(['reserved', 'used'])
    ).first()

    if existing_reservation:
        return jsonify({"success": False, "message": "Seçtiğiniz şezlonglardan biri veya birkaçı bu saat aralığında başkası tarafından rezerve edilmiş."}), 409

    try:
        # Rezervasyonları veritabanına UTC zamanı ile kaydet
        for bed_id in bed_ids:
            new_reservation = Reservation(
                beach_id=beach_id,
                user_id=user_id,
                bed_number=int(bed_id),
                date=parsed_date_utc,        # Veritabanına UTC tarihi kaydet
                start_time=parsed_start_utc, # Veritabanına UTC başlangıç saati kaydet
                end_time=parsed_end_utc,     # Veritabanına UTC bitiş saati kaydet
                status='reserved'
            )
            db.session.add(new_reservation)

        db.session.commit()

        # WebSocket mesajları için orijinal "saf" tarih/saatleri kullanabiliriz
        # eğer istemci tarafı UTC'den haberdar değilse bu daha kolay bir yöntemdir.
        print("📡 WebSocket için tek bir birleştirilmiş olay ('bulk_status_updated') gönderiliyor...")
        socketio.emit("bulk_status_updated", {
            "beach_id": beach_id,
            "bed_ids": bed_ids,       # Örnek: ['1', '2'] gibi bir liste
            "date": date_str,
            "start_time": start_str,  # Örnek: "10:00"
            "end_time": end_str,      # Örnek: "13:00"
            "new_status": "reserved"
        }, broadcast=True)

        # Başarılı HTTP yanıtını rezervasyonu yapan kullanıcıya döndür
        return jsonify({
            "success": True,
            "message": "Rezervasyon başarıyla oluşturuldu.",
            "summary": {
                "date": date_str,
                "start_time": start_str,
                "end_time": end_str,
                "bed_count": len(bed_ids),
                "total_price": beach.price * len(bed_ids) if beach.price else 0
            }
        })

    except IntegrityError: # Veritabanı "bu kayıt zaten var" hatası verirse
        db.session.rollback() # İşlemi geri al
        return jsonify({"success": False, "message": "Üzgünüz, siz işlemi tamamlarken seçtiğiniz şezlonglardan biri rezerve edildi. Lütfen sayfayı yenileyip tekrar deneyin."}), 409
    
    except Exception as e: # Diğer tüm beklenmedik hatalar için
        db.session.rollback() # İşlemi geri al
        # Geliştirme ortamında hatayı loglamak faydalı olabilir:
        print(f"AN UNEXPECTED ERROR OCCURRED: {e}")
        return jsonify({"success": False, "message": "Beklenmedik bir sunucu hatası oluştu. Lütfen daha sonra tekrar deneyin."}), 500


@reservations_bp.route("/my-reservations")
@login_required
def my_reservations():
    user_id = current_user.id
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
    if reservation.user_id != current_user.id:
        flash("Bu rezervasyonu iptal etmeye yetkiniz yok.", "danger")
        return redirect(url_for('reservations.my_reservations'))

    # İptal etmeye çalıştığı rezervasyonun durumu zaten 'cancelled' ise işlem yapma
    if reservation.status == 'cancelled':
        flash("Bu rezervasyon zaten daha önce iptal edilmiş.", "info")
        return redirect(url_for('reservations.my_reservations'))

    start_datetime = datetime.combine(reservation.date, reservation.start_time)
    now = datetime.now()

    # İYİLEŞTİRME 1: Geçmiş rezervasyonlar için farklı mesaj
    if start_datetime < now:
        flash("Başlangıç saati geçmiş bir rezervasyon iptal edilemez.", "danger")
        return redirect(url_for('reservations.my_reservations'))

    # İYİLEŞTİRME 2: İptal süresi kontrolü (örneğin 1 saat)
    if start_datetime - now < timedelta(hours=1):
        flash("Rezervasyonun başlamasına 1 saatten az kaldığı için iptal edilemez.", "warning")
        return redirect(url_for('reservations.my_reservations'))

    # İYİLEŞTİRME 3: Veriyi silmek yerine durumunu güncelle (Soft Delete)
    reservation.status = 'cancelled'

    db.session.commit()
    
    flash("Rezervasyonunuz başarıyla iptal edildi.", "success")
    return redirect(url_for('reservations.my_reservations'))

@reservations_bp.route("/get-user-info/<int:reservation_id>")
@login_required
def get_user_info(reservation_id):
    reservation = Reservation.query.get_or_404(reservation_id)
    current_user = User.query.get(current_user.id)

    is_admin = getattr(current_user, 'is_admin', False)
    is_beach_owner = (reservation.beach.owner_id == current_user.id)

    if not (is_admin or is_beach_owner):
        return jsonify({"success": False, "message": "Bu bilgiyi görüntüleme yetkiniz yok."}), 403 # 403 Forbidden

    user = reservation.user
    if not user:
        return jsonify({"success": False, "message": "Kullanıcı bilgisi bulunamadı."}), 404

    return jsonify({
        "success": True,
        "full_name": f"{user.first_name} {user.last_name}",
        "email": user.email
    })

@reservations_bp.route('/notify-when-free', methods=['POST'])
# @login_required  # Test sırasında kapalı
def notify_when_free():
    print("[DEBUG] notify_when_free route triggered.")

    try:
        data = request.get_json(force=True)
        print("[DEBUG] JSON alındı:", data)
    except Exception as e:
        print("[ERROR] JSON parsing hatası:", e)
        return jsonify({"success": False, "message": "Geçersiz JSON"}), 400

    beach_id = data.get("beach_id")
    bed_number = data.get("bed_number")
    date = data.get("date")
    time_slot = data.get("time_slot")

    if not all([beach_id, bed_number, date, time_slot]):
        print("[ERROR] Eksik alan var")
        return jsonify({"success": False, "message": "Eksik veri gönderildi."}), 400

    from app.models import WaitingList
    from datetime import datetime

    # 🧪 TEST: current_user yerine sabit kullanıcı ID kullan
    test_user_id = 1  # Veritabanında gerçekten olan bir user ID yaz

    try:
        existing = WaitingList.query.filter_by(
            user_id=test_user_id,
            beach_id=beach_id,
            bed_number=bed_number,
            date=date,
            time_slot=time_slot,
            notified=False
        ).first()

        if existing:
            print("[DEBUG] Zaten kayıtlı istek bulundu.")
            return jsonify({"success": False, "message": "Bu şezlong için zaten bildirim isteğiniz mevcut."}), 200

        new_entry = WaitingList(
            user_id=test_user_id,
            beach_id=beach_id,
            bed_number=bed_number,
            date=date,
            time_slot=time_slot,
            notified=False,
            created_at=datetime.utcnow()
        )

        db.session.add(new_entry)
        db.session.commit()

        print("[DEBUG] Yeni kayıt oluşturuldu.")
        return jsonify({"success": True, "message": "Bildirim talebiniz alındı. Şezlong boşalınca size haber vereceğiz."})

    except Exception as e:
        print(f"[ERROR] DB işlemi sırasında hata: {e}")
        return jsonify({"success": False, "message": "Sunucu hatası oluştu."}), 500
