from flask import Blueprint, render_template, session, redirect, url_for, request, flash, jsonify, current_app
from app.models import User, Beach, Reservation
from datetime import datetime, timedelta, date
from app.extensions import db
from functools import wraps
from flask_login import login_required, current_user
from ..extensions import mail, socketio
from flask_mail import Message
from ..extensions import mail
from app.extensions import csrf
from threading import Thread
import time


def send_confirmation_email(user_email, beach_name, bed_number, date, time_slot):
    subject = "Rezervasyon Onaylandı ✅"
    body = f"""Merhaba,

Rezervasyonunuz işletme tarafından onaylandı.

📍 Plaj: {beach_name}
🪑 Şezlong: {bed_number}
📅 Tarih: {date}
🕒 Saat: {time_slot}

İyi tatiller dileriz!
"""
    msg = Message(subject=subject, recipients=[user_email], body=body)
    mail.send(msg)

    
beach_admin_bp = Blueprint('beach_admin', __name__, url_prefix='/beach-admin')

# Yalnızca beach_admin rolündeki kullanıcılar erişebilsin
def beach_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('user_role') != 'beach_admin':
            return redirect(url_for('public.index'))
        return f(*args, **kwargs)
    return decorated_function

@beach_admin_bp.route('/dashboard')
@beach_admin_required
def dashboard():
    user_id = session.get('user_id')

    # Bu kullanıcıya ait plaj(lar)
    beaches = Beach.query.filter_by(manager_id=user_id).all()

    # ⏰ Güncel saat bilgisi
    current_time = datetime.now().strftime('%H:%M')

    # 🛠️ ÖNEMLİ: session'a beach_id yaz
    # ⚠️ Eğer beach_id zaten varsa, tekrar yazma
    if not session.get('beach_id') and beaches:
        session['beach_id'] = beaches[0].id


    return render_template(
        'beach_admin/dashboard.html',
        beaches=beaches,
        current_time=current_time
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
    user_id = session.get('user_id')

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
    user_id = session.get('user_id')
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
    user_id = session.get('user_id')
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
        return redirect(url_for('public.index')) # Veya uygun bir yönlendirme

    # 📅 Tarih parametresi (varsayılan: bugün)
    date_str = request.args.get('date') or datetime.today().strftime('%Y-%m-%d')
    selected_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date() # Tarih nesnesi olarak kalsın

    # ⏱️ Saat aralıkları (örn. 09:00 - 18:00)
    start_hour, end_hour = 9, 18 # Plajınızın çalışma saatlerine göre ayarlayabilirsiniz
    hours = [f"{h:02d}:00" for h in range(start_hour, end_hour + 1)]

    # 🛏️ Şezlong sayısı kadar başlangıç yapısı kur
    bed_count = beach.bed_count or 20 # Varsayılan şezlong sayısı
    bed_schedule_data = { # İsim değişikliği kafa karışıklığını önlemek için
        bed_num: {
            hour: {"status": "free", "time": hour, "reservation_id": None, "user_info": None} # Varsayılan değerler güncellendi
            for hour in hours
        }
        for bed_num in range(1, bed_count + 1)
    }

    # 📦 Belirtilen tarihteki tüm rezervasyonları al
    reservations_on_selected_date = Reservation.query.filter_by(beach_id=beach_id, date=selected_date_obj).all()

    for res in reservations_on_selected_date:
        bed_num = res.bed_number
        
        # Şezlong numarasının bed_schedule_data içinde olduğundan emin olalım
        if bed_num not in bed_schedule_data:
            # Bu durum, veritabanındaki bed_number'ın plajın toplam şezlong sayısından büyük olması 
            # veya 0 ya da negatif olması gibi bir veri tutarsızlığına işaret edebilir.
            # Şimdilik bu tür bir rezervasyonu atlayabilir veya loglayabilirsiniz.
            print(f"Uyarı: {res.id} ID'li rezervasyon için {bed_num} numaralı şezlong, takvimde bulunamadı.")
            continue

        user = User.query.get(res.user_id)
        user_info_str = f"{user.first_name} {user.last_name}" if user else "Bilinmiyor"
        user_email = user.email

        # Rezervasyonun geçerli olduğu saat dilimlerini belirle
        current_slot_time = res.start_time
        while current_slot_time < res.end_time:
            hour_key = current_slot_time.strftime("%H:00") # "09:00", "10:00" formatında

            if hour_key in bed_schedule_data[bed_num]: # Saatin tanımlı aralıkta olduğundan emin ol
                bed_schedule_data[bed_num][hour_key] = {
                    "status": res.status,  # Veritabanındaki gerçek status
                    "user_info": user_info_str,
                    "user_email": user_email,
                    "time": hour_key,
                    "reservation_id": res.id # Rezervasyon ID'si eklendi
                }
            
            # Bir sonraki saat dilimine geç (her slot 1 saatlik varsayılıyor)
            # datetime objesine çevirip 1 saat ekleyip tekrar time objesine dönüştürüyoruz
            current_dt_for_increment = datetime.combine(selected_date_obj, current_slot_time)
            next_slot_dt = current_dt_for_increment + timedelta(hours=1)
            current_slot_time = next_slot_dt.time()
            
            # Eğer bir sonraki slot, ana saat listemizin (hours) dışına taşıyorsa döngüden çık
            if current_slot_time.strftime("%H:00") not in hours and current_slot_time < res.end_time :
                 # Eğer rezervasyon bitiş saati tam saat başı değilse ve bir sonraki slot listemizde yoksa
                 # bu, son slotun kısmi olduğu anlamına gelebilir. Bu durumu nasıl ele alacağınız
                 # iş mantığınıza bağlı. Şimdilik, listemizdeki saat başlarını dolduruyoruz.
                 pass # Gerekirse burada ek mantık eklenebilir

    return render_template(
        'beach_admin/bed_schedule.html',
        beach=beach,
        selected_date=date_str, # Şablona orijinal string formatında gönderiyoruz
        hours=hours,
        bed_schedule=bed_schedule_data # Güncellenmiş veri
    )

@beach_admin_bp.route('/update-reservation-status', methods=['POST'])
@csrf.exempt # Gerekliyse
@login_required
def update_reservation_status():
    data = request.get_json()

    # 1. Veriyi Al ve Doğrula
    # Artık 'time_slots' adında bir liste bekliyoruz.
    time_slots = data.get('time_slots')
    new_status = data.get('new_status')
    beach_id = data.get('beach_id')
    bed_number = data.get('bed_number')
    date_str = data.get('date')

    # Gerekli tüm parametreler geldi mi?
    if not all([time_slots, new_status, beach_id, bed_number, date_str]):
        return jsonify({"success": False, "message": "Eksik veya geçersiz parametreler."}), 400
    
    # time_slots'un bir liste olduğundan emin olalım.
    if not isinstance(time_slots, list):
        return jsonify({"success": False, "message": "'time_slots' bir liste olmalıdır."}), 400

    updates_to_emit = []
    processed_count = 0

    try:
        # 2. Yetki Kontrolü
        target_beach = Beach.query.get(beach_id)
        if not target_beach or target_beach.manager_id != current_user.id:
            return jsonify({"success": False, "message": "Bu plaj için işlem yapma yetkiniz yok."}), 403

        selected_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()

        # 3. Ana İşlem Döngüsü
        for time_slot in time_slots:
            start_time_obj = datetime.strptime(time_slot, '%H:%M').time()
            end_time_obj = (datetime.combine(selected_date_obj, start_time_obj) + timedelta(hours=1)).time()

            # Olası mevcut rezervasyonu bul
            existing_reservation = Reservation.query.filter_by(
                beach_id=beach_id,
                bed_number=bed_number,
                date=selected_date_obj,
                start_time=start_time_obj
            ).first()

            if new_status == 'free':
                if existing_reservation:
                    # Silmeden önce emit için veriyi hazırla
                    updates_to_emit.append({
                        'beach_id': existing_reservation.beach_id,
                        'bed_number': existing_reservation.bed_number,
                        'time_slot': existing_reservation.start_time.strftime('%H:%M'),
                        'date': existing_reservation.date.strftime('%Y-%m-%d'),
                        'new_status': 'free',
                        'reservation_id': None,
                        'user_info': None
                    })
                    db.session.delete(existing_reservation)
                    processed_count += 1
            else: # 'reserved', 'used' gibi durumlar
                if existing_reservation:
                    # Mevcut rezervasyonun durumunu güncelle
                    existing_reservation.status = new_status
                    # Emit için veriyi hazırla
                    updates_to_emit.append({
                        'beach_id': existing_reservation.beach_id,
                        'bed_number': existing_reservation.bed_number,
                        'time_slot': existing_reservation.start_time.strftime('%H:%M'),
                        'date': existing_reservation.date.strftime('%Y-%m-%d'),
                        'new_status': existing_reservation.status,
                        'reservation_id': existing_reservation.id,
                        'user_info': f"{existing_reservation.user.first_name} {existing_reservation.user.last_name}" if existing_reservation.user else "Bilinmiyor"
                    })
                    processed_count += 1
                else:
                    # Yeni rezervasyon oluştur
                    new_reservation = Reservation(
                        beach_id=beach_id,
                        user_id=current_user.id,
                        bed_number=bed_number,
                        date=selected_date_obj,
                        start_time=start_time_obj,
                        end_time=end_time_obj,
                        status=new_status
                    )
                    db.session.add(new_reservation)
                    # ID'si commit sonrası atanacağı için, objeyi commit sonrası işleyeceğiz.
                    # Bu yüzden geçici bir placeholder ekleyebiliriz.
                    updates_to_emit.append(new_reservation) # Geçici olarak objeyi ekliyoruz
                    processed_count += 1

        # 4. Atomik Olarak Veritabanına İşle
        db.session.commit()

        # 5. Değişiklikleri Herkese Yayınla
        # Commit sonrası ID'leri belli olan yeni rezervasyonlar için veriyi son haline getir
        final_updates = []
        for update in updates_to_emit:
            if isinstance(update, Reservation): # Eğer bu yeni oluşturulmuş bir obje ise
                final_updates.append({
                    'beach_id': update.beach_id,
                    'bed_number': update.bed_number,
                    'time_slot': update.start_time.strftime('%H:%M'),
                    'date': update.date.strftime('%Y-%m-%d'),
                    'new_status': update.status,
                    'reservation_id': update.id, # Artık ID'si var
                    'user_info': f"{update.user.first_name} {update.user.last_name}" if update.user else "Bilinmiyor"
                })
            else: # Bu, silinmiş veya güncellenmiş bir rezervasyonun verisiydi
                final_updates.append(update)
        
        if final_updates:
            socketio.emit('multi_status_updated', {
                'updates': final_updates
            }, broadcast=True)

        # 6. Başarılı Yanıtı Döndür
        return jsonify({
            "success": True,
            "message": f"{processed_count} adet saat dilimi başarıyla '{new_status}' olarak güncellendi.",
            "updated_slots": final_updates # İsteği yapan tarayıcıya da tüm güncel veriyi yolla
        })

    except Exception as e:
        db.session.rollback() # Hata anında tüm işlemleri geri al!
        current_app.logger.error(f"Çoklu rezervasyon güncellenirken hata: {e}")
        return jsonify({"success": False, "message": f"Sunucu hatası: {str(e)}"}), 500




def delayed_confirmation_check(app, reservation_id):
    time.sleep(5)
    print(f"[DEBUG] Mail trigger geldi: res_id={reservation_id}")


    with app.app_context():
        current_res = Reservation.query.get(reservation_id)

        if not current_res:
            return

        # Aynı kullanıcı, plaj, yatak, tarih, status için kontrol
        same_slots = Reservation.query.filter_by(
            user_id=current_res.user_id,
            beach_id=current_res.beach_id,
            bed_number=current_res.bed_number,
            date=current_res.date,
            status='used'
        ).all()

        # Zaten onaylanmış varsa, bir daha mail gönderme
        if any(res.confirmation_sent for res in same_slots):
            return

        try:
            send_confirmation_email(
                user_email=current_res.user.email,
                beach_name=current_res.beach.name if current_res.beach else "Bilinmeyen Plaj",
                bed_number=current_res.bed_number,
                date=str(current_res.date),
                time_slot=f"{current_res.start_time} - {current_res.end_time}"
            )

            current_res.confirmation_sent = True
            db.session.commit()
        except Exception as e:
            app.logger.warning(f"❌ Mail gönderim hatası: {e}")





