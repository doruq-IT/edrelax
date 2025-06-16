from flask import Blueprint, render_template, session, redirect, url_for, request, flash, jsonify, current_app
from app.models import User, Beach, Reservation
from app.routes.reservations import kontrol_et_ve_bildirim_listesi
from datetime import datetime, timedelta, date
from pytz import timezone, utc
from app.extensions import db
from functools import wraps
from flask_login import login_required, current_user
from ..extensions import mail, socketio
from flask_mail import Message
from ..extensions import mail
from app.extensions import csrf
from threading import Thread
import time
import pytz

def send_confirmation_email(user_email, beach_name, bed_number, date, time_slot):
    local_tz = timezone("Europe/Istanbul")

    try:
        # Örn: "06:00-15:00"
        start_utc_str, end_utc_str = time_slot.split("-")
        dt_date = datetime.strptime(date.strip(), "%Y-%m-%d").date()

        start_time = datetime.strptime(start_utc_str.strip(), "%H:%M").time()
        end_time = datetime.strptime(end_utc_str.strip(), "%H:%M").time()

        # UTC datetime objeleri
        # Bu satırların çalışması için dosyanın başında 'from pytz import utc' olmalı
        start_utc_dt = utc.localize(datetime.combine(dt_date, start_time))
        end_utc_dt = utc.localize(datetime.combine(dt_date, end_time))

        # Yerel saate dönüştür
        start_local_str = start_utc_dt.astimezone(local_tz).strftime("%H:%M")
        end_local_str = end_utc_dt.astimezone(local_tz).strftime("%H:%M")

        time_slot_local = f"{start_local_str} - {end_local_str}"

    except Exception as e:
        # GÜNCELLEME: Hata oluşursa bunu loglayalım.
        # Böylece bir sorun olduğunda terminalde veya log dosyanızda görürsünüz.
        current_app.logger.error(f"E-posta için saat dönüşümü başarısız oldu: {e}. Fallback olarak UTC kullanılıyor.")
        time_slot_local = time_slot  # fallback (UTC olarak kalır)

    subject = "Rezervasyon Onaylandı ✅"
    body = f"""Merhaba,

Rezervasyonunuz işletme tarafından onaylandı.

📍 Plaj: {beach_name}
🪑 Şezlong: {bed_number}
📅 Tarih: {date}
🕒 Saat: {time_slot_local}

İyi tatiller dileriz!
"""
    msg = Message(subject=subject, recipients=[user_email], body=body)
    mail.send(msg)

    
beach_admin_bp = Blueprint('beach_admin', __name__, url_prefix='/beach-admin')

# Yalnızca beach_admin rolündeki kullanıcılar erişebilsin
def beach_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 1. Önce kimliğin doğrulanıp doğrulanmadığını KONTROL ET
        if not current_user.is_authenticated:
            flash("Bu sayfayı görüntülemek için giriş yapmalısınız.", "warning")
            return redirect(url_for('auth.login'))
        # 2. Sonra rolünün doğru olup olmadığını KONTROL ET
        if current_user.role != 'beach_admin':
            flash("Bu sayfaya erişim yetkiniz yok.", "danger")
            return redirect(url_for('public.index'))
        return f(*args, **kwargs)
    return decorated_function

@beach_admin_bp.route('/dashboard')
@beach_admin_required
def dashboard():
    user_id = current_user.id
    beaches = Beach.query.filter_by(manager_id=user_id).all()
    today = date.today()
    
    # 1. Otomatik plaj seçimi (birden fazla plajı olan yöneticiler için)
    if not session.get('beach_id') and beaches:
        session['beach_id'] = beaches[0].id

    # 2. Şablona göndermek için işlenmiş veri listesi oluştur
    dashboard_data = []
    for beach in beaches:
        # Sadece bugüne ait ve durumu 'reserved' veya 'used' olanları say
        active_reservations_count = Reservation.query.filter(
            Reservation.beach_id == beach.id,
            Reservation.date == today,
            Reservation.status.in_(['reserved', 'used'])
        ).count()

        # Boş şezlong sayısını hesapla
        empty_sunbeds = beach.bed_count - active_reservations_count
        
        # Doluluk oranını hesapla
        occupancy_rate = 0
        if beach.bed_count and beach.bed_count > 0:
            occupancy_rate = round((active_reservations_count / beach.bed_count) * 100)

        dashboard_data.append({
            'beach': beach,
            'active_reservations_today': active_reservations_count,
            'empty_sunbeds': empty_sunbeds,
            'occupancy_rate_today': occupancy_rate
        })
        
    return render_template(
        'beach_admin/dashboard.html',
        # Eski 'beaches' yerine işlenmiş 'dashboard_data' listesini gönderiyoruz
        dashboard_data=dashboard_data, 
        current_time=datetime.now().strftime('%H:%M')
    )

