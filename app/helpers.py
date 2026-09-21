import os
import uuid
from functools import wraps
from flask import request, redirect, url_for, flash, current_app
from flask_login import current_user
from app.extensions import db

ALLOWED_PHOTO_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Cap on rows rendered by the finance list pages (fees history, expenses,
# funding). Pages show "latest N of M" with a nudge to the filters instead
# of loading unbounded tables into the DOM.
FINANCE_LIST_LIMIT = 200


def save_photo_data(file_storage, max_mb=4):
    """Validate an uploaded photo and return (raw_bytes, mime) for DB storage, or None."""
    if not file_storage or not getattr(file_storage, 'filename', None):
        return None
    name = file_storage.filename
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if ext not in ALLOWED_PHOTO_EXT:
        raise ValueError(f"Unsupported photo format: .{ext or 'unknown'}")
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > max_mb * 1024 * 1024:
        raise ValueError(f"Photo exceeds {max_mb}MB limit")
    data = file_storage.read()
    mime = getattr(file_storage, 'mimetype', None) or f'image/{ext if ext != "jpg" else "jpeg"}'
    if mime.startswith('application/octet-stream') or '/' not in mime:
        mime = f'image/{ext if ext != "jpg" else "jpeg"}'
    return data, mime


def save_photo(file_storage, max_mb=4):
    """Legacy: persist an uploaded photo into static/uploads and return its filename, or None."""
    if not file_storage or not getattr(file_storage, 'filename', None):
        return None
    name = file_storage.filename
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if ext not in ALLOWED_PHOTO_EXT:
        raise ValueError(f"Unsupported photo format: .{ext or 'unknown'}")
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > max_mb * 1024 * 1024:
        raise ValueError(f"Photo exceeds {max_mb}MB limit")
    filename = 'u' + uuid.uuid4().hex[:12] + '.' + ext
    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    file_storage.save(os.path.join(upload_dir, filename))
    return filename


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if current_user.role != 'Admin':
            flash("Access denied: Admin permissions required.", "danger")
            return redirect(url_for('dashboard.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def is_ajax_request():
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def staff_can_view_student(student_id):
    """Admins see every student; staff only those sharing their courses.

    Imports are lazy because app.models imports from this module.
    """
    if not current_user.is_authenticated:
        return False
    if current_user.role == 'Admin':
        return True
    if current_user.role != 'Staff':
        return False
    from app.models import Tutor, student_courses
    tutor = Tutor.query.filter_by(email=current_user.email).first()
    if not tutor:
        return False
    course_ids = [c.id for c in tutor.courses]
    if not course_ids:
        return False
    return db.session.query(student_courses).filter(
        student_courses.c.student_id == student_id,
        student_courses.c.course_id.in_(course_ids)
    ).first() is not None


BACKUP_DIR = None


def get_backup_dir(app):
    global BACKUP_DIR
    if BACKUP_DIR is None:
        import os
        BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(app.root_path)), 'backups')
    return BACKUP_DIR


def next_code(prefix, model, column):
    """Return the next sequential public code (e.g. STU0004) for model.column.

    Reads only the code column (never full rows), so bulk imports don't pay
    an N+1 object load per insert. Two concurrent transactions can still
    compute the same value — callers creating records must commit through
    commit_with_retry() below instead of a bare db.session.commit().
    """
    col = getattr(model, column)
    seen = [val for (val,) in
            db.session.query(col).filter(col.startswith(prefix)).all()]
    # Same-flush siblings: when several objects are added before one flush,
    # earlier siblings' codes live only in the session (uncommitted), so the
    # query above can't see them. Read local __dict__ state (never triggers
    # a refresh — expired attributes are simply skipped; committed rows are
    # already covered by the query).
    for obj in list(db.session.new) + list(db.session.identity_map.values()):
        if isinstance(obj, model):
            seen.append(obj.__dict__.get(column))
    max_num = 0
    for val in seen:
        if val and val.startswith(prefix):
            try:
                max_num = max(max_num, int(val[len(prefix):]))
            except (ValueError, TypeError):
                continue
    return f'{prefix}{max_num + 1:04d}'


def cell_text(value):
    """Excel cell -> stripped string. Empty cells become '', never 'None'.

    Shared by the student/tutor importers so blank cells can't become
    literal 'None' records.
    """
    if value is None:
        return ''
    text = str(value).strip()
    return '' if text.lower() == 'none' else text


def get_gst_rates():
    """Return (cgst_pct, sgst_pct) from SystemSetting with safe fallbacks.

    Never raises: missing, blank, non-numeric, or out-of-range values fall
    back to 9.0 each. Every reader must use this instead of float()-ing the
    raw setting (a single bad admin save used to 500 every fee/GST page).
    """
    from app.models import SystemSetting

    def _rate(key):
        try:
            row = SystemSetting.query.filter_by(key=key).first()
            if row is None or row.value in (None, ''):
                return 9.0
            val = float(row.value)
            if 0 <= val <= 100:
                return val
        except (TypeError, ValueError):
            pass
        return 9.0

    return _rate('CGST_PCT'), _rate('SGST_PCT')


def commit_with_retry(build_and_commit, attempts=3):
    """Run build_and_commit() (which ends with commit) with IntegrityError retries.

    The callback must rebuild all of its objects from scratch on every call:
    a failed attempt leaves the session rolled back and pending objects
    detached, so reusing them would re-insert stale state. Re-raises the
    last IntegrityError when attempts run out.
    """
    from sqlalchemy.exc import IntegrityError
    last_exc = None
    for _ in range(attempts):
        try:
            return build_and_commit()
        except IntegrityError as e:
            db.session.rollback()
            last_exc = e
    raise last_exc


# Enrollment statuses that no longer count as an active teaching relationship.
# Any other value (including legacy NULL) is treated as active. Shared by the
# salary calculator and payroll commission so both attribute fees identically.
INACTIVE_ENROLLMENT_STATUSES = ('Dropped', 'Completed')


def tutor_students(tutor_id):
    """Students with an active enrollment in a course taught by `tutor_id`.

    Excludes student_courses rows whose status is Dropped/Completed (a dropped
    student's historical fees must not be attributed to a tutor forever), while
    legacy NULL rows remain included. Returns a deduplicated list of Student,
    one per student regardless of how many of that tutor's courses they take.
    """
    from sqlalchemy import or_
    from app.models import Student, Course, Tutor, student_courses, tutor_courses
    rows = (
        Student.query
        .join(student_courses, student_courses.c.student_id == Student.id)
        .join(Course, Course.id == student_courses.c.course_id)
        .join(tutor_courses, tutor_courses.c.course_id == Course.id)
        .join(Tutor, Tutor.id == tutor_courses.c.tutor_id)
        .filter(
            Tutor.id == tutor_id,
            or_(student_courses.c.status.is_(None),
                student_courses.c.status.notin_(INACTIVE_ENROLLMENT_STATUSES)),
        )
        .all()
    )
    # Multi-course enrollments yield one ORM row per matching association; the
    # raw SQL may duplicate the student (Postgres does not dedupe). Collapse to
    # one Student per id so both the list and fee attribution are exact.
    seen = set()
    unique = []
    for s in rows:
        if s.id not in seen:
            seen.add(s.id)
            unique.append(s)
    return unique


def active_tutor_count_for_student(student_id):
    """Distinct ACTIVE tutors currently teaching `student_id`.

    Only active tutors over active enrollments count, so an inactive tutor (or
    a Dropped/Completed association) no longer halves a student's effective
    fees. Mirrors tutor_students() for the split denominator.
    """
    from sqlalchemy import distinct, or_
    from app.models import Tutor, Course, tutor_courses, student_courses
    return (
        db.session.query(db.func.count(distinct(Tutor.id)))
        .select_from(Tutor)
        .join(tutor_courses, Tutor.id == tutor_courses.c.tutor_id)
        .join(Course, Course.id == tutor_courses.c.course_id)
        .join(student_courses, student_courses.c.course_id == Course.id)
        .filter(
            student_courses.c.student_id == student_id,
            Tutor.status == 'Active',
            or_(student_courses.c.status.is_(None),
                student_courses.c.status.notin_(INACTIVE_ENROLLMENT_STATUSES)),
        )
        .scalar() or 0
    )


def tutor_commission_percentage(tutor_id):
    """Effective commission % used to generate payroll for a tutor.

    Single source of truth shared by the salary calculator and
    compute_tutor_payroll: reads TutorPayrollSettings and falls back to 0.0
    when unset (commission is zero, never a magic default).
    """
    from app.models import TutorPayrollSettings
    settings = TutorPayrollSettings.query.filter_by(tutor_id=tutor_id).first()
    return (settings.commission_percentage or 0.0) if settings else 0.0


def _enrollment_spans(intervals, fee_date):
    """True when `fee_date` falls inside at least one enrollment interval.

    Intervals are (enrolled_on, completed_on) pairs; NULL bounds are open
    (no start / no end) so legacy rows always match. Accounting is on the
    calendar date — fees paid before a student joins or after they leave a
    tutor's course belong to another tutor.
    """
    for enrolled_on, completed_on in intervals:
        if enrolled_on and fee_date < enrolled_on:
            continue
        if completed_on and fee_date > completed_on:
            continue
        return True
    return False


def tutor_overlapping_fees(tutor_id, start_date, end_date):
    """FeeRecord rows attributable to `tutor_id` in [start_date, end_date].

    A fee is attributed only when the payer had a live enrollment under this
    tutor ON the payment date: the association status must be active
    (Dropped/Completed never count) and, when present, enrolled_on <= fee date
    and completed_on >= fee date. Legacy rows without dates always count.
    Returns rows ordered by payment_date DESC, id DESC.
    """
    from sqlalchemy import or_
    from app.models import Course, FeeRecord, student_courses, tutor_courses
    intervals = (
        db.session.query(
            student_courses.c.student_id,
            student_courses.c.enrolled_on,
            student_courses.c.completed_on,
        )
        .join(Course, Course.id == student_courses.c.course_id)
        .join(tutor_courses, tutor_courses.c.course_id == Course.id)
        .filter(
            tutor_courses.c.tutor_id == tutor_id,
            or_(student_courses.c.status.is_(None),
                student_courses.c.status.notin_(INACTIVE_ENROLLMENT_STATUSES)),
        )
        .all()
    )
    intervals_by_student = {}
    for sid, enrolled_on, completed_on in intervals:
        intervals_by_student.setdefault(sid, []).append((enrolled_on, completed_on))
    if not intervals_by_student:
        return []
    records = (
        FeeRecord.query.filter(
            FeeRecord.student_id.in_(list(intervals_by_student)),
            FeeRecord.payment_date >= start_date,
            FeeRecord.payment_date <= end_date,
            FeeRecord.status != 'Voided',
        )
        .order_by(FeeRecord.payment_date.desc(), FeeRecord.id.desc())
        .all()
    )
    return [r for r in records if _enrollment_spans(intervals_by_student[r.student_id], r.payment_date)]
