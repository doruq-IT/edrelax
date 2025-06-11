import os
import pymysql
from flask import Flask, render_template, redirect, url_for, flash, request, current_app, session
from app.extensions import db, login_manager, limiter
from app.routes import auth_bp, admin_bp, public_bp, reservations_bp
from .routes.auth import load_user  # Kullanıcı yükleme fonksiyonu
from datetime import datetime
from app.routes.beach_admin import beach_admin_bp
from google.cloud import secretmanager
from .extensions import oauth
from flask_wtf.csrf import generate_csrf
from app.util import to_alphanumeric_bed_id
from app import socket_events
from config import Config
from app.extensions import csrf, mail, limiter, google_bp
from app.extensions import socketio
from dotenv import load_dotenv
from .extensions import csrf
import hashlib


load_dotenv()
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
# pymysql'i MySQLdb gibi davranması için kur
pymysql.install_as_MySQLdb()

def get_secret_from_gcp(secret_name):
    client = secretmanager.SecretManagerServiceClient()
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(name=name)
    return response.payload.data.decode("UTF-8")

def create_app():
    from werkzeug.middleware.proxy_fix import ProxyFix
    app = Flask(
        __name__,
        template_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), '../templates')),
        static_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), '../static'))
    )
    app.config.from_object(Config)
    app.config["SECRET_KEY"] = get_secret_from_gcp("flask_secret_key")
    app.config["WTF_CSRF_SECRET_KEY"] = app.config["SECRET_KEY"]
    
    app.config["GOOGLE_CLIENT_ID"] = get_secret_from_gcp("google_client_id")
    app.config["GOOGLE_CLIENT_SECRET"] = get_secret_from_gcp("google_client_secret")
    
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # --- CACHE BUSTER KODU BURAYA EKLENDİ ---
    @app.context_processor
    def inject_cache_buster():
        def cache_buster(filepath_relative_to_static):
            """
            Dosyanın, static klasörüne göre olan yolunu alır (örn: 'css/style.css')
            ve tam sistem yolunu bularak hash üretir.
            """
            # Flask'in bildiği static klasörünün tam yolu ile dosya yolunu birleştir
            full_path = os.path.join(app.static_folder, filepath_relative_to_static)
            
            if not os.path.exists(full_path):
                return "" # Dosya bulunamazsa boş dön
            
            # Dosyanın içeriğinin hash'ini hesapla
            hasher = hashlib.md5()
            with open(full_path, 'rb') as f:
                buf = f.read()
                hasher.update(buf)
            
            return hasher.hexdigest()[:10]
            
        return dict(cache_buster=cache_buster)
    # --- EKLEME BÖLÜMÜ SONU ---
    
    csrf.init_app(app)
    mail.init_app(app)
    oauth.init_app(app)

    # 🔌 Uzantıları başlat
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.user_loader(load_user)
    limiter.init_app(app)
    socketio.init_app(app)

    # Google'ı bir OAuth sağlayıcısı olarak kaydet
    oauth.register(
        name='google',
        client_id=app.config.get("GOOGLE_CLIENT_ID"),
        client_secret=app.config.get("GOOGLE_CLIENT_SECRET"),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'openid email profile'
        }
    )



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

    # ✅ Config değerini şablonlara aktarmak için context processor
    @app.context_processor
    def inject_admin_emails():
        return dict(admin_emails=current_app.config.get('ADMIN_EMAILS', []))
    
    @app.context_processor
    def inject_csrf():
        return dict(csrf_token=generate_csrf())
    
    
    @app.after_request
    def inject_csrf_token(response):
        response.set_cookie('csrf_token', generate_csrf())
        return response
    
    @app.route("/debug/google-creds")
    def debug_google_creds():
        return f"""
        <pre>
        GOOGLE_CLIENT_ID: {app.config.get("GOOGLE_CLIENT_ID")}
        GOOGLE_CLIENT_SECRET: {app.config.get("GOOGLE_CLIENT_SECRET")}
        </pre>
        """

    return app
    

    