@beach_admin_bp.route('/complete-past-reservations/<int:beach_id>', methods=['POST'])
@login_required
def complete_past_reservations(beach_id):
    today = date.today()
    try:
        beach = Beach.query.get_or_404(beach_id)
        if beach.manager_id != current_user.id:
            return jsonify({
                "success": False,
                "message": "Bu işlem için yetkiniz yok."
            }), 403

        # Güncellenecek rezervasyonları bul
        reservations_to_update = Reservation.query.filter(
            Reservation.beach_id == beach_id,
            Reservation.date < today,  # Tarihi bugünden küçük olanlar
            Reservation.status.in_(['reserved', 'used'])  # Durumu 'reserved' veya 'used' olanlar
        ).all()

        updated_count = 0  # Gerçek sayıyı sonra hesaplayacağız
        if reservations_to_update:
            for res in reservations_to_update:
                res.status = 'completed'
                updated_count += 1

        db.session.commit()  # Değişiklikleri veritabanına kaydet

        # Başarılı yanıt
        return jsonify({
            "success": True,
            "message": f"{updated_count} adet geçmiş rezervasyon 'Tamamlandı' olarak işaretlendi."
        })

    except Exception as e:
        current_app.logger.error(f"Geçmiş rezervasyonlar tamamlanırken hata: {e}")
        db.session.rollback()  # Hata durumunda veritabanı işlemlerini geri al
        return jsonify({
            "success": False,
            "message": f"Bir hata oluştu: {str(e)}"
        }), 500


@beach_admin_bp.route('/select-beach', methods=['GET', 'POST'])
@login_required
def select_beach():
    user_id = current_user.id
    beaches = Beach.query.filter_by(manager_id=user_id).all()

    if not beaches:
        flash("Size atanmış bir plaj bulunamadı.", "warning")
        return redirect(url_for('public.index'))

    # Tek plaj varsa otomatik atayıp yönlendir
    if len(beaches) == 1:
        session['beach_id'] = beaches[0].id
        return redirect(url_for('beach_admin.dashboard'))

    if request.method == 'POST':
        selected_id = request.form.get('beach_id')
        session['beach_id'] = int(selected_id)
        return redirect(url_for('beach_admin.dashboard'))

    return render_template('beach_admin/select_beach.html', beaches=beaches)


@beach_admin_bp.route('/reservations')
@beach_admin_required
def reservations():
    from datetime import datetime
    user_id = current_user.id

    # Bu adminin yönettiği plaj(lar)
    beaches = Beach.query.filter_by(manager_id=user_id).all()
    beach_ids = [b.id for b in beaches]

    # Sadece kendi plajlarına ait rezervasyonlar
    reservations = Reservation.query \
        .filter(Reservation.beach_id.in_(beach_ids)) \
        .order_by(Reservation.date.desc(), Reservation.start_time.desc()) \
        .all()

    return render_template('beach_admin/beach_admin_reservations.html',
                           reservations=reservations)

