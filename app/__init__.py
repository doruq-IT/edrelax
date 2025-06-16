import os
from flask import Flask, render_template, redirect, url_for, flash, request, current_app, session
from app.extensions import db, login_manager, limiter, csrf, mail, oauth, socketio
from app.routes import auth_bp, admin_bp, public_bp, reservations_bp, beach_admin_bp
from pytz import timezone, utc
from .routes.auth import load_user
from datetime import datetime
from app.util import to_alphanumeric_bed_id
from app import socket_events
from config import Config
from dotenv import load_dotenv
import hashlib

load_dotenv()
# Geliştirme ortamında HTTP üzerinden OAuth testi için gereklidir. Canlıda kaldırılabilir.
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' 


def create_app():
    from werkzeug.middleware.proxy_fix import ProxyFix
    app = Flask(
        __name__,
        template_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), '../templates')),
        static_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), '../static'))
    )
    app.config.from_object(Config)
    app.config["WTF_CSRF_SECRET_KEY"] = app.config["SECRET_KEY"]

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    @app.context_processor
    def inject_cache_buster():
        def cache_buster(filepath_relative_to_static):
            full_path = os.path.join(app.static_folder, filepath_relative_to_static)
            if not os.path.exists(full_path):
                return ""
            hasher = hashlib.md5()
            with open(full_path, 'rb') as f:
                buf = f.read()
                hasher.update(buf)
            return hasher.hexdigest()[:10]
        return dict(cache_buster=cache_buster)

    # Eklentileri başlat
    csrf.init_app(app)
    mail.init_app(app)
    db.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)
    socketio.init_app(app, async_mode='gevent')
    
    # OAuth'u başlat ve Google istemcisini kaydet
    oauth.init_app(app)
    oauth.register(
        name='google',
        client_id=app.config.get('GOOGLE_CLIENT_ID'),
        client_secret=app.config.get('GOOGLE_CLIENT_SECRET'),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'openid email profile'
        }
    )

    # Diğer ayarlar
    login_manager.login_view = 'auth.login'
    login_manager.user_loader(load_user)

    # Jinja filtresi
    app.jinja_env.filters['to_alphanumeric_bed_id'] = to_alphanumeric_bed_id

    # Blueprint'leri kaydet
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(beach_admin_bp)

    @app.before_request
    def make_session_permanent():
        session.permanent = True

    @app.context_processor
    def inject_admin_emails():
        return dict(admin_emails=current_app.config.get('ADMIN_EMAILS', []))

    # Not: CSRF token'ı enjekte eden context_processor ve after_request
    # hook'ları Flask-WTF tarafından zaten yönetildiği için genellikle
    # manuel olarak eklenmesine gerek yoktur, ancak özel bir kullanımınız
    # varsa kalabilirler. Şimdilik koruyoruz.
    @app.context_processor
    def inject_csrf():
        from flask_wtf.csrf import generate_csrf
        return dict(csrf_token=generate_csrf())

    @app.after_request
    def inject_csrf_token(response):
        from flask_wtf.csrf import generate_csrf
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
        
    def utc_to_local_time_str(utc_hour_str):
        if not utc_hour_str:
            return "?"
        try:
            dt_utc = datetime.strptime(utc_hour_str, "%H:%M")
            utc_dt = utc.localize(datetime.combine(datetime.today(), dt_utc.time()))
            local_dt = utc_dt.astimezone(timezone("Europe/Istanbul"))
            return local_dt.strftime("%H:%M")
        except Exception as e:
            return utc_hour_str

    app.jinja_env.filters['to_local_time'] = utc_to_local_time_str

    return app