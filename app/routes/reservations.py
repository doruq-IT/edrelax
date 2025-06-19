# app/routes/reservations.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from collections import defaultdict
from app.models import RentableItem
from app.models import User
from app.extensions import db, csrf
from app.models import Beach, Reservation
from app.extensions import socketio
from datetime import datetime, timedelta
from app.models import WaitingList
import pytz
import sys
from collections import defaultdict
from flask_mail import Message
from app.extensions import mail


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

    # --- SAAT DİLİMİ YÖNETİMİ (Bu kısım aynı kalıyor) ---
    try:
        local_tz = pytz.timezone('Europe/Istanbul')
        local_start_dt = local_tz.localize(datetime.strptime(f"{date_str} {start_str}", "%Y-%m-%d %H:%M"))
        utc_start_dt = local_start_dt.astimezone(pytz.utc)
    except (ValueError, pytz.exceptions.InvalidTimeError):
        flash("Geçersiz tarih veya saat formatı.", "danger")
        return redirect(url_for('public.beach_detail', slug=slug))
 
    # 1. Plaja ait tüm aktif kiralanabilir eşyaları çek.
    all_items = beach.rentable_items

    # 2. Belirtilen tarih/saat aralığında dolu olan EŞYA ID'lerini bul.
    overlapping_reservations = Reservation.query.filter(
        Reservation.beach_id == beach.id,
        Reservation.date == utc_start_dt.date(),
        Reservation.start_time < datetime.strptime(end_str, "%H:%M").time(),
        Reservation.end_time > datetime.strptime(start_str, "%H:%M").time(),
        Reservation.status.in_(['reserved', 'used'])
    ).all()
    booked_item_ids = {r.item_id for r in overlapping_reservations}

    # 3. Şablona göndereceğimiz zengin veri yapısını hazırla.
    items_by_type = defaultdict(list)
    for item in all_items:
        if not item.is_active:
            continue

        status = 'booked' if item.id in booked_item_ids else 'available'
        
        items_by_type[item.item_type].append({
            'id': item.id,
            'item_number': item.item_number,
            'price': float(item.price),
            'status': status
        })
    
    user_reservations_today = Reservation.query.filter(
        Reservation.user_id == current_user.id,
        Reservation.date == local_start_dt.date(), # Burada yerel tarih kullanmak daha doğru
        Reservation.status.in_(['reserved', 'used'])
    ).count()
 
    # YORUM: Artık `booked_beds` yerine yeni yapıyı ve orijinal değişken adıyla limit bilgisini şablona gönderiyoruz.
    return render_template(
        'select_beds.html',
        beach=beach,
        date=date_str,
        start_time=start_str,
        end_time=end_str,
        items_by_type=items_by_type,  # Yeni ve zengin veri yapımız
        kullanicinin_o_gun_rezerve_ettigi_sezlong_sayisi=user_reservations_today # Orijinal değişken adını koruduk
    )