@beach_admin_bp.route('/beds', methods=["GET", "POST"])
@beach_admin_required # Kullandığınız decorator
def manage_beds():
    user_id = current_user.id
    # Yöneticiye ait ham plaj nesnelerini al
    beaches_query_result = Beach.query.filter_by(manager_id=user_id).all()

    if request.method == "POST":
        for beach_instance in beaches_query_result: # beaches_query_result üzerinden dönerek doğrudan güncelleme
            new_count_str = request.form.get(f"bed_count_{beach_instance.id}")
            if new_count_str and new_count_str.isdigit():
                new_count = int(new_count_str)
                # Opsiyonel: Eğer yeni sayı, o gün için aktif rezervasyonlardan azsa bir uyarı verebilirsiniz
                # (Bu daha karmaşık bir kontrol olurdu, şimdilik eklemiyorum)
                beach_instance.bed_count = new_count
            # 2️⃣ Yeni fiyatı al
            new_price_str = request.form.get(f"bed_price_{beach_instance.id}")
            if new_price_str:
                try:
                    new_price = float(new_price_str)
                    if beach_instance.price != new_price:
                        beach_instance.price = new_price
                except ValueError:
                    flash(f"{beach_instance.name} için geçersiz fiyat girdiniz.", "danger")
        db.session.commit()
        flash("Şezlong sayıları başarıyla güncellendi.", "success")
        return redirect(url_for('beach_admin.manage_beds'))

    # GET isteği için plaj verilerini işle ve şablona gönder
    processed_beaches_data = []
    today = date.today()

    for beach_obj in beaches_query_result:
        # Bugün için 'reserved' veya 'used' durumundaki aktif rezervasyonları say
        active_reservations_today = Reservation.query.filter(
            Reservation.beach_id == beach_obj.id,
            Reservation.date == today,
            Reservation.status.in_(['reserved', 'used']) # Sadece aktif kabul edilen durumlar
        ).count()
        
        occupancy_rate_today = 0
        if beach_obj.bed_count and beach_obj.bed_count > 0:
            occupancy_rate_today = round((active_reservations_today / beach_obj.bed_count) * 100)
        else:
            occupancy_rate_today = 0 # Şezlong sayısı 0 ise doluluk da 0'dır
        
        processed_beaches_data.append({
            'id': beach_obj.id,
            'name': beach_obj.name,
            'bed_count': beach_obj.bed_count,
            'price': beach_obj.price,
            'active_reservations_today': active_reservations_today,
            'occupancy_rate_today': occupancy_rate_today
        })

    return render_template('beach_admin/manage_beds.html', beaches=processed_beaches_data)

@beach_admin_bp.route('/occupancy')
@beach_admin_required # Kullandığınız decorator
def bed_occupancy():
    user_id = current_user.id
    beaches_query_result = Beach.query.filter_by(manager_id=user_id).all()

    labels = []
    data = [] # Yüzdelik doluluk oranları
    detailed_data = [] # Daha detaylı bilgi için (isteğe bağlı, şablonda kullanılabilir)

    today = date.today()

    for beach_obj in beaches_query_result:
        total_beds = beach_obj.bed_count or 0 # Şezlong sayısı 0 veya None ise 0 kabul et
        
        # Bugün için 'reserved' veya 'used' durumundaki aktif rezervasyonları say
        active_reservations_today = Reservation.query.filter(
            Reservation.beach_id == beach_obj.id,
            Reservation.date == today,
            Reservation.status.in_(['reserved', 'used']) # Sadece aktif kabul edilen durumlar
        ).count()

        percent_occupancy = 0
        if total_beds > 0:
            percent_occupancy = round((active_reservations_today / total_beds) * 100, 2)
        
        labels.append(beach_obj.name)
        data.append(percent_occupancy)
        detailed_data.append({ # Şablonda daha fazla detay göstermek isterseniz
            "name": beach_obj.name,
            "total_beds": total_beds,
            "active_reservations": active_reservations_today,
            "occupancy_rate": percent_occupancy
        })

    return render_template(
        'beach_admin/bed_occupancy.html',
        # beaches=beaches_query_result, # Eğer şablonda ham beach nesnelerine ihtiyaç yoksa kaldırılabilir
        labels=labels,
        data=data,
        detailed_beach_data=detailed_data # Şablona yeni detaylı veri gönderiyoruz
    )

