# app/models.py
from app.extensions import db
from datetime import datetime
from flask_login import UserMixin

# --- YENİ MODEL: RENTABLEITEM ---
# Bu model, veritabanında oluşturduğumuz 'rentable_items' tablosuna karşılık gelir.
class RentableItem(db.Model):
    __tablename__ = 'rentable_items'

    id = db.Column(db.Integer, primary_key=True)
    beach_id = db.Column(db.Integer, db.ForeignKey('beaches.id'), nullable=False)
    item_type = db.Column(db.String(50), nullable=False)  # Örn: 'standart_sezlong', 'loca', 'vip'
    item_number = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False) # Para birimi için Float yerine Numeric daha güvenlidir.
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    # Beach modeli ile olan ilişki
    beach = db.relationship('Beach', back_populates='rentable_items')

    def __repr__(self):
        return f"<RentableItem id={self.id} type='{self.item_type}' number={self.item_number}>"
# --- YENİ MODEL BİTTİ ---


class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    role = db.Column(db.String(20), default='user')
    confirmed = db.Column(db.Boolean, default=False)

    reservations = db.relationship('Reservation', back_populates='user', cascade='all, delete')


# --- GÜNCELLENEN MODEL: BEACH ---
class Beach(db.Model):
    __tablename__ = 'beaches'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    long_description = db.Column(db.Text)
    image_url = db.Column(db.String(200))
    slug = db.Column(db.String(100), unique=True)
    
    # --- ESKİYEN SÜTUNLAR ---
    # Bu sütunlar artık doğrudan kullanılmayacak. Bilgiler RentableItem modelinden gelecek.
    # price = db.Column(db.Float, nullable=True)
    # bed_count = db.Column(db.Integer, default=0)
    # NOT: Bu sütunları veritabanından daha sonra sileceğiz, şimdilik koddan kaldırmak yeterli.

    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)

    has_booking = db.Column(db.Boolean, default=False)
    has_food = db.Column(db.Boolean, default=False)
    has_parking = db.Column(db.Boolean, default=False)
    allows_pets = db.Column(db.Boolean, default=False)
    has_wifi = db.Column(db.Boolean, default=False)
    has_water_sports = db.Column(db.Boolean, default=False)
    is_disabled_friendly = db.Column(db.Boolean, default=False)
    manager_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    manager = db.relationship('User', backref='managed_beaches')

    # --- GÜNCELLENEN İLİŞKİLER ---
    # Bir plajın birden çok rezervasyonu ve kiralanabilir eşyası olabilir.
    reservations = db.relationship('Reservation', back_populates='beach', cascade='all, delete-orphan')
    rentable_items = db.relationship('RentableItem', back_populates='beach', cascade='all, delete-orphan')

    def to_dict(self):
        # to_dict fonksiyonunu da yeni yapıya uygun hale getirelim.
        return {
            'id': self.id,
            'name': self.name,
            'location': self.location,
            'description': self.description,
            'long_description': self.long_description,
            'image_url': self.image_url,
            'slug': self.slug,
            'latitude': self.latitude,
            'longitude': self.longitude,
            # Artık bu bilgiler doğrudan plaja ait değil.
            # 'price': self.price,
            # 'bed_count': self.bed_count,
            'rentable_items_count': len(self.rentable_items), # Yeni dinamik bilgi
            'has_booking': self.has_booking,
            'has_food': self.has_food,
            'has_parking': self.has_parking,
            'allows_pets': self.allows_pets,
            'has_wifi': self.has_wifi,
            'has_water_sports': self.has_water_sports,
            'is_disabled_friendly': self.is_disabled_friendly
        }

# --- GÜNCELLENEN MODEL: RESERVATION ---
class Reservation(db.Model):
    __tablename__ = 'reservations'
    id = db.Column(db.Integer, primary_key=True)
    beach_id = db.Column(db.Integer, db.ForeignKey('beaches.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # --- YENİ SÜTUN VE ESKİYEN SÜTUN ---
    item_id = db.Column(db.Integer, db.ForeignKey('rentable_items.id'), nullable=False)
    # bed_number = db.Column(db.Integer, nullable=False) # ESKİDİ: Artık item_id kullanıyoruz.
    
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    confirmation_sent = db.Column(db.Boolean, default=False)
    
    status = db.Column(db.String(50), default='reserved', nullable=False)

    # --- GÜNCELLENEN İLİŞKİLER ---
    beach = db.relationship('Beach', back_populates='reservations')
    user = db.relationship('User', back_populates='reservations')
    item = db.relationship('RentableItem', backref='reservations') # Her rezervasyon tek bir 'item'a aittir.

    # --- GÜNCELLENEN VERİTABANI KISITLAMASI ---
    # Benzersizlik kısıtlaması artık 'bed_number' yerine 'item_id' üzerinden olmalı.
    __table_args__ = (
        db.UniqueConstraint('item_id', 'date', 'start_time', name='_item_date_start_uc'),
    )


class Favorite(db.Model):
    __tablename__ = 'favorites'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    beach_id = db.Column(db.Integer, db.ForeignKey('beaches.id'), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    user = db.relationship('User', backref='favorites')
    beach = db.relationship('Beach', backref='favorited_by')
    

class BeachComment(db.Model):
    __tablename__ = "beach_comments"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    beach_id = db.Column(db.Integer, db.ForeignKey("beaches.id"), nullable=False)
    comment_text = db.Column(db.Text, nullable=False)
    sentiment_score = db.Column(db.Integer)  # 1–5 arası değer beklenir
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
# --- GÜNCELLENEN MODEL: WAITINGLIST ---
class WaitingList(db.Model):
    __tablename__ = 'waiting_list'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    beach_id = db.Column(db.Integer, db.ForeignKey('beaches.id'), nullable=False)
    
    # --- YENİ SÜTUN VE ESKİYEN SÜTUN ---
    item_id = db.Column(db.Integer, db.ForeignKey('rentable_items.id'), nullable=False)
    # bed_number = db.Column(db.Integer, nullable=False) # ESKİDİ: Artık item_id kullanıyoruz.

    date = db.Column(db.Date, nullable=False)
    time_slot = db.Column(db.String(20), nullable=False)
    notified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='waiting_entries')
    beach = db.relationship('Beach', backref='waiting_entries')