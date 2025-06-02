# app/routes/admin.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, jsonify
from app.extensions import db
from app.models import Beach, User
from functools import wraps
import os
import time
from werkzeug.utils import secure_filename
from flask_login import login_required, current_user

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
        image_url = request.form.get('image_url')

        if uploaded_file and uploaded_file.filename.strip():
            if not allowed_file(uploaded_file.filename):
                flash("Only JPG and PNG files are allowed.", "danger")
                return redirect(url_for("admin.beaches"))

            if is_file_too_large(uploaded_file):
                flash("Image file is too large. Max 5MB allowed.", "danger")
                return redirect(url_for("admin.beaches"))

            filename = secure_filename(uploaded_file.filename)
            ext = os.path.splitext(filename)[1]
            unique_name = f"{slug}-{int(time.time())}{ext}"
            save_path = os.path.join(image_folder, unique_name)
            uploaded_file.save(save_path)

            image_url = f'/static/images/{unique_name}'

        if not image_url or image_url.strip() == '':
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

    return render_template("admin_beaches.html", image_files=image_files)


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
    image_url_from_form = request.form.get('image_url')

    if uploaded_file and uploaded_file.filename.strip():
        if not allowed_file(uploaded_file.filename):
            flash("Only JPG and PNG files are allowed.", "danger")
            return redirect(url_for("admin.beaches"))

        if is_file_too_large(uploaded_file):
            flash("Image file is too large. Max 5MB allowed.", "danger")
            return redirect(url_for("admin.beaches"))

        image_folder = os.path.join(current_app.static_folder, 'images')
        os.makedirs(image_folder, exist_ok=True)

        filename = secure_filename(uploaded_file.filename)
        ext = os.path.splitext(filename)[1]
        unique_name = f"{beach.slug}-{int(time.time())}{ext}"
        save_path = os.path.join(image_folder, unique_name)
        uploaded_file.save(save_path)

        beach.image_url = f'/static/images/{unique_name}'
    else:
        # Eğer yeni dosya yoksa, formdaki mevcut URL'yi kullan
        beach.image_url = image_url_from_form

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

@admin_bp.route('/users/<int:user_id>/update', methods=['POST'])
@admin_required
def update_user_role(user_id):
    user = User.query.get_or_404(user_id)
    new_role = request.form.get('new_role')
    beach_id = request.form.get('manager_for_beach_id')

    # Kullanıcının rolünü güncelle
    if new_role:
        user.role = new_role

    # Eğer beach_id girilmişse ve boş değilse
    if beach_id:
        beach = Beach.query.get(int(beach_id))
        if beach:
            beach.manager_id = user.id

    db.session.commit()
    flash("Kullanıcı ve plaj ataması başarıyla güncellendi.", "success")
    return redirect(url_for('admin.manage_users'))