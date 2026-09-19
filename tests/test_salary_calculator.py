"""Batch 1 (bugs) for the salary calculator:
B1 dropped/completed enrollments excluded (shared with payroll),
B2 commission % default matches payroll (no magic 10%),
B3 custom-range validation,
B4 deterministic fee-ledger ordering,
B5 active-only tutor dropdown + active-only split count + no future year.
"""
import re
from datetime import date

from app.extensions import db
from app.models import (Tutor, Course, Student, FeeRecord,
                        TutorPayrollSettings, student_courses, tutor_courses)

SEP = (9, 2026)


def _mk_tutor(app, name, status='Active'):
    with app.app_context():
        email = name.lower().replace(' ', '') + '@guha.b1.test'
        t = Tutor(name=name, email=email, phone='9' * 10, status=status)
        db.session.add(t)
        db.session.commit()
        return t.id


def _mk_course(app, code, tutor_id):
    with app.app_context():
        c = Course(name='Course ' + code, code=code, description='',
                   duration_weeks=4, duration_unit='weeks', fees=1000.0,
                   gst_applicable=False)
        db.session.add(c)
        db.session.flush()
        # Raw association insert (avoids mutating a relationship across the
        # short-lived app contexts used by these helpers).
        db.session.execute(tutor_courses.insert().values(tutor_id=tutor_id, course_id=c.id))
        db.session.commit()
        return c.id


def _mk_student(app, name, course_ids):
    with app.app_context():
        s = Student(name=name, email=name.lower().replace(' ', '') + '@guha.b1.test',
                    phone='9' * 10, status='Active')
        db.session.add(s)
        db.session.flush()
        for cid in course_ids:
            db.session.execute(student_courses.insert().values(student_id=s.id, course_id=cid))
        db.session.commit()
        return s.id


def _fee(app, student_id, amount, on):
    with app.app_context():
        db.session.add(FeeRecord(student_id=student_id, amount_paid=amount,
                                 taxable_amount=0.0, gst_amount=0.0,
                                 payment_date=on, payment_method='Cash'))
        db.session.commit()


def _set_enrollment(app, student_id, course_id, status):
    with app.app_context():
        db.session.execute(
            student_courses.update().where(
                student_courses.c.student_id == student_id,
                student_courses.c.course_id == course_id,
            ).values(status=status))
        db.session.commit()


def _set_settings(app, tutor_id, commission=None):
    with app.app_context():
        s = TutorPayrollSettings.query.filter_by(tutor_id=tutor_id).first()
        if s is None:
            s = TutorPayrollSettings(tutor_id=tutor_id)
            db.session.add(s)
        if commission is not None:
            s.commission_percentage = commission
        db.session.commit()


# ---- B1: Dropped/Completed enrollments are excluded ------------------------

def test_salary_calculator_excludes_dropped_student(admin_client, app):
    tid = _mk_tutor(app, 'DropCheck')
    cid = _mk_course(app, 'DC', tid)
    sid = _mk_student(app, 'Dropper', [cid])
    _fee(app, sid, 1000.0, date(2026, 9, 10))
    _set_enrollment(app, sid, cid, 'Dropped')

    body = admin_client.get(
        f'/salary-calculator?tutor_id={tid}&percentage=10&month={SEP[0]}&year={SEP[1]}'
    ).get_data(as_text=True)
    assert 'Enrolled Students (0)' in body
    assert 'Dropper' not in body
    assert 'No collections for this period' in body


def test_salary_calculator_keeps_active_sibling_enrollment(admin_client, app):
    # One dropped course must not hide the student while another is active.
    tid = _mk_tutor(app, 'SiblingCheck')
    ca = _mk_course(app, 'SA', tid)
    cb = _mk_course(app, 'SB', tid)
    sid = _mk_student(app, 'Sibling', [ca, cb])
    _fee(app, sid, 1000.0, date(2026, 9, 10))
    _set_enrollment(app, sid, cb, 'Completed')

    body = admin_client.get(
        f'/salary-calculator?tutor_id={tid}&percentage=10&month={SEP[0]}&year={SEP[1]}'
    ).get_data(as_text=True)
    assert 'Enrolled Students (1)' in body
    assert '1,000.00' in body


def test_compute_tutor_payroll_excludes_dropped_student(app):
    from app.routes.payroll_routes import compute_tutor_payroll
    tid = _mk_tutor(app, 'PayDrop')
    cid = _mk_course(app, 'PD', tid)
    sid = _mk_student(app, 'PayDropper', [cid])
    _fee(app, sid, 1000.0, date(2026, 9, 10))
    _set_enrollment(app, sid, cid, 'Dropped')
    _set_settings(app, tid, commission=10)

    with app.app_context():
        t = db.session.get(Tutor, tid)
        res = compute_tutor_payroll(t, SEP[0], SEP[1])
        assert res['commission'] == 0.0


