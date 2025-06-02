import os
import pymysql
from flask import Flask, render_template, redirect, url_for, flash, request, current_app, session
from app.extensions import db, login_manager, limiter
from app.routes import auth_bp, admin_bp, public_bp, reservations_bp
from .routes.auth import load_user  # Kullanıcı yükleme fonksiyonu
from datetime import datetime
from app.routes.beach_admin import beach_admin_bp
from app.util import to_alphanumeric_bed_id
from config import Config
from app.extensions import limiter
from app.extensions import csrf
from app.extensions import mail
from app.extensions import google_bp
from dotenv import load_dotenv

load_dotenv()
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
# pymysql'i MySQLdb gibi davranması için kur
pymysql.install_as_MySQLdb()


def create_app():
    app = Flask(
        __name__,
        template_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), '../templates')),
        static_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), '../static'))
    )

    app.config.from_object(Config)
    csrf.init_app(app)
    mail.init_app(app)

    # 🔌 Uzantıları başlat
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.user_loader(load_user)
    limiter.init_app(app)

    # ✨ Jinja filtresini kaydet
    app.jinja_env.filters['to_alphanumeric_bed_id'] = to_alphanumeric_bed_id
    app.register_blueprint(google_bp, url_prefix="/login")

    # 🔗 Blueprint'leri ekle
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(beach_admin_bp)

    # 🔒 Oturum süresi otomatik yenilensin (30 dakika inaktiviteden sonra logout)
    @app.before_request
    def make_session_permanent():
        session.permanent = True
        session.modified = True

    # ✅ Config değerini şablonlara aktarmak için context processor
    @app.context_processor
    def inject_admin_emails():
        return dict(admin_emails=current_app.config.get('ADMIN_EMAILS', []))

    return app



