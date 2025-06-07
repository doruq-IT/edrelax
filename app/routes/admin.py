# app/routes/admin.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, jsonify
from app.extensions import db
from app.models import Beach, User
from functools import wraps
import os
import time
from werkzeug.utils import secure_filename
from flask_login import login_required, current_user
from google.cloud import storage
import uuid

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png'}
MAX_FILE_SIZE_MB = 5

def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def is_file_too_large(file):
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    return size > (MAX_FILE_SIZE_MB * 1024 * 1024)


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("You must be logged in.", "warning")
            return redirect(url_for("auth.login"))

        admin_emails = current_app.config.get("ADMIN_EMAILS", [])
        if current_user.email not in admin_emails:
            flash("Access denied. Admins only.", "danger")
            return redirect(url_for("public.index"))

        return f(*args, **kwargs)
    return decorated_function


@admin_bp.route('/beaches', methods=['GET', 'POST'])
@admin_required
def beaches():
    image_folder = os.path.join(current_app.static_folder, 'images')
    os.makedirs(image_folder, exist_ok=True)

    image_files = [f for f in os.listdir(image_folder) if f.lower().endswith(('.jpg', '.png', '.jpeg'))]

    if request.method == 'POST':
        name = request.form.get('name')
        location = request.form.get('location')
        description = request.form.get('description')
        long_description = request.form.get('long_description')
        slug = request.form.get('slug')
        latitude = request.form.get('latitude', type=float)
        longitude = request.form.get('longitude', type=float)
        price = request.form.get('price', type=float) or 0.0
        bed_count = request.form.get('bed_count', type=int) or 0

        if Beach.query.filter_by(slug=slug).first():
            flash("This slug is already in use.", "warning")
            return redirect(url_for("admin.beaches"))

        uploaded_file = request.files.get('image_upload')
        # --- GCS İÇİN DEĞİŞTİRİLDİ ---
        if uploaded_file and uploaded_file.filename.strip():
            if not allowed_file(uploaded_file.filename):
                flash("Only JPG and PNG files are allowed.", "danger")
                return redirect(url_for("admin.beaches"))

            if is_file_too_large(uploaded_file):
                flash("Image file is too large. Max 5MB allowed.", "danger")
                return redirect(url_for("admin.beaches"))

            # GCS'e yükleme mantığı
            filename = secure_filename(uploaded_file.filename)
            unique_filename = str(uuid.uuid4()) + "-" + filename
            
            storage_client = storage.Client()
            bucket_name = current_app.config['GCS_BUCKET_NAME']
            bucket = storage_client.bucket(bucket_name)

            blob = bucket.blob(unique_filename)
            blob.upload_from_file(
                uploaded_file,
                content_type=uploaded_file.content_type
            )
            image_url = blob.public_url # Veritabanına kaydedilecek URL
        # --- GCS İÇİN DEĞİŞTİRİLDİ BİTTİ ---

        if not image_url:
            image_url = '/static/images/default.jpg'

        new_beach = Beach(
            name=name,
            location=location,
            description=description,
            long_description=long_description,
            image_url=image_url,
            slug=slug,
            latitude=latitude,
            longitude=longitude,
            price=price,
            bed_count=bed_count,
            has_booking=bool(request.form.get('has_booking')),
            has_food=bool(request.form.get('has_food')),
            has_parking=bool(request.form.get('has_parking')),
            allows_pets=bool(request.form.get('allows_pets')),
            has_wifi=bool(request.form.get('has_wifi')),
            has_water_sports=bool(request.form.get('has_water_sports')),
            is_disabled_friendly=bool(request.form.get('is_disabled_friendly'))
        )

        try:
            db.session.add(new_beach)
            db.session.commit()
            flash("Beach added successfully.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred while adding the beach: {e}", "danger")

        return redirect(url_for("admin.beaches"))
    
    all_beaches = Beach.query.order_by(Beach.id.desc()).all()
    return render_template("admin_beaches.html", beaches=all_beaches, image_files=image_files)


@admin_bp.route('/beaches/delete/<int:beach_id>', methods=['POST'])
@admin_required
def delete_beach(beach_id):
    beach = Beach.query.get_or_404(beach_id)
    db.session.delete(beach)
    db.session.commit()
    flash("Beach deleted successfully.", "info")
    return redirect(url_for("admin.beaches"))

