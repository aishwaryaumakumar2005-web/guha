"""Batch 1 (bugs) + Batch 2 (functionality) for the salary calculator:
B1 dropped/completed enrollments excluded (shared with payroll),
B2 commission % default matches payroll (no magic 10%),
B3 custom-range validation,
B4 deterministic fee-ledger ordering,
B5 active-only tutor dropdown + active-only split count + no future year,
F1 enrollment-period-aware fee attribution (shared with payroll),
F2 net-pay projection card from payroll settings,
F3 per-student commission breakdown,
F4 'Generate payroll draft' action (POST /payroll/process),
F5a single commission-% source of truth (tutor_commission_percentage) +
F5b show/hide split-details toggle.
"""
import re
from datetime import date

from app.extensions import db
from app.models import (Tutor, Course, Student, FeeRecord, PayrollRecord,
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


def _set_enrollment_dates(app, student_id, course_id, enrolled_on=None,
                          completed_on=None):
    with app.app_context():
        db.session.execute(
            student_courses.update().where(
                student_courses.c.student_id == student_id,
                student_courses.c.course_id == course_id,
            ).values(enrolled_on=enrolled_on, completed_on=completed_on))
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


# ---- F1: enrollment-period-aware attribution (shared with payroll) ----------

def test_salary_calculator_fee_before_enrollment_excluded(admin_client, app):
    tid = _mk_tutor(app, 'EarlyFee')
    cid = _mk_course(app, 'EF', tid)
    sid = _mk_student(app, 'EarlyFeeS', [cid])
    # enrollment only starts 2026-09-15; the 2026-09-10 payment predates it
    _set_enrollment_dates(app, sid, cid, enrolled_on=date(2026, 9, 15))
    _fee(app, sid, 1000.0, date(2026, 9, 10))

    body = admin_client.get(
        f'/salary-calculator?tutor_id={tid}&percentage=10&month=9&year=2026'
    ).get_data(as_text=True)
    assert 'Fee Ledger Receipts (0)' in body
    assert 'No collections for this period' in body


def test_salary_calculator_fee_after_completion_excluded(admin_client, app):
    tid = _mk_tutor(app, 'LateFee')
    cid = _mk_course(app, 'LF', tid)
    sid = _mk_student(app, 'LateFeeS', [cid])
    _set_enrollment_dates(app, sid, cid, enrolled_on=date(2026, 9, 1),
                          completed_on=date(2026, 9, 15))
    _fee(app, sid, 1000.0, date(2026, 9, 20))

    body = admin_client.get(
        f'/salary-calculator?tutor_id={tid}&percentage=10&month=9&year=2026'
    ).get_data(as_text=True)
    assert 'Fee Ledger Receipts (0)' in body
    assert 'No collections for this period' in body


def test_salary_calculator_only_inwindow_fees_count(admin_client, app):
    tid = _mk_tutor(app, 'WindowFee')
    cid = _mk_course(app, 'WF', tid)
    sid = _mk_student(app, 'WindowFeeS', [cid])
    _set_enrollment_dates(app, sid, cid, enrolled_on=date(2026, 9, 1),
                          completed_on=date(2026, 9, 15))
    _fee(app, sid, 1000.0, date(2026, 9, 10))  # inside -> counts
    _fee(app, sid, 500.0, date(2026, 9, 20))   # after completion -> ignored

    body = admin_client.get(
        f'/salary-calculator?tutor_id={tid}&percentage=10&month=9&year=2026'
    ).get_data(as_text=True)
    assert 'Fee Ledger Receipts (1)' in body
    assert 'No collections for this period' not in body


def test_payroll_and_calculator_agree_on_overlap(app, admin_client):
    from app.routes.payroll_routes import compute_tutor_payroll
    tid = _mk_tutor(app, 'ParityOverlap')
    cid = _mk_course(app, 'PO', tid)
    sid = _mk_student(app, 'ParityOverlapS', [cid])
    _set_enrollment_dates(app, sid, cid, enrolled_on=date(2026, 9, 1),
                          completed_on=date(2026, 9, 15))
    _fee(app, sid, 1000.0, date(2026, 9, 10))
    _fee(app, sid, 500.0, date(2026, 9, 20))
    _set_settings(app, tid, commission=10)

    with app.app_context():
        t = db.session.get(Tutor, tid)
        res = compute_tutor_payroll(t, SEP[0], SEP[1])
        assert 99.0 <= res['commission'] <= 101.0  # only the in-window fee

    body = admin_client.get(
        f'/salary-calculator?tutor_id={tid}&month=9&year=2026'
    ).get_data(as_text=True)
    assert 'Fee Ledger Receipts (1)' in body
    assert '100.00' in body


# ---- F2: net-pay projection from payroll settings ---------------------------

def test_salary_calculator_projection_math(admin_client, app):
    tid = _mk_tutor(app, 'ProjectMath')
    cid = _mk_course(app, 'PM', tid)
    sid = _mk_student(app, 'ProjectMathS', [cid])
    _fee(app, sid, 1000.0, date(2026, 9, 10))
    with app.app_context():
        s = TutorPayrollSettings.query.filter_by(tutor_id=tid).first()
        if s is None:
            s = TutorPayrollSettings(tutor_id=tid)
            db.session.add(s)
        s.base_salary = 5000.0
        s.commission_percentage = 10.0
        s.tds_percentage = 5.0
        s.bonus = 500.0
        s.other_deductions = 200.0
        db.session.commit()

    body = admin_client.get(
        f'/salary-calculator?tutor_id={tid}&month=9&year=2026'
    ).get_data(as_text=True)
    assert 'Projected Net Pay' in body
    # 5000 base + 100 commission + 500 bonus - 280 TDS (5%) - 200 other
    assert '5,120.00' in body
    assert 'No payroll settings configured' not in body


def test_salary_calculator_projection_without_settings(admin_client, app):
    tid = _mk_tutor(app, 'ProjectPlain')
    cid = _mk_course(app, 'PP', tid)
    sid = _mk_student(app, 'ProjectPlainS', [cid])
    _fee(app, sid, 1000.0, date(2026, 9, 10))

    body = admin_client.get(
        f'/salary-calculator?tutor_id={tid}&percentage=5&month=9&year=2026'
    ).get_data(as_text=True)
    assert 'Projected Net Pay' in body
    assert 'No payroll settings configured' in body
    # net == commission only (50 @ 5%); base/TDS/bonus treated as 0
    assert '50.00' in body


# ---- F3 + F5b: per-student breakdown table and show/hide toggle -------------

def test_salary_calculator_breakdown_table_and_toggle(admin_client, app):
    tid = _mk_tutor(app, 'BreakdownUI')
    cid = _mk_course(app, 'BU', tid)
    sid = _mk_student(app, 'BreakdownUI S', [cid])
    _fee(app, sid, 1200.0, date(2026, 9, 10))
    _set_settings(app, tid, commission=10)

    body = admin_client.get(
        f'/salary-calculator?tutor_id={tid}&month=9&year=2026'
    ).get_data(as_text=True)
    assert 'Per-Student Commission Breakdown' in body
    assert 'id="splitToggle"' in body
    assert 'id="splitDetails"' in body
    assert 'Effective Share' in body
    assert '1,200.00' in body
    assert '120.00' in body


def test_salary_calculator_breakdown_shared_split_share(admin_client, app):
    # two ACTIVE tutors over the same course -> each takes 1/2 of the fee
    tid = _mk_tutor(app, 'BreakdownA')
    tid2 = _mk_tutor(app, 'BreakdownB')
    cid = _mk_course(app, 'BX', tid)
    with app.app_context():
        db.session.execute(tutor_courses.insert().values(tutor_id=tid2, course_id=cid))
        db.session.commit()
    sid = _mk_student(app, 'BreakdownXS', [cid])
    _fee(app, sid, 1000.0, date(2026, 9, 10))
    _set_settings(app, tid, commission=10)

    body = admin_client.get(
        f'/salary-calculator?tutor_id={tid}&month=9&year=2026'
    ).get_data(as_text=True)
    assert 'Shared courses detected' in body
    assert 'Per-Student Commission Breakdown' in body
    # share = 500 -> commission 50 per tutor
    assert '500.00' in body
    assert '50.00' in body


# ---- F4: generate payroll draft (POST /payroll/process) ---------------------

def test_salary_calculator_generate_draft_form_present(admin_client, app):
    tid = _mk_tutor(app, 'DraftMaker')
    cid = _mk_course(app, 'DM', tid)
    sid = _mk_student(app, 'DraftMakerS', [cid])
    _fee(app, sid, 1000.0, date(2026, 9, 10))
    _set_settings(app, tid, commission=10)

    body = admin_client.get(
        f'/salary-calculator?tutor_id={tid}&month=9&year=2026'
    ).get_data(as_text=True)
    assert 'action="/payroll/process"' in body
    assert 'name="tutor_id"' in body
    assert 'name="month"' in body
    assert 'name="year"' in body
    assert 'name="percentage"' in body
    assert 'Generate payroll draft for Sep 2026' in body


def test_salary_calculator_generate_draft_creates_draft(app, admin_client):
    tid = _mk_tutor(app, 'DraftCreator')
    cid = _mk_course(app, 'DC2', tid)
    sid = _mk_student(app, 'DraftCreatorS', [cid])
    _fee(app, sid, 1000.0, date(2026, 9, 10))
    _set_settings(app, tid, commission=10)

    resp = admin_client.post('/payroll/process', data={
        'tutor_id': str(tid), 'month': '9', 'year': '2026',
    }, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        rec = PayrollRecord.query.filter_by(tutor_id=tid, month=9, year=2026).first()
        assert rec is not None
        assert rec.status == 'Draft'
        assert 99.0 <= rec.commission_amount <= 101.0


def test_salary_calculator_generate_draft_hidden_for_range(admin_client, app):
    tid = _mk_tutor(app, 'DraftHider')
    cid = _mk_course(app, 'DH', tid)
    sid = _mk_student(app, 'DraftHiderS', [cid])
    _fee(app, sid, 1000.0, date(2026, 9, 10))

    body = admin_client.get(
        f'/salary-calculator?tutor_id={tid}&percentage=10&filter_type=range'
        '&start_date=2026-09-01&end_date=2026-09-30'
    ).get_data(as_text=True)
    assert 'Generate payroll draft' not in body