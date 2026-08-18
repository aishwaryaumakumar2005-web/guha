from app.extensions import db


class SystemSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.Text)

    def __repr__(self):
        return f"<SystemSetting {self.key}>"