@beach_admin_bp.route('/beach/<int:beach_id>/bed-schedule', methods=['GET'])
@login_required # veya @beach_admin_required
def bed_schedule(beach_id):
    beach = Beach.query.get_or_404(beach_id)

    # 🔒 Erişim kontrolü
    if beach.manager_id != current_user.id:
        flash("Bu plaja erişim izniniz yok.", "danger")
        return redirect(url_for('public.index'))

    # 📅 Tarih parametresi (varsayılan: bugün)
    date_str = request.args.get('date') or datetime.today().strftime('%Y-%m-%d')
    selected_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()

    # --- YENİ: SAAT DİLİMİ TANIMLAMALARI ---
    local_tz = pytz.timezone('Europe/Istanbul')
    utc_tz = pytz.utc

    # ⏱️ Saat aralıkları (plajınızın çalışma saatlerine göre)
    start_hour, end_hour = 9, 18
    hours = [f"{h:02d}:00" for h in range(start_hour, end_hour + 1)]

    # 🛏️ Şezlong sayısı kadar boş bir takvim yapısı kur
    bed_count = beach.bed_count or 20
    bed_schedule_data = {
        bed_num: {
            hour: {"status": "free", "time": hour, "reservation_id": None, "user_info": None}
            for hour in hours
        }
        for bed_num in range(1, bed_count + 1)
    }

    date_range_to_check = [selected_date_obj, selected_date_obj - timedelta(days=1)]
    
    reservations_to_process = Reservation.query.filter(
        Reservation.beach_id == beach_id,
        Reservation.date.in_(date_range_to_check)
    ).all()


    for res in reservations_to_process:
        bed_num = res.bed_number
        if bed_num not in bed_schedule_data:
            print(f"Uyarı: {res.id} ID'li rezervasyon için {bed_num} numaralı şezlong, takvimde bulunamadı.")
            continue

        # --- YENİ: REZERVASYON SAATLERİNİ YEREL SAAATE ÇEVİR ---
        # 1. Veritabanındaki UTC tarih ve saatleri birleştirip UTC saat dilimini ata
        # Bu satır, "naive" datetime'ı "aware" hale getirir.
        utc_start_time = utc_tz.localize(datetime.combine(res.date, res.start_time))
        utc_end_time = utc_tz.localize(datetime.combine(res.date, res.end_time))

        # 2. Bu UTC saatleri, plaj yöneticisinin göreceği yerel saate çevir
        local_start_time = utc_start_time.astimezone(local_tz)
        local_end_time = utc_end_time.astimezone(local_tz)

        # --- YENİ FİLTRELEME: Bu rezervasyon bizim takvim günümüze ait mi? ---
        # Eğer rezervasyonun yerel başlangıç günü, takvimde seçilen günden farklıysa, bu rezervasyonu atla.
        if local_start_time.date() != selected_date_obj:
            continue

        user = User.query.get(res.user_id)
        user_info_str = f"{user.first_name} {user.last_name}" if user else "Bilinmiyor"
        user_email = user.email if user else None

        # --- GÜNCELLENMİŞ: REZERVASYON SÜRESİ KADAR DÖNGÜ KUR ---
        # Rezervasyonun geçerli olduğu her saat dilimi için takvimi doldur
        current_hour_slot = local_start_time
        while current_hour_slot < local_end_time:
            hour_key = current_hour_slot.strftime("%H:00") # "09:00", "10:00" formatında

            if hour_key in bed_schedule_data[bed_num]:
                bed_schedule_data[bed_num][hour_key] = {
                    "status": res.status,
                    "user_info": user_info_str,
                    "user_email": user_email,
                    "time": hour_key,
                    "reservation_id": res.id
                }
            
            # Bir sonraki saate geç
            current_hour_slot += timedelta(hours=1)

    return render_template(
        'beach_admin/bed_schedule.html',
        beach=beach,
        selected_date=date_str,
        hours=hours,
        bed_schedule=bed_schedule_data
    )
    
