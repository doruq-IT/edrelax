# app/extensions.py

# Üçüncü parti eklentiler
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf import CSRFProtect
from flask_socketio import SocketIO
import os
from flask import abort
from functools import wraps
from flask_mail import Mail
from authlib.integrations.flask_client import OAuth


# Eklenti nesneleri
db = SQLAlchemy()
login_manager = LoginManager()
limiter = Limiter(key_func=get_remote_address)
csrf = CSRFProtect()
mail = Mail()

socketio = SocketIO(
    cors_allowed_origins="*",
    async_mode="gevent"
)
oauth = OAuth()

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            abort(403)
        return f(*args, **kwargs)
    return decorated_function