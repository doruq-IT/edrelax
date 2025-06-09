# Bu dosya: app/routes/auth.py

# === Gerekli importlar ===
# gevent'i en başa ekliyoruz. Monkey-patching'i zaten ana çalıştırma dosyanızda yaptınız.
import gevent
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, logout_user, login_required, current_user
from itsdangerous import URLSafeTimedSerializer
from app.extensions import login_manager, db, limiter, mail
from app.forms.auth_forms import LoginForm, SignUpForm, ForgotPasswordForm, ResetPasswordForm
from app.models import User
from flask_mail import Message
from flask_dance.contrib.google import google
import os

# Blueprint tanımı (değişiklik yok)
auth_bp = Blueprint('auth', __name__)


# === YARDIMCI FONKSİYON ===
# CPU-yoğun şifre kontrolünü arka plana atmak için bir yardımcı fonksiyon.
# Bu, 'login' ve 'profile' rotaları tarafından kullanılacak.
def check_password_in_background(hashed_password, password_to_check):
    """
    Bu fonksiyon, gevent'in threadpool'unda çalışarak ana döngüyü
    kilitlemeden şifre kontrolü yapar.
    """
    # check_password_hash fonksiyonu zaten bu dosyada import edildiği için
    # tekrar import etmeye gerek yok.
    return check_password_hash(hashed_password, password_to_check)


# === GÜNCELLENMİŞ LOGIN ROTASI ===
@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def login():
    form = LoginForm()
    print("🟢 Login route tetiklendi")
    if form.validate_on_submit():
        print("✅ Form valid")
        email = form.email.data
        password = form.password.data
        user = User.query.filter_by(email=email).first()

        # 1. Önce kullanıcı var mı diye kontrol et
        if user:
            # 2. Şifre kontrolünü ana döngüyü kilitlemeden arka planda çalıştır
            is_password_correct = gevent.get_hub().threadpool.spawn(
                check_password_in_background, user.password, password
            ).get() # .get() sonucu bekler ama bu sırada diğer gevent işleri devam eder.

            # 3. Şifre doğruysa işlemlere devam et
            if is_password_correct:
                if not user.confirmed:
                    flash("Lütfen e-posta adresinizi doğrulayın.", "warning")
                    return redirect(url_for("auth.login"))
                
                login_user(user, remember=form.remember.data)
                print(f"🚀 login_user çağrıldı: {user.email}")
                session.permanent = True
                session["user_id"] = user.id
                session["user_name"] = user.first_name
                session["user_email"] = user.email
                session["user_role"] = user.role

                flash("Giriş başarılı.", "success")

                if user.role == "beach_admin":
                    return redirect(url_for("beach_admin.select_beach"))

                return redirect(url_for("public.index"))

        # Kullanıcı bulunamazsa veya şifre yanlışsa (her iki durumda da aynı mesaj)
        flash("Hatalı e-posta veya şifre.", "danger")

    return render_template("login.html", form=form)


# === GÜNCELLENMİŞ PROFİL ROTASI ===
@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user

    if request.method == "POST":
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")

        # Şifre güncelleme istenmişse
        if new_password:
            if not current_password:
                flash("To change your password, please enter your current password.", "warning")
                return redirect(url_for("auth.profile"))

            # Yine şifre kontrolünü ana döngüyü kilitlemeden arka planda yapıyoruz
            is_current_password_correct = gevent.get_hub().threadpool.spawn(
                check_password_in_background, user.password, current_password
            ).get()

            if not is_current_password_correct:
                flash("Current password is incorrect.", "danger")
                return redirect(url_for("auth.profile"))
            
            # Şifre doğru, yenisini güvenli bir şekilde hash'le
            user.password = generate_password_hash(new_password)

        # İsim güncelle
        user.first_name = first_name
        user.last_name = last_name

        db.session.commit()
        flash("Profile updated successfully.", "success")
        return redirect(url_for("auth.profile"))

    return render_template("profile.html", user=user)


# ==========================================================
# DİĞER FONKSİYONLARINIZ (HİÇBİR DEĞİŞİKLİK YAPILMADI)
# ==========================================================

