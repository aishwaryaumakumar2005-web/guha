from app.extensions import db


class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    description = db.Column(db.Text)
    duration_weeks = db.Column(db.Integer, nullable=False)
    duration_unit = db.Column(db.String(10), nullable=False, default='weeks')
    fees = db.Column(db.Float, nullable=False)
    gst_applicable = db.Column(db.Boolean, default=False)
    syllabus = db.Column(db.Text)

    enquiries = db.relationship('Enquiry', backref='course', lazy=True)

    def __repr__(self):
        return f"<Course {self.code}: {self.name}>"