@admin_bp.route('/update-beach/<int:beach_id>', methods=['POST'])
@admin_required
def update_beach(beach_id):
    beach = Beach.query.get_or_404(beach_id)

    new_slug = request.form.get('slug')
    existing = Beach.query.filter_by(slug=new_slug).first()
    if existing and existing.id != beach.id:
        flash("Slug is already in use by another beach.", "warning")
        return redirect(url_for("admin.beaches"))

    beach.name = request.form.get('name')
    beach.location = request.form.get('location')
    beach.description = request.form.get('description')
    beach.long_description = request.form.get('long_description')
    beach.slug = new_slug
    beach.price = request.form.get('price', type=float)
    beach.bed_count = request.form.get('bed_count', type=int)
    beach.latitude = request.form.get('latitude', type=float)
    beach.longitude = request.form.get('longitude', type=float)

    beach.has_booking = bool(request.form.get('has_booking'))
    beach.has_food = bool(request.form.get('has_food'))
    beach.has_parking = bool(request.form.get('has_parking'))
    beach.allows_pets = bool(request.form.get('allows_pets'))
    beach.has_wifi = bool(request.form.get('has_wifi'))
    beach.has_water_sports = bool(request.form.get('has_water_sports'))
    beach.is_disabled_friendly = bool(request.form.get('is_disabled_friendly'))

    uploaded_file = request.files.get('image_upload')
    # --- GCS İÇİN DEĞİŞTİRİLDİ ---
    if uploaded_file and uploaded_file.filename.strip():
        if not allowed_file(uploaded_file.filename):
            flash("Only JPG and PNG files are allowed.", "danger")
            return redirect(url_for("admin.beaches"))

        if is_file_too_large(uploaded_file):
            flash("Image file is too large. Max 5MB allowed.", "danger")
            return redirect(url_for("admin.beaches"))

        # GCS'e yükleme mantığı
        filename = secure_filename(uploaded_file.filename)
        unique_filename = str(uuid.uuid4()) + "-" + filename
        
        storage_client = storage.Client()
        bucket_name = current_app.config['GCS_BUCKET_NAME']
        bucket = storage_client.bucket(bucket_name)

        blob = bucket.blob(unique_filename)
        blob.upload_from_file(
            uploaded_file,
            content_type=uploaded_file.content_type
        )
        beach.image_url = blob.public_url # Plajın resim URL'ini doğrudan GCS linki ile güncelle
    # --- GCS İÇİN DEĞİŞTİRİLDİ BİTTİ ---

    try:
        db.session.commit()
        flash('Beach updated successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating beach: {e}', 'danger')

    return redirect(url_for('admin.beaches'))


@admin_bp.route('/users', methods=['GET', 'POST'])
@admin_required
def manage_users():
    from app.models import User, Beach
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        new_role = request.form.get('new_role')
        beach_id = request.form.get('manager_for_beach_id')

        user = User.query.get(user_id)

        if user:
            user.role = new_role

            if beach_id:
                beach = Beach.query.get(int(beach_id))
                if beach:
                    beach.manager_id = user.id

            db.session.commit()
            flash(f"{user.email} kullanıcısının rolü '{new_role}' olarak güncellendi.", "success")

        return redirect(url_for('admin.manage_users'))

    users = User.query.all()
    beaches = Beach.query.all()  # 👈 dropdown için gerekli
    return render_template("admin_users.html", users=users, beaches=beaches)


@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    from app.models import User, Beach, Reservation, Favorite

    total_users = User.query.count()
    total_admins = User.query.filter_by(role='admin').count()
    total_beach_admins = User.query.filter_by(role='beach_admin').count()
    total_beaches = Beach.query.count()
    total_reservations = Reservation.query.count()
    total_favorites = Favorite.query.count() if 'Favorite' in globals() else 0

    return render_template("admin_dashboard.html", **locals())

@admin_bp.route('/dashboard/data')
@admin_required
def dashboard_data():
    from app.models import Reservation, Beach
    from sqlalchemy import func
    from datetime import datetime, timedelta

    # 7 gün önceye kadar olan rezervasyonlar
    today = datetime.today().date()
    last_7_days = [today - timedelta(days=i) for i in range(6, -1, -1)]

    # Günlük rezervasyon sayısı (dict formatı)
    daily_data = (
        db.session.query(
            Reservation.date,
            func.count().label('count')
        )
        .filter(Reservation.date.in_(last_7_days))
        .group_by(Reservation.date)
        .all()
    )
    daily_reservations = {str(date): count for date, count in daily_data}

    # Popüler plajlar (en çok rezervasyon alan)
    beach_data = (
        db.session.query(
            Beach.name,
            func.count(Reservation.id).label('count')
        )
        .join(Reservation, Beach.id == Reservation.beach_id)
        .group_by(Beach.name)
        .order_by(func.count(Reservation.id).desc())
        .limit(5)
        .all()
    )
    popular_beaches = [{"name": name, "reservations": count} for name, count in beach_data]

    return jsonify({
        "daily_reservations": daily_reservations,
        "popular_beaches": popular_beaches
    })

