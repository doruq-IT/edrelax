import os
# import pymysql
from flask import Flask, render_template, redirect, url_for, flash, request, current_app, session
from app.extensions import db, login_manager, limiter
from app.routes import auth_bp, admin_bp, public_bp, reservations_bp
from .routes.auth import load_user  # Kullanıcı yükleme fonksiyonu
from datetime import datetime
from app.routes.beach_admin import beach_admin_bp
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


# GCP Secret Manager kullanımı devre dışı bırakıldı
# def get_secret_from_gcp(secret_name):
#     client = secretmanager.SecretManagerServiceClient()
#     project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
#     name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
#     response = client.access_secret_version(name=name)
#     return response.payload.data.decode("UTF-8")

def create_app():
    # pymysql.install_as_MySQLdb()
    from werkzeug.middleware.proxy_fix import ProxyFix
    app = Flask(
        __name__,
        template_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), '../templates')),
        static_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), '../static'))
    )
    app.config.from_object(Config)
    app.config["WTF_CSRF_SECRET_KEY"] = app.config["SECRET_KEY"]

    # GCP üzerinden gizli bilgileri alma işlemleri devre dışı bırakıldı
    # app.config["GOOGLE_CLIENT_ID"] = get_secret_from_gcp("google_client_id")
    # app.config["GOOGLE_CLIENT_SECRET"] = get_secret_from_gcp("google_client_secret")
    # app.config["DB_USER"] = get_secret_from_gcp("db_user")
    # app.config["DB_PASSWORD"] = get_secret_from_gcp("db_password")
    # admin_email = get_secret_from_gcp("admin_notification_email")
    # app.config["ADMIN_EMAIL"] = admin_email
    # app.config["ADMIN_EMAILS"] = [admin_email]
    # mail_user = get_secret_from_gcp("mail_username")
    # app.config["MAIL_USERNAME"] = mail_user
    # app.config["MAIL_PASSWORD"] = get_secret_from_gcp("mail_password")
    # app.config["MAIL_DEFAULT_SENDER"] = mail_user

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

    csrf.init_app(app)
    mail.init_app(app)
    oauth.init_app(app)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.user_loader(load_user)
    limiter.init_app(app)
    socketio.init_app(app, async_mode='gevent')

    # GCP ayarları kapalı olduğu için bu register da devre dışı
    # oauth.register(
    #     name='google',
    #     client_id=app.config.get("GOOGLE_CLIENT_ID"),
    #     client_secret=app.config.get("GOOGLE_CLIENT_SECRET"),
    #     server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    #     client_kwargs={
    #         'scope': 'openid email profile'
    #     }
    # )

    app.jinja_env.filters['to_alphanumeric_bed_id'] = to_alphanumeric_bed_id
    app.register_blueprint(google_bp, url_prefix="/login")
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
