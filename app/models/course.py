from app.extensions import db


class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    description = db.Column(db.Text)
    duration_weeks = db.Column(db.Integer, nullable=False)
    duration_unit = db.Column(db.String(10), nullable=False, default='weeks')
    fees = db.Column(db.Float, nullable=False)
    capacity = db.Column(db.Integer, nullable=True)
    gst_applicable = db.Column(db.Boolean, default=False)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id', ondelete='SET NULL'), nullable=True)
    syllabus = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default='Active')
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)

    enquiries = db.relationship('Enquiry', backref='course', lazy=True, passive_deletes=True)

    def __repr__(self):
        return f"<Course {self.code}: {self.name}>"


def active_enrollment_count(course_id):
    from sqlalchemy import or_, func
    from app.models.student import student_courses
    return db.session.query(func.count(student_courses.c.student_id)).filter(
        student_courses.c.course_id == course_id,
        or_(student_courses.c.status == 'Enrolled', student_courses.c.status.is_(None))
    ).scalar() or 0


def course_has_capacity(course, extra=1):
    return course.capacity is None or active_enrollment_count(course.id) + extra <= course.capacity
