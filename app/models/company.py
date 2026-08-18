from app.extensions import db


class Company(db.Model):
    __tablename__ = 'company'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    is_gst_registered = db.Column(db.Boolean, default=True, nullable=False)
    gstin = db.Column(db.String(20), nullable=True)
    address = db.Column(db.Text, nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(100), nullable=True)
    invoice_prefix = db.Column(db.String(20), default='INV/', nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    accounts = db.relationship('Account', backref='company', lazy=True)
    courses = db.relationship('Course', backref='company', lazy=True)
    fee_records = db.relationship('FeeRecord', backref='company', lazy=True)

    def __repr__(self):
        return f"<Company {self.code}: {self.name}>"