@beach_admin_bp.route('/update-reservation-status', methods=['POST'])
@login_required
def update_reservation_status():
    from pytz import timezone, utc
    local_tz = timezone('Europe/Istanbul')

    data = request.get_json()

    reservation_id = data.get('reservation_id')
    new_status = data.get('new_status')
    bed_number = data.get('bed_number')
    beach_id = data.get('beach_id')
    date_str = data.get('date')
    time_slot = data.get('time_slot')  # Örn: "09:00"
    end_time_str = data.get('end_time')  # Örn: "12:00"

    allowed_statuses = ['reserved', 'used', 'cancelled', 'free']
    if not new_status or new_status not in allowed_statuses:
        return jsonify({"success": False, "message": "Geçersiz durum bilgisi."}), 400

    try:
        # ✅ 1. Güncelleme
        if reservation_id:
            reservation = Reservation.query.get(reservation_id)
            if not reservation:
                return jsonify({"success": False, "message": "Rezervasyon bulunamadı."}), 404

            if reservation.beach.manager_id != current_user.id:
                return jsonify({"success": False, "message": "Yetkiniz yok."}), 403

            if new_status == 'free':
                # Önce silinecek rezervasyonun bilgilerini alalım
                deleted_info = {
                    "beach_id": reservation.beach_id,
                    "bed_number": reservation.bed_number,
                    "utc_start_time_str": reservation.start_time.strftime('%H:%M'),
                    "utc_end_time_str": reservation.end_time.strftime('%H:%M'),
                    "utc_date_str": reservation.date.strftime('%Y-%m-%d')
                }
                
                # Rezervasyonu sil ve veritabanına işle
                db.session.delete(reservation)
                db.session.commit()

                # --- YENİ: ZAMAN DİLİMİ DÖNÜŞÜMÜ ---
                local_tz = pytz.timezone('Europe/Istanbul')
                utc_tz = pytz.utc

                # UTC stringlerini tekrar zaman nesnelerine çevir
                start_utc_time_obj = datetime.strptime(deleted_info['utc_start_time_str'], '%H:%M').time()
                end_utc_time_obj = datetime.strptime(deleted_info['utc_end_time_str'], '%H:%M').time()
                utc_date_obj = datetime.strptime(deleted_info['utc_date_str'], '%Y-%m-%d').date()

                # Zaman dilimi farkında (aware) UTC nesneleri oluştur
                start_utc_dt = utc_tz.localize(datetime.combine(utc_date_obj, start_utc_time_obj))
                end_utc_dt = utc_tz.localize(datetime.combine(utc_date_obj, end_utc_time_obj))
                
                # Türkiye saatine çevir
                start_local_dt = start_utc_dt.astimezone(local_tz)
                end_local_dt = end_utc_dt.astimezone(local_tz)
                
                # Yerel saatlerden arama için parametreleri oluştur
                local_date_for_check = start_local_dt.date()
                local_time_slot_for_check = f"{start_local_dt.strftime('%H:%M')}-{end_local_dt.astimezone(local_tz).strftime('%H:%M')}"

                # Bildirim kontrol fonksiyonunu YEREL saatlerle çağır
                kontrol_et_ve_bildirim_listesi(
                    beach_id=deleted_info['beach_id'],
                    bed_number=deleted_info['bed_number'],
                    date=local_date_for_check,
                    time_slot=local_time_slot_for_check
                )

                socketio.emit('status_updated', {
                    'beach_id': deleted_info['beach_id'],
                    'bed_number': deleted_info['bed_number'],
                    'time_slot': deleted_info['start_time'],
                    'end_time': deleted_info['end_time'],
                    'date': deleted_info['date'],
                    'new_status': 'free',
                    'reservation_id': None,
                    'user_info': None
                }, broadcast=True)

                return jsonify({
                    "success": True,
                    "message": "Rezervasyon iptal edildi.",
                    "new_status": "free",
                    "reservation_id": None
                })

            else:
                reservation.status = new_status
                if new_status == 'used' and data.get('mail_trigger'):
                    app_ctx = current_app._get_current_object()
                    Thread(target=delayed_confirmation_check, args=(app_ctx, reservation.id)).start()

                db.session.commit()

                socketio.emit('status_updated', {
                    'beach_id': reservation.beach_id,
                    'bed_number': reservation.bed_number,
                    'time_slot': reservation.start_time.strftime('%H:%M'),
                    'date': reservation.date.strftime('%Y-%m-%d'),
                    'new_status': reservation.status,
                    'reservation_id': reservation.id,
                    'user_info': f"{reservation.user.first_name} {reservation.user.last_name}" if reservation.user else "Bilinmiyor"
                }, broadcast=True)

                return jsonify({
                    "success": True,
                    "message": "Rezervasyon durumu güncellendi.",
                    "new_status": reservation.status,
                    "reservation_id": reservation.id
                })

        # ✅ 2. Yeni rezervasyon oluştur
        elif new_status != 'free' and bed_number and beach_id and date_str and time_slot and end_time_str:
            beach = Beach.query.get(beach_id)
            if not beach or beach.manager_id != current_user.id:
                return jsonify({"success": False, "message": "Yetkiniz yok."}), 403

            try:
                # Kullanıcının gönderdiği yerel saatleri UTC'ye çevir
                local_start = local_tz.localize(datetime.strptime(f"{date_str} {time_slot}", "%Y-%m-%d %H:%M"))
                local_end = local_tz.localize(datetime.strptime(f"{date_str} {end_time_str}", "%Y-%m-%d %H:%M"))
                utc_start = local_start.astimezone(utc)
                utc_end = local_end.astimezone(utc)

                parsed_date_utc = utc_start.date()
                parsed_start_utc = utc_start.time()
                parsed_end_utc = utc_end.time()

            except Exception as e:
                return jsonify({"success": False, "message": f"Saat dönüşüm hatası: {str(e)}"}), 400

            conflict = Reservation.query.filter(
                Reservation.beach_id == beach_id,
                Reservation.bed_number == bed_number,
                Reservation.date == parsed_date_utc,
                Reservation.start_time < parsed_end_utc,
                Reservation.end_time > parsed_start_utc,
                Reservation.status.in_(['reserved', 'used'])
            ).first()

            if conflict:
                return jsonify({"success": False, "message": "Bu saat diliminde zaten rezervasyon var."}), 409

            new_res = Reservation(
                beach_id=beach_id,
                user_id=current_user.id,
                bed_number=bed_number,
                date=parsed_date_utc,
                start_time=parsed_start_utc,
                end_time=parsed_end_utc,
                status=new_status
            )
            db.session.add(new_res)
            db.session.commit()

            socketio.emit('status_updated', {
                'beach_id': new_res.beach_id,
                'bed_number': new_res.bed_number,
                'time_slot': new_res.start_time.strftime('%H:%M'),
                'date': new_res.date.strftime('%Y-%m-%d'),
                'new_status': new_res.status,
                'reservation_id': new_res.id,
                'user_info': f"{new_res.user.first_name} {new_res.user.last_name}" if new_res.user else "Bilinmiyor"
            }, broadcast=True)

            return jsonify({
                "success": True,
                "message": f"Yeni rezervasyon eklendi.",
                "new_status": new_res.status,
                "reservation_id": new_res.id
            })

        else:
            return jsonify({"success": False, "message": "Eksik veri gönderildi."}), 400

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"update_reservation_status hatası: {e}")
        return jsonify({"success": False, "message": f"Sunucu hatası: {str(e)}"}), 500


