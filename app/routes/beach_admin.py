from flask import Blueprint, render_template, session, redirect, url_for, request, flash, jsonify, current_app
from app.models import User, Beach, Reservation, RentableItem
from app.routes.reservations import kontrol_et_ve_bildirim_listesi
from datetime import datetime, timedelta, date, time
from pytz import timezone, utc
from app.extensions import db
from functools import wraps
from flask_login import login_required, current_user
from ..extensions import mail, socketio
from flask_mail import Message
from ..extensions import mail
from app.extensions import csrf
from threading import Thread
from collections import defaultdict
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
        total_items_count = len(beach.rentable_items)
        empty_items_count = total_items_count - active_reservations_count
        
        occupancy_rate = 0
        # total_items_count zaten yukarıda hesaplanmıştı.
        if total_items_count > 0:
            occupancy_rate = round((active_reservations_count / total_items_count) * 100)

        dashboard_data.append({
            'beach': beach,
            'active_reservations_today': active_reservations_count,
            'empty_items': empty_items_count,
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

@beach_admin_bp.route('/manage-items')
@beach_admin_required
def manage_items():
    """
    Yöneticinin seçili plajına ait tüm kiralanabilir eşyaları listeler.
    """
    # Session'dan aktif plajın ID'sini al
    beach_id = session.get('beach_id')
    if not beach_id:
        flash("Lütfen önce bir plaj seçin.", "warning")
        return redirect(url_for('beach_admin.dashboard'))

    # İlgili plajı ve tüm eşyalarını veritabanından çek
    beach = Beach.query.get_or_404(beach_id)
    items = db.session.query(RentableItem).filter_by(beach_id=beach.id).order_by(RentableItem.item_number).all()

    # Eşyaları şablonda kolayca göstermek için türlerine göre grupla
    items_by_type = defaultdict(list)
    for item in items:
        # Örn: 'standart_sezlong' -> 'Standart Sezlong'
        type_display_name = item.item_type.replace('_', ' ').title()
        items_by_type[type_display_name].append(item)

    # Yeni bir HTML şablonu kullanacağız
    return render_template(
        'beach_admin/manage_items.html',
        beach=beach,
        # items_by_type'ı alfabetik olarak sıralayarak gönderiyoruz
        items_by_type=dict(sorted(items_by_type.items()))
    )

# 2. Yeni Eşya Ekleme Fonksiyonu
@beach_admin_bp.route('/item/add', methods=['POST'])
@beach_admin_required
def add_item():
    """
    Seçili plaja yeni bir kiralanabilir eşya ekler.
    """
    beach_id = session.get('beach_id')
    if not beach_id:
        flash("İşlem yapılamadı, lütfen tekrar plaj seçin.", "danger")
        return redirect(url_for('beach_admin.dashboard'))

    # Formdan gelen verileri al
    item_type = request.form.get('item_type')
    item_number_str = request.form.get('item_number')
    price_str = request.form.get('price')

    # Doğrulama
    if not all([item_type, item_number_str, price_str]):
        flash('Eşya Türü, Numara ve Fiyat alanları zorunludur.', 'danger')
        return redirect(url_for('beach_admin.manage_items'))

    try:
        item_number = int(item_number_str)
        price = float(price_str)
    except (ValueError, TypeError):
        flash('Eşya Numarası ve Fiyat geçerli sayılar olmalıdır.', 'danger')
        return redirect(url_for('beach_admin.manage_items'))

    # Bu plajda bu numaraya sahip başka bir eşya var mı?
    existing_item = RentableItem.query.filter_by(beach_id=beach_id, item_number=item_number).first()
    if existing_item:
        flash(f'#{item_number} numaralı eşya bu plajda zaten mevcut.', 'warning')
        return redirect(url_for('beach_admin.manage_items'))

    # Yeni eşyayı oluştur ve kaydet
    new_item = RentableItem(
        beach_id=beach_id,
        item_type=item_type.strip().lower().replace(" ", "_"),
        item_number=item_number,
        price=price
    )
    db.session.add(new_item)
    db.session.commit()

    flash(f'{item_type.title()} (#{item_number}) başarıyla eklendi.', 'success')
    return redirect(url_for('beach_admin.manage_items'))


# 3. Eşya Silme Fonksiyonu
@beach_admin_bp.route('/item/<int:item_id>/delete', methods=['POST'])
@beach_admin_required
def delete_item(item_id):
    """
    Belirli bir kiralanabilir eşyayı siler.
    """
    item_to_delete = RentableItem.query.get_or_404(item_id)

    # GÜVENLİK KONTROLÜ: Bu eşyayı silmeye çalışanın, o eşyanın bulunduğu plajın yöneticisi olduğundan emin ol.
    if item_to_delete.beach.manager_id != current_user.id:
        flash("Bu işlemi yapmaya yetkiniz yok.", "danger")
        # abort(403) # Alternatif olarak erişim engellendi hatası verilebilir
        return redirect(url_for('beach_admin.dashboard'))

    db.session.delete(item_to_delete)
    db.session.commit()

    flash(f"#{item_to_delete.item_number} numaralı eşya başarıyla silindi.", "success")
    return redirect(url_for('beach_admin.manage_items'))

@beach_admin_bp.route('/item-occupancy')
@beach_admin_required
def item_occupancy():
    beach_id = session.get('beach_id')
    if not beach_id:
        flash("Lütfen önce bir plaj seçin.", "warning")
        return redirect(url_for('beach_admin.dashboard'))

    beach = Beach.query.get_or_404(beach_id)

    # 1. Kullanıcının seçtiği tarihi al, eğer tarih seçilmemişse bugünü varsay
    # URL'den ?date=YYYY-MM-DD şeklinde tarih alınacak
    selected_date_str = request.args.get('date', date.today().isoformat())
    try:
        selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
    except ValueError:
        flash("Geçersiz tarih formatı. Lütfen YYYY-MM-DD formatını kullanın.", "danger")
        return redirect(url_for('beach_admin.item_occupancy'))

    # 2. O plaja ait tüm kiralanabilir eşyaları çek
    all_items = RentableItem.query.filter_by(beach_id=beach.id).order_by(RentableItem.item_type, RentableItem.item_number).all()

    # 3. Seçilen tarihteki tüm aktif rezervasyonları TEK BİR SORGUDAYLA çek
    reservations_on_date = Reservation.query.filter(
        Reservation.beach_id == beach.id,
        Reservation.date == selected_date,
        Reservation.status.in_(['reserved', 'used'])
    ).all()

    # 4. Hızlı arama için rezervasyonları bir sözlüğe (dictionary) map'le
    # Anahtar: item_id, Değer: Reservation nesnesi
    reservation_map = {reservation.item_id: reservation for reservation in reservations_on_date}

    # 5. Şablona göndermek üzere veriyi işle ve türlerine göre grupla
    from collections import defaultdict
    occupancy_by_type = defaultdict(list)

    for item in all_items:
        # Bu eşyanın rezervasyon map'inde olup olmadığını kontrol et
        reservation_info = reservation_map.get(item.id)
        
        type_display_name = item.item_type.replace('_', ' ').title()
        occupancy_by_type[type_display_name].append({
            'item': item,
            'is_booked': reservation_info is not None,
            'reservation': reservation_info  # Şablonda daha fazla detay için (örn: kim rezerve etmiş)
        })

    # Yeni bir şablon dosyası kullanacağız
    return render_template(
        'beach_admin/item_occupancy.html',
        beach=beach,
        selected_date_str=selected_date_str,
        occupancy_data=dict(sorted(occupancy_by_type.items()))
    )

@beach_admin_bp.route('/item-schedule')
@login_required # veya @beach_admin_required
def item_schedule():
    
    # Adım 2: Aktif plajı session'dan al ve erişim kontrolü yap.
    beach_id = session.get('beach_id')
    if not beach_id:
        flash("Lütfen önce bir plaj seçin.", "warning")
        return redirect(url_for('beach_admin.dashboard'))

    beach = Beach.query.get_or_404(beach_id)
    if beach.manager_id != current_user.id:
        flash("Bu plajın zaman çizelgesini görüntüleme yetkiniz yok.", "danger")
        return redirect(url_for('beach_admin.dashboard'))

    # Adım 3: Tarih parametresini al. Bu kısım aynı kalabilir.
    date_str = request.args.get('date') or datetime.today().strftime('%Y-%m-%d')
    try:
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        selected_date = date.today()
        date_str = selected_date.isoformat()
        flash("Geçersiz tarih formatı, bugünün tarihi gösteriliyor.", "warning")

    # Adım 4: Verileri yeni modele göre çekelim.
    # Eskiden bed_count'a göre işlem yaparken, şimdi plaja ait tüm 'item'ları çekiyoruz.
    items = RentableItem.query.filter_by(beach_id=beach.id).order_by(RentableItem.item_type, RentableItem.item_number).all()
    
    # Seçilen tarihteki tüm aktif rezervasyonları tek bir sorguyla alalım. Bu daha verimli.
    reservations = Reservation.query.filter(
        Reservation.beach_id == beach.id,
        Reservation.date == selected_date,
        Reservation.status.in_(['reserved', 'used'])
    ).all()
    
    # Adım 5: Zaman aralıklarını oluşturalım. Bu kısım da benzer kalabilir.
    start_hour, end_hour = 9, 18
    hours = [f"{h:02d}:00" for h in range(start_hour, end_hour + 1)]

    # Adım 6: Şablon için yeni veri yapısını kuralım.
    # Artık 'bed_num' değil, 'item' nesnelerini temel alan bir yapı kuruyoruz.
    schedule_data = {}
    for item in items:
        # Her bir eşya için saatlik durumları tutan bir sözlük oluştur.
        schedule_data[item.id] = {
            "item_info": item, # Eşyanın tüm bilgileri
            "slots": {hour: {"status": "free", "user_info": None} for hour in hours}
        }

    # Adım 7: Rezervasyonları işleyerek zaman çizelgesini dolduralım.
    # Artık her rezervasyon için UTC->Local dönüşümü yapmak yerine,
    # veritabanındaki UTC saatleri doğrudan karşılaştırabiliriz. Bu daha basit ve güvenilirdir.
    for res in reservations:
        # Rezervasyonun hangi eşyaya ait olduğunu kontrol et
        if res.item_id in schedule_data:
            # Rezervasyonun saatlerini kullanarak ilgili slot'ları 'dolu' olarak işaretle
            current_hour = res.start_time.hour
            while current_hour < res.end_time.hour:
                hour_key = f"{current_hour:02d}:00"
                if hour_key in schedule_data[res.item_id]["slots"]:
                    user = User.query.get(res.user_id) # Kullanıcı bilgisini burada alalım
                    schedule_data[res.item_id]["slots"][hour_key] = {
                        "status": res.status,
                        "user_info": f"{user.first_name} {user.last_name}" if user else "Bilinmiyor"
                    }
                current_hour += 1

    return render_template(
        'beach_admin/item_schedule.html', # YENİ BİR ŞABLON GEREKECEK
        beach=beach,
        selected_date=date_str,
        hours=hours,
        schedule=schedule_data # Yeni veri yapısını şablona gönderiyoruz
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
                    "start_time": reservation.start_time.strftime('%H:%M'),
                    "end_time": reservation.end_time.strftime('%H:%M'),
                    "date": reservation.date.strftime('%Y-%m-%d')
                }
                
                # Rezervasyonu sil ve veritabanına işle
                db.session.delete(reservation)
                db.session.commit()

                # --- YENİ: ZAMAN DİLİMİ DÖNÜŞÜMÜ ---
                local_tz = pytz.timezone('Europe/Istanbul')
                utc_tz = pytz.timezone('utc')

                start_utc_time_obj = datetime.strptime(deleted_info['start_time'], '%H:%M').time()
                end_utc_time_obj = datetime.strptime(deleted_info['end_time'], '%H:%M').time()
                utc_date_obj = datetime.strptime(deleted_info['date'], '%Y-%m-%d').date()

                start_utc_dt = utc_tz.localize(datetime.combine(utc_date_obj, start_utc_time_obj))
                end_utc_dt = utc_tz.localize(datetime.combine(utc_date_obj, end_utc_time_obj))
                
                start_local_dt = start_utc_dt.astimezone(local_tz)
                end_local_dt = end_utc_dt.astimezone(local_tz)
                
                local_date_for_check = start_local_dt.date()
                local_time_slot_for_check = f"{start_local_dt.strftime('%H:%M')}-{end_local_dt.strftime('%H:%M')}"

                kontrol_et_ve_bildirim_listesi(
                    beach_id=deleted_info['beach_id'],
                    bed_number=deleted_info['bed_number'],
                    date=local_date_for_check,
                    time_slot=local_time_slot_for_check
                )
                # --------------------------------------------------------------------

                # Bu bölüm artık doğru anahtarları bulacağı için hata vermeyecek
                socketio.emit('status_updated', {
                    'beach_id': deleted_info['beach_id'],
                    'bed_number': deleted_info['bed_number'],
                    'time_slot': deleted_info['start_time'], # 'start_time' anahtarı artık mevcut
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