@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    form = SignUpForm()
    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data).first():
            flash("This email is already registered.", "warning")
            return redirect(url_for("auth.signup"))
        hashed_pw = generate_password_hash(form.password.data)
        new_user = User(
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            email=form.email.data,
            password=hashed_pw,
            role="user"
        )
        db.session.add(new_user)
        db.session.commit()
        s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
        token = s.dumps(new_user.email, salt="email-confirm")
        confirm_url = url_for("auth.confirm_email", token=token, _external=True)
        msg = Message("Hesabınızı Doğrulayın", recipients=[new_user.email])
        msg.body = f"Merhaba {new_user.first_name},\n\nHesabınızı aktifleştirmek için bu linke tıklayın:\n{confirm_url}\n\nTeşekkürler!"
        mail.send(msg)
        flash("Kayıt başarılı! Lütfen e-postanızı kontrol edin ve hesabınızı aktifleştirin.", "info")
        return redirect(url_for("auth.login"))
    return render_template("signup.html", form=form)

@auth_bp.route("/confirm/<token>")
def confirm_email(token):
    from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    try:
        email = s.loads(token, salt="email-confirm", max_age=3600)
    except (SignatureExpired, BadSignature):
        flash("Doğrulama linki geçersiz veya süresi dolmuş.", "danger")
        return redirect(url_for("auth.login"))
    user = User.query.filter_by(email=email).first()
    if user is None:
        flash("Kullanıcı bulunamadı.", "danger")
    elif user.confirmed:
        flash("Bu hesap zaten doğrulanmış.", "info")
    else:
        user.confirmed = True
        db.session.commit()
        flash("Hesabınız doğrulandı! Giriş yapabilirsiniz.", "success")
    return redirect(url_for("auth.login"))

@auth_bp.route('/google-login')
def google_login():
    if not google.authorized:
        return redirect(url_for("google.login"))
    resp = google.get("/oauth2/v2/userinfo")
    if not resp.ok:
        flash("Google login failed.", "danger")
        return redirect(url_for("public.index"))
    user_info = resp.json()
    email = user_info["email"]
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(
            first_name=user_info.get("given_name", ""),
            last_name=user_info.get("family_name", ""),
            email=email,
            role="user"
        )
        db.session.add(user)
        db.session.commit()
    login_user(user)
    flash("Welcome!", "success")
    return redirect(url_for("public.index"))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    flash("Çıkış yapıldı.", "info")
    return redirect(url_for("public.index"))


@auth_bp.route('/forgot-password', methods=["GET", "POST"])
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
            token = s.dumps(user.email, salt="password-reset-salt")
            reset_url = url_for("auth.reset_password", token=token, _external=True)
            msg = Message("Şifre Sıfırlama Talebi", recipients=[user.email])
            msg.body = f"Merhaba {user.first_name},\n\nŞifrenizi sıfırlamak için aşağıdaki linke tıklayın (Link 1 saat geçerlidir):\n{reset_url}\n\nEğer bu talebi siz yapmadıysanız, bu e-postayı görmezden gelin.\n\nTeşekkürler!"
            mail.send(msg)
        flash("Bu e-posta adresi sistemimizde kayıtlıysa, şifre sıfırlama bağlantısı gönderilmiştir.", "info")
        return redirect(url_for("auth.login"))
    return render_template("forgot_password.html", form=form)


@auth_bp.route('/reset-password/<token>', methods=["GET", "POST"])
def reset_password(token):
    from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    try:
        email = s.loads(token, salt="password-reset-salt", max_age=3600)
    except (SignatureExpired, BadSignature):
        flash("Şifre sıfırlama bağlantısı geçersiz veya süresi dolmuş.", "danger")
        return redirect(url_for("auth.login"))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=email).first()
        if user:
            hashed_pw = generate_password_hash(form.password.data)
            user.password = hashed_pw
            db.session.commit()
            flash("Şifreniz başarıyla güncellendi. Yeni şifrenizle giriş yapabilirsiniz.", "success")
            return redirect(url_for("auth.login"))
    return render_template("reset_password.html", form=form, token=token)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@auth_bp.route('/send-test-mail')
def send_test_mail():
    msg = Message("Test Mail", recipients=["okan.rescue@gmail.com"])
    msg.body = "Flask-Mail çalışıyor! Bu bir test mesajıdır."
    mail.send(msg)
    return "Mail gönderildi"


@auth_bp.route('/delete_account', methods=['POST'])
@login_required
def delete_account():
    user = current_user
    logout_user()
    db.session.delete(user)
    db.session.commit()
    flash("Profiliniz kalıcı olarak silinmiştir.", "success")
    return redirect(url_for("public.index"))