# beach_admin.py dosyanızdaki mevcut fonksiyonu bununla değiştirin

def delayed_confirmation_check(app, reservation_id):
    # E-postanın anında gitmemesi için küçük bir bekleme süresi hala mantıklı
    time.sleep(2) 
    print(f"[DEBUG] Mail trigger geldi: res_id={reservation_id}")

    with app.app_context():
        try:
            # --- YENİ ATOMİK GÜNCELLEME MANTIĞI ---
            # Tek bir işlemde, sadece confirmation_sent=False olan kaydı güncellemeye çalışıyoruz.
            # .update() metodu, kaç adet satırın güncellendiğini sayı olarak döndürür.
            updated_rows = db.session.query(Reservation).filter(
                Reservation.id == reservation_id,
                Reservation.confirmation_sent == False
            ).update({"confirmation_sent": True}, synchronize_session=False)

            db.session.commit()
            # -----------------------------------------

            # EĞER updated_rows 1 ise, bu işlemi ilk kez bizim yaptığımız anlamına gelir.
            # Yani yarışı biz kazandık ve e-postayı göndermeliyiz.
            if updated_rows > 0:
                print(f"[SUCCESS] Mail gönderme yarışı kazanıldı: res_id={reservation_id}. E-posta gönderiliyor.")
                
                # E-postayı göndermek için rezervasyon bilgilerini tekrar alalım
                current_res = Reservation.query.get(reservation_id)
                if not current_res:
                    return # Rezervasyon bir şekilde silindiyse devam etme

                # E-posta gönderme fonksiyonunu çağır
                send_confirmation_email(
                    user_email=current_res.user.email,
                    beach_name=current_res.beach.name if current_res.beach else "Bilinmeyen Plaj",
                    bed_number=current_res.bed_number,
                    date=str(current_res.date),
                    # ÖNEMLİ DÜZELTME: time_slot'u doğru formatta gönderdiğinizden emin olalım
                    time_slot=f"{current_res.start_time.strftime('%H:%M')}-{current_res.end_time.strftime('%H:%M')}"
                )

            # EĞER updated_rows 0 ise, bizden önce başka bir thread bu kaydı zaten güncellemiş demektir.
            # Bu yüzden hiçbir şey yapmamalıyız.
            else:
                print(f"[INFO] Mail gönderme yarışı kaybedildi: res_id={reservation_id}. E-posta gönderilmeyecek.")

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"❌ delayed_confirmation_check içinde hata oluştu: {e}")





