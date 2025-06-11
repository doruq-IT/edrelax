from gevent import monkey
monkey.patch_all()
# ---------------------

from app import create_app
from app.extensions import socketio
from app import socket_events  # unutma

app = create_app()

if __name__ == '__main__':
    # Bu blok, doğrudan 'python run.py' komutuyla çalıştırıldığında kullanılır.
    # Gunicorn ile çalışırken bu kısım Gunicorn tarafından yönetilir.
    socketio.run(app, host='0.0.0.0', port=8000)