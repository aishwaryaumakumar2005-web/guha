import uuid
from datetime import datetime
from sqlalchemy import event
from app.extensions import db
from app.helpers import next_code


student_courses = db.Table('student_courses',
    db.Column('student_id', db.Integer, db.ForeignKey('student.id', ondelete='CASCADE'), primary_key=True),
    db.Column('course_id', db.Integer, db.ForeignKey('course.id', ondelete='CASCADE'), primary_key=True),
    db.Column('status', db.String(20), default='Enrolled'),
    db.Column('enrolled_on', db.Date),
    db.Column('completed_on', db.Date),
    db.Column('drop_reason', db.String(200)),
    # W2 agreed-dues snapshot: price/GST/entity as agreed at enrollment.
    # Catalog edits affect NEW enrollments only; NULL rows fall back to the
    # live course row (and are backfilled once by migration).
    db.Column('agreed_fee', db.Float),
    db.Column('agreed_gst', db.Boolean),
    db.Column('agreed_company_id', db.Integer),
)


def ensure_enrolled_on(student_id, course_ids=None, when=None):
    """Stamp enrolled_on on association rows that are missing it.

    Safe to rerun: only touches rows where enrolled_on IS NULL, so
    existing enrollment history (Completed/Dropped dates) is preserved.
    """
    from datetime import date as _date
    when = when or _date.today()
    cond = [student_courses.c.student_id == student_id,
            student_courses.c.enrolled_on.is_(None)]
    if course_ids:
        cond.append(student_courses.c.course_id.in_(list(course_ids)))
    db.session.execute(
        student_courses.update().where(*cond).values(enrolled_on=when)
    )


def stamp_agreed_dues(student_id, course_ids=None):
    """Snapshot catalog price/GST/company onto enrollment rows missing it.

    Call after appending courses + flush at every enrollment site. Rerun-safe
    (mirrors ensure_enrolled_on): only touches rows where agreed_fee IS NULL,
    so later catalog edits never rewrite an agreed price.
    """
    cond = [student_courses.c.student_id == student_id,
            student_courses.c.agreed_fee.is_(None)]
    if course_ids:
        cond.append(student_courses.c.course_id.in_(list(course_ids)))
    db.session.flush()
    pairs = db.session.query(student_courses.c.course_id).filter(*cond).all()
    if not pairs:
        return 0
    from app.models.course import Course
    stamped = 0
    for row in pairs:
        cid = row[0]
        course = Course.query.get(cid)
        if course is None:
            continue
        db.session.execute(
            student_courses.update().where(
                student_courses.c.student_id == student_id,
                student_courses.c.course_id == cid,
                student_courses.c.agreed_fee.is_(None),
            ).values(agreed_fee=course.fees,
                     agreed_gst=bool(course.gst_applicable),
                     agreed_company_id=course.company_id)
        )
        stamped += 1
    return stamped


class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    roll_no = db.Column(db.String(20), unique=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    enrollment_date = db.Column(db.Date, default=lambda: datetime.utcnow().date())
    date_of_birth = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='Active')
    qr_code_uuid = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))
    photo = db.Column(db.String(255))
    photo_data = db.Column(db.LargeBinary)
    photo_mime = db.Column(db.String(50))
    courses = db.relationship('Course', secondary=student_courses, backref=db.backref('students', lazy='dynamic'))
    fee_records = db.relationship('FeeRecord', backref='student', cascade="all, delete-orphan", lazy=True)

    def __repr__(self):
        return f"<Student {self.name}>"


@event.listens_for(Student, 'before_insert')
def _assign_roll_no(mapper, connection, target):
    if not target.roll_no:
        target.roll_no = next_code('STU', Student, 'roll_no')