@admin_bp.route('/users/<int:user_id>/update_role_assign_beach', methods=['POST'])
@admin_required
def update_user_role_and_assign_beach(user_id): # HTML'deki url_for ile eşleşen fonksiyon adı
    user = User.query.get_or_404(user_id)
    new_role = request.form.get('new_role')
    # HTML'deki <select name="assign_new_beach_id" ...> alanından değeri alıyoruz
    new_beach_to_assign_id = request.form.get('assign_new_beach_id') 

    role_changed_message = None
    beach_assigned_message = None
    warning_message = None
    action_taken = False # Herhangi bir veritabanı değişikliği yapılıp yapılmadığını izlemek için

    # 1. Kullanıcının rolünü güncelle
    if new_role and user.role != new_role:
        user.role = new_role
        role_changed_message = f"{user.first_name} {user.last_name} kullanıcısının rolü '{new_role}' olarak güncellendi."
        action_taken = True

    # 2. Yeni bir plaj atanacaksa (dropdown'dan bir plaj seçilmişse)
    if new_beach_to_assign_id: # Değer boş değilse (yani "-- Yeni Plaj Ata (Opsiyonel) --" seçilmemişse)
        beach_to_assign = Beach.query.get(int(new_beach_to_assign_id))
        if beach_to_assign:
            if beach_to_assign.manager_id and beach_to_assign.manager_id != user.id:
                other_manager_user = User.query.get(beach_to_assign.manager_id)
                other_manager_name = f"{other_manager_user.first_name} {other_manager_user.last_name}" if other_manager_user else "başka bir kullanıcı"
                warning_message = f"{beach_to_assign.name} plajının zaten bir yöneticisi ({other_manager_name}) var. Atama yapılmadı."
            elif beach_to_assign.manager_id == user.id:
                # Zaten bu kullanıcıya atanmışsa bir şey yapma
                pass 
            else:
                beach_to_assign.manager_id = user.id
                beach_assigned_message = f"{beach_to_assign.name} plajı {user.first_name} {user.last_name} kullanıcısına başarıyla atandı."
                action_taken = True
        else:
            warning_message = "Atanmak istenen plaj bulunamadı."

    # 3. Veritabanı işlemlerini yap ve mesajları flash et
    if action_taken: # Sadece gerçekten bir değişiklik yapıldıysa commit et
        try:
            db.session.commit()
            if role_changed_message:
                flash(role_changed_message, "success")
            if beach_assigned_message:
                flash(beach_assigned_message, "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Veritabanı güncellenirken bir hata oluştu: {str(e)}", "danger")
            # Hata durumunda uyarı mesajını da (varsa) göster
            if warning_message:
                flash(warning_message, "warning")
            return redirect(url_for('admin.manage_users')) # Hata sonrası yönlendirme

    # Uyarı mesajları her zaman gösterilebilir (başarılı işlemden sonra veya tek başına)
    if warning_message:
        flash(warning_message, "warning")
    
    if not action_taken and not warning_message: # Hiçbir değişiklik yapılmadıysa ve uyarı da yoksa
        flash("Kaydedilecek bir değişiklik yapılmadı veya seçilen plaj zaten atanmış.", "info")

    return redirect(url_for('admin.manage_users'))

# admin.py dosyanıza EKLENECEK KOD
@admin_bp.route('/users/<int:user_id>/unassign_beach/<int:beach_id>', methods=['POST'])
@admin_required
def unassign_specific_beach(user_id, beach_id):
    user = User.query.get_or_404(user_id)
    beach = Beach.query.get_or_404(beach_id)

    if beach.manager_id == user.id:
        beach.manager_id = None
        db.session.commit()
        flash(f'{user.first_name} {user.last_name} kullanıcısı {beach.name} plaj yöneticiliğinden başarıyla kaldırıldı.', 'success')
    else:
        flash(f'Hata: {beach.name} plajı zaten {user.first_name} {user.last_name} kullanıcısına atanmamış veya başka bir sorun oluştu.', 'danger')

    return redirect(url_for('admin.manage_users'))

@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    user_to_delete = User.query.get_or_404(user_id)

    if user_to_delete.role == 'admin':
        flash('Admin rolündeki kullanıcılar sistemden silinemez.', 'danger')
        return redirect(url_for('admin.manage_users'))

    try:
        if user_to_delete.role == 'beach_admin':
            Beach.query.filter_by(manager_id=user_to_delete.id).update({Beach.manager_id: None})

        db.session.delete(user_to_delete)
        db.session.commit()
        flash(f'{user_to_delete.first_name} {user_to_delete.last_name} ({user_to_delete.email}) adlı kullanıcı başarıyla silindi.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Kullanıcı silinirken bir hata oluştu: {str(e)}', 'danger')

    return redirect(url_for('admin.manage_users'))