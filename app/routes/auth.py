from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, logout_user, login_required, current_user
from itsdangerous import URLSafeTimedSerializer
from app.extensions import login_manager
from app.forms.auth_forms import LoginForm
from app.extensions import db
from app.models import User
from app.extensions import limiter
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from app.forms.auth_forms import SignUpForm
from flask_mail import Message
from app.extensions import mail
from flask_dance.contrib.google import google


auth_bp = Blueprint('auth', __name__)


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

        # ✅ TOKEN OLUŞTUR
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
        email = s.loads(token, salt="email-confirm", max_age=3600)  # 1 saat geçerli
    except SignatureExpired:
        flash("Doğrulama linkinin süresi dolmuş.", "danger")
        return redirect(url_for("auth.login"))
    except BadSignature:
        flash("Geçersiz doğrulama bağlantısı.", "danger")
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
        return redirect(url_for("google.login"))  # bu flask-dance’in otomatik endpoint’i

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

        if user and check_password_hash(user.password, password):
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
        else:
            flash("Hatalı e-posta veya şifre.", "danger")

    return render_template("login.html", form=form)



@auth_bp.route("/logout")
@login_required
def logout():
    # 🔐 Flask-Login çıkışı
    logout_user()

    # 🧹 Session temizliği
    session.clear()

    flash("Çıkış yapıldı.", "info")
    return redirect(url_for("public.index"))



@auth_bp.route('/forgot-password', methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email")
        flash("If this email is registered, a reset link has been sent.", "info")
        return redirect(url_for("auth.login"))
    return render_template("forgot_password.html")

@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user

    if request.method == "POST":
        # 📌 Form verileri
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")

        # 🛡️ Şifre güncelleme istenmişse
        if new_password:
            if not current_password:
                flash("To change your password, please enter your current password.", "warning")
                return redirect(url_for("auth.profile"))

            if not check_password_hash(user.password, current_password):
                flash("Current password is incorrect.", "danger")
                return redirect(url_for("auth.profile"))

            # 🔐 Şifre doğru, yenisini kaydet
            user.password = generate_password_hash(new_password)

        # ✏️ İsim güncelle
        user.first_name = first_name
        user.last_name = last_name

        db.session.commit()
        flash("Profile updated successfully.", "success")
        return redirect(url_for("auth.profile"))

    return render_template("profile.html", user=user)


# Flask-Login için kullanıcıyı session'dan yükleyen fonksiyon
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@auth_bp.route('/send-test-mail')
def send_test_mail():
    msg = Message("Test Mail", recipients=["okan.rescue@gmail.com"])
    msg.body = "Flask-Mail çalışıyor! Bu bir test mesajıdır."
    mail.send(msg)
    return "Mail gönderildi"