def test_compute_tutor_payroll_splits_active_student(app):
    from app.routes.payroll_routes import compute_tutor_payroll
    tid = _mk_tutor(app, 'PayActive')
    cid = _mk_course(app, 'PA', tid)
    sid = _mk_student(app, 'PayActiveS', [cid])
    _fee(app, sid, 1000.0, date(2026, 9, 10))
    _set_settings(app, tid, commission=10)

    with app.app_context():
        t = db.session.get(Tutor, tid)
        res = compute_tutor_payroll(t, SEP[0], SEP[1])
        assert 99.0 <= res['commission'] <= 101.0


# ---- B2: commission % default mirrors payroll (0, never 10) ----------------

def test_salary_calculator_default_percentage_from_settings(admin_client, app):
    no_settings = _mk_tutor(app, 'NoSettings')
    zero_comm = _mk_tutor(app, 'ZeroComm')
    _set_settings(app, zero_comm, commission=0)
    mid_comm = _mk_tutor(app, 'MidComm')
    _set_settings(app, mid_comm, commission=7.5)

    assert 'value="0.0"' in admin_client.get(
        f'/salary-calculator?tutor_id={no_settings}').get_data(as_text=True)
    assert 'value="0.0"' in admin_client.get(
        f'/salary-calculator?tutor_id={zero_comm}').get_data(as_text=True)
    assert 'value="7.5"' in admin_client.get(
        f'/salary-calculator?tutor_id={mid_comm}').get_data(as_text=True)


# ---- B3: custom range must be complete and ordered -------------------------

def test_salary_calculator_reversed_range_rejected(admin_client, app):
    tid = _mk_tutor(app, 'RangeRev')
    body = admin_client.get(
        f'/salary-calculator?tutor_id={tid}&filter_type=range'
        '&start_date=2026-09-20&end_date=2026-09-01'
    ).get_data(as_text=True)
    assert 'From date cannot be after the To date' in body
    assert 'Enrolled Students' not in body  # no silent monthly fallback results


def test_salary_calculator_incomplete_range_rejected(admin_client, app):
    tid = _mk_tutor(app, 'RangeInc')
    body = admin_client.get(
        f'/salary-calculator?tutor_id={tid}&filter_type=range&start_date=2026-09-01'
    ).get_data(as_text=True)
    assert 'requires both a From and a To date' in body


def test_salary_calculator_valid_range_works(admin_client, app):
    tid = _mk_tutor(app, 'RangeOk')
    cid = _mk_course(app, 'RO', tid)
    sid = _mk_student(app, 'RangeOkS', [cid])
    _fee(app, sid, 500.0, date(2026, 9, 15))

    body = admin_client.get(
        f'/salary-calculator?tutor_id={tid}&percentage=10&filter_type=range'
        '&start_date=2026-09-01&end_date=2026-09-30'
    ).get_data(as_text=True)
    assert 'Enrolled Students (1)' in body
    assert '500.00' in body


# ---- B4: deterministic fee-ledger ordering ---------------------------------

def test_salary_calculator_fee_ledger_ordered(admin_client, app):
    tid = _mk_tutor(app, 'OrderCheck')
    cid = _mk_course(app, 'OC', tid)
    sid = _mk_student(app, 'OrderS', [cid])
    _fee(app, sid, 100.0, date(2026, 9, 10))
    _fee(app, sid, 200.0, date(2026, 9, 10))

    body = admin_client.get(
        f'/salary-calculator?tutor_id={tid}&percentage=10&month=9&year=2026'
    ).get_data(as_text=True)
    # Same-day receipts render newest-first (payment_date DESC, id DESC).
    assert body.index('200.00') < body.index('100.00')


# ---- B5: inactive tutors excluded; clean year range ------------------------

def test_salary_calculator_inactive_tutor_not_selectable(admin_client, app):
    _mk_tutor(app, 'HiddenInactiveTutor', status='Inactive')
    active = _mk_tutor(app, 'VisibleActiveTutor')
    body = admin_client.get('/salary-calculator').get_data(as_text=True)
    assert 'HiddenInactiveTutor' not in body
    assert 'VisibleActiveTutor' in body
    assert f'>{date.today().year + 1}<' not in body


def test_salary_calculator_inactive_cotutor_does_not_split(admin_client, app):
    tid = _mk_tutor(app, 'SplitActive')
    other = _mk_tutor(app, 'SplitInactive', status='Inactive')
    cid = _mk_course(app, 'SP', tid)
    with app.app_context():
        db.session.execute(tutor_courses.insert().values(tutor_id=other, course_id=cid))
        db.session.commit()
    sid = _mk_student(app, 'SplitS', [cid])
    _fee(app, sid, 1000.0, date(2026, 9, 10))

    body = admin_client.get(
        f'/salary-calculator?tutor_id={tid}&percentage=10&month=9&year=2026'
    ).get_data(as_text=True)
    assert 'Enrolled Students (1)' in body
    assert 'Shared courses detected' not in body
    assert '1,000.00' in body