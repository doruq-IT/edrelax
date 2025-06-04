from flask_socketio import emit
from app.extensions import socketio


@socketio.on('bed_reserved')
def handle_bed_reserved(data):
    print("Canlı rezervasyon alındı:", data)
    # Broadcast: diğer herkese (gönderen hariç)
    emit('bed_reserved', data, broadcast=True, include_self=False)