@reservations_bp.route('/make-reservation', methods=['POST'])
@login_required
def make_reservation():
    """
    Kullanıcının seçtiği kiralanabilir eşyalar (item) için rezervasyon oluşturur.
    Yeni sisteme tamamen uyarlanmıştır.
    """
    data = request.get_json()

    # 1. Gelen veriyi yeni yapıya göre al ('item_ids' olarak)
    beach_id = data.get("beach_id")
    item_ids = data.get("item_ids") # ESKİ: bed_ids, YENİ: item_ids
    date_str = data.get("date")
    start_str = data.get("start_time")
    end_str = data.get("end_time")

    if not all([beach_id, item_ids, date_str, start_str, end_str]):
        return jsonify({"success": False, "message": "Eksik bilgi gönderildi."}), 400
    
    if not isinstance(item_ids, list) or not item_ids:
        return jsonify({"success": False, "message": "Geçersiz eşya seçimi."}), 400

    # --- Saat Dilimi Yönetimi (Bu kısım zaten doğru, aynı kalıyor) ---
    try:
        local_tz = pytz.timezone('Europe/Istanbul')
        local_start_dt = local_tz.localize(datetime.strptime(f"{date_str} {start_str}", "%Y-%m-%d %H:%M"))
        local_end_dt = local_tz.localize(datetime.strptime(f"{date_str} {end_str}", "%Y-%m-%d %H:%M"))
        
        if local_end_dt <= local_start_dt:
            return jsonify({"success": False, "message": "Bitiş saati, başlangıç saatinden sonra olmalı."}), 400

        # Veritabanı işlemleri için saatleri UTC'ye çevir
        utc_start_dt = local_start_dt.astimezone(pytz.utc)
        utc_end_dt = local_end_dt.astimezone(pytz.utc)
        parsed_date_utc = utc_start_dt.date()
        parsed_start_utc = utc_start_dt.time()
        parsed_end_utc = utc_end_dt.time()
    except (ValueError, pytz.exceptions.InvalidTimeError):
        return jsonify({"success": False, "message": "Tarih veya saat biçimi hatalı."}), 400
    # --- Saat Dilimi Yönetimi Bitiş ---


    # --- Yeni ve Gelişmiş Kontroller ---

    # 2. İstenen eşyaları veritabanından TEK BİR SORGUDAYLA çek ve doğrula
    requested_items = RentableItem.query.filter(RentableItem.id.in_(item_ids)).all()

    # Doğrulama: Frontend'den gelen ID sayısı ile veritabanından dönen eşya sayısı aynı mı?
    if len(requested_items) != len(item_ids):
        return jsonify({"success": False, "message": "Geçersiz veya bulunamayan bir eşya seçtiniz."}), 400

    # Doğrulama: Tüm eşyalar bu plaja mı ait? Bu, güvenlik için önemlidir.
    if not all(item.beach_id == beach_id for item in requested_items):
        return jsonify({"success": False, "message": "Eşyalar farklı plajlara ait olamaz."}), 400

    # 3. Günlük limit kontrolü
    GUNLUK_MAKSIMUM_ESYA = 10
    user_id = current_user.id
    reservations_today_count = Reservation.query.filter(
        Reservation.user_id == user_id, 
        Reservation.date == local_start_dt.date(), # Limit kontrolü kullanıcının yerel gününe göre yapılır
        Reservation.status.in_(['reserved', 'used'])
    ).count()

    if (reservations_today_count + len(item_ids)) > GUNLUK_MAKSIMUM_ESYA:
        return jsonify({"success": False, "message": f"Bir günde en fazla {GUNLUK_MAKSIMUM_ESYA} eşya rezerve edebilirsiniz."}), 400

    # 4. Çakışma kontrolü: Bu eşyalardan herhangi biri bu saatte başkası tarafından rezerve edilmiş mi?
    existing_reservation = Reservation.query.filter(
        Reservation.item_id.in_(item_ids),
        Reservation.date == parsed_date_utc,
        Reservation.start_time < parsed_end_utc,
        Reservation.end_time > parsed_start_utc,
        Reservation.status.in_(['reserved', 'used'])
    ).first()

    if existing_reservation:
        booked_item = RentableItem.query.get(existing_reservation.item_id)
        item_type_tr = booked_item.item_type.replace('_', ' ').title()
        message = f"Üzgünüz! Siz işlemi tamamlarken seçtiğiniz eşyalardan biri (#{booked_item.item_number} numaralı {item_type_tr}) başkası tarafından rezerve edildi."
        return jsonify({"success": False, "message": message}), 409 # 409 Conflict

    # --- Rezervasyonları Oluşturma ---
    try:
        total_price = 0
        newly_created_reservations = []

        for item in requested_items:
            # Her eşyanın kendi fiyatını toplama ekle
            total_price += item.price

            new_reservation = Reservation(
                beach_id=beach_id,
                user_id=user_id,
                item_id=item.id, # KRİTİK DEĞİŞİKLİK: Artık item_id'yi kaydediyoruz
                date=parsed_date_utc,
                start_time=parsed_start_utc,
                end_time=parsed_end_utc,
                status='reserved'
            )
            db.session.add(new_reservation)
            newly_created_reservations.append(new_reservation)

        # Tüm yeni rezervasyonları tek seferde veritabanına işle
        db.session.commit()
        
        # WebSocket için veri hazırlama (Socket.IO kullanıyorsanız)
        # Bu kısım eski kodunuzdan uyarlandı ve artık item bilgilerini içeriyor
        reservations_data_for_socket = []
        for res in newly_created_reservations:
            # res.item ilişkisi sayesinde item bilgilerine direkt ulaşabiliriz
            reservations_data_for_socket.append({
                'item_id': res.item_id,
                'item_number': res.item.item_number,
                'item_type': res.item.item_type,
                'reservation_id': res.id
            })
        
        socketio.emit("items_reserved", { # Event adı daha genel hale getirildi
            "beach_id": beach_id,
            "date": date_str,
            "reservations": reservations_data_for_socket
        }, broadcast=True)


        # Başarı yanıtını doğru toplam fiyatla döndür
        return jsonify({
            "success": True,
            "message": "Rezervasyon başarıyla oluşturuldu.",
            "summary": {
                "date": date_str,
                "start_time": start_str,
                "end_time": end_str,
                "item_count": len(item_ids),
                "total_price": float(total_price) # Decimal'i JSON uyumlu float'a çevir
            }
        })

    except IntegrityError:
        db.session.rollback()
        return jsonify({"success": False, "message": "Veritabanı hatası. Seçtiğiniz eşyalardan biri siz işlemi tamamlarken rezerve edilmiş olabilir. Lütfen sayfayı yenileyip tekrar deneyin."}), 409
    
    except Exception as e:
        db.session.rollback()
        # Hata durumunda loglama yapmak önemlidir
        current_app.logger.error(f"make_reservation sırasında beklenmedik hata: {e}")
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

    if reservation.status == 'cancelled':
        flash("Bu rezervasyon zaten daha önce iptal edilmiş.", "info")
        return redirect(url_for('reservations.my_reservations'))

    # Not: Veritabanındaki saatlerin UTC olduğunu varsayıyoruz, bu yüzden UTC now ile karşılaştırmak en doğrusu.
    # Ancak sunucunuz ve veritabanınız aynı saat dilimindeyse mevcut kodunuz da çalışır.
    # Daha sağlam bir yapı için: start_datetime = utc.localize(datetime.combine(...)) ve now = datetime.now(utc)
    start_datetime = datetime.combine(reservation.date, reservation.start_time)
    now = datetime.now()

    if start_datetime < now:
        flash("Başlangıç saati geçmiş bir rezervasyon iptal edilemez.", "danger")
        return redirect(url_for('reservations.my_reservations'))

    if start_datetime - now < timedelta(hours=1):
        flash("Rezervasyonun başlamasına 1 saatten az kaldığı için iptal edilemez.", "warning")
        return redirect(url_for('reservations.my_reservations'))

    reservation.status = 'cancelled'
    db.session.commit()
    
    # Doğru time_slot değişkeni burada oluşturuluyor
    time_slot = f"{reservation.start_time.strftime('%H:%M')}-{reservation.end_time.strftime('%H:%M')}"
    
    # 🧠 Şezlong boşaldı, bekleyen kullanıcı varsa onları kontrol et
    kontrol_et_ve_bildirim_listesi(
        beach_id=reservation.beach_id,
        bed_number=reservation.bed_number,
        date=reservation.date,
        time_slot=time_slot  # GÜNCELLENDİ: 'reservation.time_slot' yerine üstte oluşturulan değişken kullanılıyor
    )

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
@login_required
def notify_when_free():
    print("[DEBUG] notify_when_free route triggered", file=sys.stderr)

    try:
        data = request.get_json()
        print("[DEBUG] Gelen veri:", data, file=sys.stderr)

        beach_id = data.get("beach_id")
        bed_number = data.get("bed_number")
        date_str = data.get("date") # Değişken adını date_str olarak değiştirdik
        time_slot = data.get("time_slot")

        if not all([beach_id, bed_number, date_str, time_slot]):
            print("[ERROR] Eksik alanlar var", file=sys.stderr)
            return jsonify({"success": False, "message": "Eksik veri."}), 400

        # YENİ: Gelen metin formatındaki tarihi date objesine çeviriyoruz
        try:
            parsed_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            print(f"[ERROR] Geçersiz tarih formatı: {date_str}", file=sys.stderr)
            return jsonify({"success": False, "message": "Geçersiz tarih formatı."}), 400

        user_id = current_user.id

        existing = WaitingList.query.filter_by(
            user_id=user_id,
            beach_id=beach_id,
            bed_number=bed_number,
            date=parsed_date,         # GÜNCELLENDİ: Artık date objesi kullanılıyor
            time_slot=time_slot,
            notified=False
        ).first()

        if existing:
            print("[DEBUG] Zaten kayıt var", file=sys.stderr)
            return jsonify({"success": True, "message": "Bu şezlong için zaten bir bildirim talebiniz mevcut."}), 200

        yeni_kayit = WaitingList(
            user_id=user_id,
            beach_id=beach_id,
            bed_number=bed_number,
            date=parsed_date,         # GÜNCELLENDİ: Artık date objesi kullanılıyor
            time_slot=time_slot,
            notified=False,
            created_at=datetime.utcnow()
        )

        db.session.add(yeni_kayit)
        db.session.commit()

        print("[DEBUG] Yeni kayıt oluşturuldu", file=sys.stderr)
        return jsonify({"success": True, "message": "Bildirim talebiniz başarıyla alındı. Şezlong boşaldığında size haber vereceğiz."})

    except Exception as e:
        db.session.rollback() # Hata durumunda işlemi geri al
        print("[ERROR] Sunucu hatası:", e, file=sys.stderr)
        return jsonify({"success": False, "message": "Beklenmedik bir sunucu hatası oluştu."}), 500


def kontrol_et_ve_bildirim_listesi(beach_id, bed_number, date, time_slot):
    print("📥 Bildirim kontrolü başlatıldı", file=sys.stderr)
    print("WaitingList tablosu içeriği:", WaitingList.query.all(), file=sys.stderr)
    print(f"[DEBUG] Aranan şezlong: bed_number={bed_number}, date={date}, time_slot={time_slot}", file=sys.stderr)

    # Gelen time_slot değerini normalize et (örneğin: "09:00 - 13:00", "09:00–13:00")
    normalized_time_slot = time_slot.replace("–", "-").replace(" ", "").strip()

    # İlgili şezlong için tüm bekleyenleri çek (time_slot'ları sonra kontrol edeceğiz)
    bekleyenler = WaitingList.query.filter_by(
        beach_id=beach_id,
        bed_number=bed_number,
        date=date,
        notified=False
    ).all()

    # Uygun time_slot ile eşleşen kullanıcıları bul
    eslesenler = [
        entry for entry in bekleyenler
        if entry.time_slot.replace("–", "-").replace(" ", "").strip() == normalized_time_slot
    ]

    if not eslesenler:
        print("🚫 Bekleyen kullanıcı yok.", file=sys.stderr)
        return

    print(f"✅ {len(eslesenler)} kullanıcı bekliyor:", file=sys.stderr)

    for entry in eslesenler:
        user = User.query.get(entry.user_id)
        beach = Beach.query.get(beach_id)

        if user and user.email:
            print(f"📨 E-posta gönderiliyor: {user.email}", file=sys.stderr)

            success = send_notification_email(
                to_email=user.email,
                beach_name=beach.name if beach else "Plaj",
                bed_number=bed_number,
                date=date,
                time_slot=time_slot  # orijinal gösterimle gönderiyoruz
            )

            if success:
                entry.notified = True
                entry.notified_at = datetime.utcnow()
                print(f"✅ Gönderildi: {user.email}", file=sys.stderr)
            else:
                print(f"❌ Gönderim başarısız: {user.email}", file=sys.stderr)

    db.session.commit()
    print("📬 Tüm bildirimler işlendi.\n", file=sys.stderr)



def send_notification_email(to_email, beach_name, bed_number, date, time_slot):
    try:
        subject = "Şezlong Boşaldı 🎉"
        body = (
            f"Merhaba!\n\n"
            f"{date} tarihinde {beach_name} plajındaki {bed_number} numaralı şezlong artık boşta!\n"
            f"{time_slot} zaman aralığında rezervasyon yapabilirsiniz.\n\n"
            f"👉 Hemen kontrol et: https://edrelaxbeach.com/\n\n"
            f"Sevgiler,\nEdrelax Ekibi"
        )

        msg = Message(subject=subject, recipients=[to_email], body=body)
        mail.send(msg)
        print(f"[MAIL] E-posta gönderildi: {to_email}", file=sys.stderr)
        return True

    except Exception as e:
        print(f"[MAIL ERROR] Gönderilemedi: {to_email} - Hata: {e}", file=sys.stderr)
        return False

