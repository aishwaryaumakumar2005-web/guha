from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import User, Student, Tutor, Course, Enquiry, FeeRecord, Attendance, LeaveRequest, Exam, Task, student_courses
from app.helpers import admin_required, get_gst_rates, is_ajax_request
from app.services.account_service import (compute_account_summary,
                                          agreed_enrollment_items_bulk,
                                          student_refunded_totals_bulk)
from sqlalchemy import func, case
from time import time

dashboard_bp = Blueprint('dashboard', __name__)

# Keyed by role string so admin and staff stats never bleed into each other.
_stats_cache: dict = {}


def _empty_stats():
    """Zeroed stats shape. Served when a stats query fails so the page (or a
    JSON endpoint) degrades instead of raising."""
    return {
        "active_students": 0, "tutors": 0, "courses": 0,
        "enquiries": 0, "enquiries_new": 0, "enquiries_contacted": 0,
        "enquiries_visited": 0, "enquiries_converted": 0, "enquiries_lost": 0,
        "unresolved_enquiries": 0, "monthly_fees_collected": 0.0,
        "avg_student_attendance": None, "low_attendance_count": 0,
    }

def _empty_staff_stats():
    data = _empty_stats()
    data.update({'active_students': 0, 'tutors': 0, 'courses': 0,
                 'enquiries': 0, 'enquiries_new': 0, 'enquiries_contacted': 0,
                 'enquiries_visited': 0, 'enquiries_converted': 0,
                 'enquiries_lost': 0, 'monthly_fees_collected': 0.0})
    return data


def _safe(label, fn, default):
    """Run a dashboard section; on any DB error roll the session back (a
    failed statement poisons it for the rest of the request) and return the
    default so one bad section can't 500 the whole page."""
    try:
        return fn()
    except Exception:
        current_app.logger.exception('Dashboard section failed: %s', label)
        try:
            db.session.rollback()
        except Exception:
            pass
        return default


def get_dashboard_stats():
    from time import time
    role = getattr(current_user, 'role', 'anonymous')
    cache_key = (role, getattr(current_user, 'id', None))
    bucket = _stats_cache.get(cache_key, {"data": None, "time": 0})
    if time() - bucket["time"] < 30 and bucket["data"]:
        # Return a copy: callers (e.g. the Staff branch) add per-request keys,
        # and mutating the shared cached dict would leak them across roles.
        return dict(bucket["data"])
    try:
        data = _compute_staff_stats() if role == 'Staff' else _compute_stats()
    except Exception:
        current_app.logger.exception('get_dashboard_stats failed; serving zeros')
        try:
            db.session.rollback()
        except Exception:
            pass
        return _empty_stats()
    _stats_cache[cache_key] = {"data": data, "time": time()}
    return dict(data)

def _compute_staff_stats():
    """Return only metrics belonging to the current tutor's assigned students."""
    scope_ids = _staff_student_scope()
    if not scope_ids:
        return _empty_staff_stats()
    today = date.today()
    start_of_month = date(today.year, today.month, 1)
    tutor = Tutor.query.filter_by(email=current_user.email).first()
    course_ids = [c.id for c in tutor.courses] if tutor else []
    q = Enquiry.query.filter(Enquiry.course_id.in_(course_ids)) if course_ids else Enquiry.query.filter(db.false())
    counts = {status: q.filter_by(status=status).count() for status in ('New', 'Contacted', 'Visited', 'Converted', 'Lost')}
    att = db.session.query(func.count(Attendance.id).label('total'), func.sum(case((Attendance.status == 'Present', 1), else_=0)).label('present')).filter(
        Attendance.person_type == 'student', Attendance.person_id.in_(scope_ids), Attendance.date >= today - timedelta(days=14)).first()
    total_att, present_att = att.total or 0, att.present or 0
    return {'active_students': len(scope_ids), 'tutors': 1 if tutor else 0, 'courses': len(course_ids),
            'enquiries': sum(counts.values()), 'enquiries_new': counts['New'], 'enquiries_contacted': counts['Contacted'],
            'enquiries_visited': counts['Visited'], 'enquiries_converted': counts['Converted'], 'enquiries_lost': counts['Lost'],
            'unresolved_enquiries': counts['New'] + counts['Contacted'], 'monthly_fees_collected': 0.0,
            'avg_student_attendance': int(present_att * 100 / total_att) if total_att else None,
            'low_attendance_count': _scope_low_attendance(today, scope_ids)}


def _compute_stats():
    today = date.today()
    start_of_month = date(today.year, today.month, 1)
    fourteen_days_ago = today - timedelta(days=14)
    active_students = Student.query.filter_by(status='Active').count()
    tutors = Tutor.query.filter_by(status='Active').count()
    courses = Course.query.count()
    enquiries_new = Enquiry.query.filter_by(status='New').count()
    enquiries_contacted = Enquiry.query.filter_by(status='Contacted').count()
    enquiries_visited = Enquiry.query.filter_by(status='Visited').count()
    enquiries_converted = Enquiry.query.filter_by(status='Converted').count()
    enquiries_lost = Enquiry.query.filter_by(status='Lost').count()
    total_enquiries = Enquiry.query.count()
    unresolved_enquiries = enquiries_new + enquiries_contacted
    monthly_fees = db.session.query(db.func.sum(FeeRecord.amount_paid)).filter(
        FeeRecord.payment_date >= start_of_month,
        FeeRecord.payment_date <= today
    ).scalar() or 0.0
    att_counts = db.session.query(
        func.count(Attendance.id).label('total'),
        func.sum(case((Attendance.status == 'Present', 1), else_=0)).label('present')
    ).filter(
        Attendance.date >= fourteen_days_ago,
        Attendance.person_type == 'student'
    ).first()
    total_att_records = att_counts.total or 0
    present_att_records = att_counts.present or 0
    # No records means "no data" (None), never a plausible-looking fake number.
    avg_att = None
    if total_att_records > 0:
        avg_att = int((present_att_records / total_att_records) * 100)
    # Bound to the same 14-day window as the headline rate: without a date
    # filter this scans the entire attendance history on every cache miss.
    att_stats = db.session.query(
        Attendance.person_id,
        func.count(Attendance.id).label('total'),
        func.sum(case((Attendance.status == 'Present', 1), else_=0)).label('present')
    ).filter(
        Attendance.person_type == 'student',
        Attendance.date >= fourteen_days_ago
    ).group_by(Attendance.person_id).having(
        func.count(Attendance.id) >= 3
    ).all()
    low_att_count = sum(1 for s in att_stats if (s.present * 100.0 / s.total) < 75)
    return {
        "active_students": active_students, "tutors": tutors, "courses": courses,
        "enquiries": total_enquiries, "enquiries_new": enquiries_new,
        "enquiries_contacted": enquiries_contacted, "enquiries_visited": enquiries_visited,
        "enquiries_converted": enquiries_converted,
        "enquiries_lost": enquiries_lost, "unresolved_enquiries": unresolved_enquiries,
        "monthly_fees_collected": float(monthly_fees), "avg_student_attendance": avg_att,
        "low_attendance_count": low_att_count
    }

def _today_figures(today):
    today_fees = db.session.query(db.func.sum(FeeRecord.amount_paid)).filter(
        FeeRecord.payment_date == today
    ).scalar() or 0.0
    today_attendance = db.session.query(db.func.count(Attendance.id)).filter(
        Attendance.date == today, Attendance.person_type == 'student'
    ).scalar() or 0
    return float(today_fees), int(today_attendance)


def _recent_lists():
    return (Enquiry.query.order_by(Enquiry.id.desc()).limit(5).all(),
            FeeRecord.query.order_by(FeeRecord.payment_date.desc(), FeeRecord.id.desc()).limit(5).all())


def _fee_chart(today, months=6):
    # Use relativedelta for correct month arithmetic across year boundaries.
    # Pure-stdlib fallback if dateutil is not installed.
    try:
        from dateutil.relativedelta import relativedelta
        def _month_offset(d, months_back):
            shifted = d - relativedelta(months=months_back)
            return shifted.year, shifted.month
    except ImportError:
        def _month_offset(d, months_back):
            m = d.month - months_back
            y = d.year
            while m <= 0:
                m += 12
                y -= 1
            return y, m

    months = max(1, min(24, int(months or 6)))
    start_y, start_m = _month_offset(today, months - 1)
    start_date = date(start_y, start_m, 1)

    monthly = db.session.query(
        db.extract('month', FeeRecord.payment_date).label('m'),
        db.extract('year', FeeRecord.payment_date).label('y'),
        db.func.sum(FeeRecord.amount_paid).label('total')
    ).filter(FeeRecord.payment_date >= start_date
    ).group_by('y', 'm').order_by('y', 'm').all()
    totals_by_ym = {(int(r.y), int(r.m)): float(r.total) for r in monthly}
    chart_months = []
    chart_data = []
    for i in range(months - 1, -1, -1):
        y, m = _month_offset(today, i)
        month_start = date(y, m, 1)
        chart_months.append(month_start.strftime("%b %y") if months > 6 else month_start.strftime("%b"))
        chart_data.append(totals_by_ym.get((y, m), 0.0))
    return chart_months, chart_data


def _top_courses():
    # Top courses by enrollment count. Include capacity so we can show seat-fill %.
    return db.session.query(
        Course.id, Course.name, Course.capacity,
        func.count(student_courses.c.student_id).label('enrolled')
    ).outerjoin(student_courses, db.and_(Course.id == student_courses.c.course_id,
                                         db.or_(student_courses.c.status == 'Enrolled', student_courses.c.status.is_(None)))
    ).group_by(Course.id, Course.name, Course.capacity
    ).order_by(func.count(student_courses.c.student_id).desc()
    ).limit(5).all()


def _fee_due_rows(student_ids=None):
    """Outstanding-fees position per active student, mirroring the fees-page
    rule exactly (fees.py list / student_outstanding_bulk): dues are the agreed
    fees *inclusive* of GST (GST-applicable courses get the current CGST+SGST
    on the taxable base) and balance = due - paid - concessions + refunded.

    Batched — no per-student query loops (previously N+1 lazy loads). Passing
    ``student_ids`` scopes the scan (e.g. the staff today-tasks API); None
    means every active student.
    """
    if student_ids is not None:
        student_ids = list(student_ids)
        if not student_ids:
            return []
    query = Student.query.filter_by(status='Active')
    if student_ids is not None:
        query = query.filter(Student.id.in_(student_ids))
    students = query.all()
    sids = [s.id for s in students]
    cgst_pct, sgst_pct = get_gst_rates()
    total_gst_pct = cgst_pct + sgst_pct
    items_map = agreed_enrollment_items_bulk(sids)
    refunded_map = student_refunded_totals_bulk(sids)
    paid_rows = db.session.query(
        FeeRecord.student_id,
        db.func.sum(FeeRecord.amount_paid).label('paid'),
        db.func.sum(db.func.coalesce(FeeRecord.concession, 0)).label('concession')
    ).filter(FeeRecord.student_id.in_(sids)).group_by(FeeRecord.student_id).all()
    paid_map = {sid: (float(paid or 0), float(concession or 0))
                for sid, paid, concession in paid_rows}
    rows = []
    for s in students:
        items = items_map.get(s.id, [])
        total_taxable = round(sum(it['fee'] for it in items), 2)
        gst_amount = round(sum(
            round(it['fee'] * total_gst_pct / 100, 2) for it in items if it['gst_applicable']
        ), 2)
        total_fee = round(total_taxable + gst_amount, 2)
        paid, concession = paid_map.get(s.id, (0.0, 0.0))
        paid = round(paid, 2)
        concession = round(concession, 2)
        refunded = refunded_map.get(s.id, 0.0)
        # Aging: days since enrollment — used for overdue-bucket display.
        # Named days_enrolled to distinguish from "days the fee is late",
        # which would require knowing each fee's due date.
        days_enrolled = None
        if s.enrollment_date:
            days_enrolled = max(0, (date.today() - s.enrollment_date).days)
        rows.append({
            'id': s.id, 'name': s.name, 'roll_no': s.roll_no,
            'total_fee': total_fee, 'total_taxable': total_taxable,
            'gst_amount': gst_amount, 'paid': paid,
            'concession': concession, 'refunded': refunded,
            'days_enrolled': days_enrolled,
            # Keep days_due as an alias so other callers (todays-activities) don't break.
            'days_due': days_enrolled,
            'balance': round(total_fee - paid - concession + refunded, 2),
        })
    return rows


def _fee_dues():
    """Outstanding fees per active student (balance > ₹1), sorted by balance desc.

    Single batched pass via ``_fee_due_rows`` — no N+1. ``ageing`` sums the
    balances by days-overdue bucket (mirrors the fees-matrix thresholds):
    >90 days, 31-90 days, 30 or fewer. Result:
    ([{name, roll_no, total_fee, paid, balance, days_due}] sorted by balance desc,
    total_outstanding, ageing).
    """
    due_students = [r for r in _fee_due_rows() if r['balance'] > 1]
    due_students.sort(key=lambda d: d['balance'], reverse=True)
    ageing = {'over_90': 0.0, 'over_30': 0.0, 'recent': 0.0}
    for d in due_students:
        days = d['days_due'] or 0
        bucket = 'over_90' if days > 90 else ('over_30' if days > 30 else 'recent')
        ageing[bucket] += d['balance']
    ageing = {k: round(v, 2) for k, v in ageing.items()}
    return due_students, round(sum(d['balance'] for d in due_students), 2), ageing


def _capacity():
    # Active enrollments only (see courses.list): dropped/completed students
    # must not consume capacity or trigger overflow flags.
    enroll_rows = db.session.query(
        student_courses.c.course_id, db.func.count(student_courses.c.student_id).label('cnt')
    ).filter(db.or_(
        student_courses.c.status == 'Enrolled',
        student_courses.c.status.is_(None),
    )).group_by(student_courses.c.course_id).all()
    enroll_map = {cid: cnt for cid, cnt in enroll_rows}
    overflow_capacity = 0
    capacity_courses = []
    for c in Course.query.all():
        enrolled = enroll_map.get(c.id, 0)
        seats = c.capacity or 30
        pct = round(enrolled / seats * 100) if seats else 0
        if enrolled > seats:
            overflow_capacity += 1
        capacity_courses.append({'id': c.id, 'name': c.name, 'code': c.code,
                                 'enrolled': enrolled, 'capacity': seats, 'pct': min(100, pct),
                                 'over': enrolled > seats})
    capacity_courses.sort(key=lambda x: x['pct'], reverse=True)
    return capacity_courses, overflow_capacity


def _celebrations(today):
    # Birthdays & enrollment anniversaries today.
    # Filter Active in SQL — never pull Inactive/Completed students into memory.
    today_md = (today.month, today.day)
    active_students = Student.query.filter_by(status='Active').all()
    birthdays_today = [{'id': s.id, 'name': s.name, 'roll_no': s.roll_no, 'phone': s.phone,
                        'msg': current_app.messenger.birthday_message(s.name, today.year - s.date_of_birth.year)}
                       for s in active_students
                       if s.date_of_birth
                       and (s.date_of_birth.month, s.date_of_birth.day) == today_md]
    anniversaries_today = [{'name': s.name, 'roll_no': s.roll_no} for s in active_students
                           if s.enrollment_date
                           and (s.enrollment_date.month, s.enrollment_date.day) == today_md
                           and (s.enrollment_date.year, s.enrollment_date.month, s.enrollment_date.day) != (today.year, today.month, today.day)]
    return birthdays_today, anniversaries_today


def _staff_leave_counts(user):
    pending = LeaveRequest.query.filter_by(user_id=user.id, status='Pending').count()
    approved = LeaveRequest.query.filter_by(user_id=user.id, status='Approved').count()
    return pending, approved


def _staff_leave_days_this_month(user_id):
    from app.routes.leaves import _days_on_leave_this_month
    return _days_on_leave_this_month(user_id)


def _staff_student_scope():
    """Active student ids across the current user's courses (staff only).

    Empty for admins / tutors with no courses: scoped stats then degrade to
    *no data*, never to institute-global numbers staff shouldn't see."""
    tutor = Tutor.query.filter_by(email=current_user.email).first()
    if not tutor or not tutor.courses:
        return set()
    course_ids = [c.id for c in tutor.courses]
    enrolled_ids = [r[0] for r in db.session.query(student_courses.c.student_id).filter(
        student_courses.c.course_id.in_(course_ids)).distinct().all()]
    if not enrolled_ids:
        return set()
    return {r[0] for r in db.session.query(Student.id).filter(
        Student.id.in_(enrolled_ids), Student.status == 'Active').all()}


def _scope_today_attendance(today, scope_ids):
    if not scope_ids:
        return 0
    return db.session.query(db.func.count(Attendance.id)).filter(
        Attendance.date == today, Attendance.person_type == 'student',
        Attendance.person_id.in_(scope_ids)).scalar() or 0


def _scope_attendance_avg(today, scope_ids):
    if not scope_ids:
        return None
    fourteen_days_ago = today - timedelta(days=14)
    att_counts = db.session.query(
        func.count(Attendance.id).label('total'),
        func.sum(case((Attendance.status == 'Present', 1), else_=0)).label('present')
    ).filter(
        Attendance.date >= fourteen_days_ago, Attendance.person_type == 'student',
        Attendance.person_id.in_(scope_ids)
    ).first()
    total = att_counts.total or 0
    present = att_counts.present or 0
    return int(present * 100 / total) if total else None


def _scope_low_attendance(today, scope_ids):
    if not scope_ids:
        return 0
    fourteen_days_ago = today - timedelta(days=14)
    att_stats = db.session.query(
        Attendance.person_id,
        func.count(Attendance.id).label('total'),
        func.sum(case((Attendance.status == 'Present', 1), else_=0)).label('present')
    ).filter(
        Attendance.person_type == 'student', Attendance.person_id.in_(scope_ids),
        Attendance.date >= fourteen_days_ago
    ).group_by(Attendance.person_id).all()
    return sum(1 for r in att_stats if r.total >= 3 and (r.present * 100.0 / r.total) < 75)


@dashboard_bp.route('/')
@login_required
def dashboard():
    today = date.today()
    stats = _safe('stats', get_dashboard_stats, _empty_stats())
    today_fees, today_attendance = _safe(
        'today_figures', lambda: _today_figures(today), (0.0, 0))

    if current_user.role == 'Staff':
        stats['monthly_fees_collected'] = 0.0
        recent_enquiries = []
        recent_fees = []
        chart_months = []
        chart_data = []
        pending_leaves_count, approved_leaves_count = _safe(
            'staff_leaves', lambda: _staff_leave_counts(current_user), (0, 0))
        stats['pending_leaves_count'] = pending_leaves_count
        stats['approved_leaves_count'] = approved_leaves_count
        stats['leave_days_used_month'] = _safe(
            'staff_leave_days', lambda: _staff_leave_days_this_month(current_user.id), 0)
        # Attendance figures are scoped to the tutor's own students; the
        # global defaults from _compute_stats/_today_figures must not leak.
        scope = _safe('staff_scope', _staff_student_scope, set()) or set()
        today_attendance = _safe(
            'staff_today_attendance', lambda: _scope_today_attendance(today, scope), 0)
        stats['avg_student_attendance'] = _safe(
            'staff_attendance_avg', lambda: _scope_attendance_avg(today, scope), None)
        stats['low_attendance_count'] = _safe(
            'staff_low_attendance', lambda: _scope_low_attendance(today, scope), 0)
        top_courses = []
        due_students = []
        total_outstanding = 0.0
        dues_ageing = {'over_90': 0.0, 'over_30': 0.0, 'recent': 0.0}
        capacity_courses = []
        overflow_capacity = 0
        birthdays_today = []
        anniversaries_today = []
        # Dynamic data for the "Your Access" card replacement (item 15)
        def _staff_today_info():
            tutor = Tutor.query.filter_by(email=current_user.email).first()
            exams = []
            att_done = today_attendance > 0
            if tutor:
                course_ids = [c.id for c in tutor.courses]
                exams = [{'title': e.title, 'course': e.course.name if e.course else ''}
                         for e in Exam.query.filter(Exam.exam_date == today,
                                                    Exam.course_id.in_(course_ids)).all()]
            return exams, att_done
        staff_today_exams, staff_attendance_done = _safe('staff_today_info', _staff_today_info, ([], False))
    else:
        recent_enquiries, recent_fees = _safe('recent_lists', _recent_lists, ([], []))
        chart_months, chart_data = _safe(
            'fee_chart', lambda: _fee_chart(today), ([], []))
        top_courses = _safe('top_courses', _top_courses, [])
        due_students, total_outstanding, dues_ageing = _safe(
            'fee_dues', _fee_dues, ([], 0.0, {'over_90': 0.0, 'over_30': 0.0, 'recent': 0.0}))
        capacity_courses, overflow_capacity = _safe('capacity', _capacity, ([], 0))
        birthdays_today, anniversaries_today = _safe(
            'celebrations', lambda: _celebrations(today), ([], []))
        stats['admin_pending_leaves'] = _safe(
            'admin_pending_leaves',
            lambda: LeaveRequest.query.filter_by(status='Pending').count(), 0)
        staff_today_exams = []
        staff_attendance_done = False

    return render_template('dashboard.html',
        stats=stats, recent_enquiries=recent_enquiries,
        recent_fees=recent_fees, chart_months=chart_months, chart_data=chart_data,
        top_courses=top_courses,
        due_students=due_students, total_outstanding=total_outstanding, dues_ageing=dues_ageing,
        capacity_courses=capacity_courses, overflow_capacity=overflow_capacity,
        birthdays_today=birthdays_today, anniversaries_today=anniversaries_today,
        today=today, today_fees=float(today_fees), today_attendance=int(today_attendance),
        staff_today_exams=staff_today_exams, staff_attendance_done=staff_attendance_done,
        account_balances=_safe(
            'account_balances',
            lambda: (compute_account_summary() if current_user.role == 'Admin' else []),
            []))

@dashboard_bp.route('/api/dashboard/fee-chart')
@login_required
def api_fee_chart():
    if current_user.role == 'Staff':
        return jsonify({"months": [], "data": []})
    months = request.args.get('months', 6, type=int)
    months_labels, data_points = _safe('fee_chart', lambda: _fee_chart(date.today(), months=months), ([], []))
    return jsonify({"months": months_labels, "data": data_points})


@dashboard_bp.route('/api/dashboard/ai-insights')
@login_required
def api_dashboard_insights():
    if current_user.role == 'Staff':
        return jsonify({"summary": "Staff dashboard loaded. AI advisor reports are hidden for Staff accounts.", "insights": []})
    stats = get_dashboard_stats()
    try:
        insights = current_app.ai_engine.generate_institute_insights(stats)
        if isinstance(insights, dict):
            insights.setdefault('generated_at', datetime.utcnow().isoformat() + 'Z')
            insights.setdefault('data_period', 'Current dashboard snapshot')
        return jsonify(insights)
    except Exception:
        current_app.logger.exception('Dashboard AI insights failed')
        return jsonify({'summary': 'AI insights are temporarily unavailable.', 'insights': [], 'degraded': True}), 200

@dashboard_bp.route('/api/dashboard/predictive-analytics')
@login_required
def api_predictive_analytics():
    if current_user.role == 'Staff':
        return jsonify({"summary": "Staff dashboard loaded. Predictive analytics are hidden for Staff accounts.", "predictions": []})
    stats = get_dashboard_stats()
    try:
        predictive_data = current_app.ai_engine.generate_predictive_analytics(stats)
        if isinstance(predictive_data, dict):
            predictive_data.setdefault('generated_at', datetime.utcnow().isoformat() + 'Z')
            predictive_data.setdefault('data_period', 'Current dashboard snapshot')
        return jsonify(predictive_data)

@dashboard_bp.route('/dashboard/export')
@login_required
def dashboard_export():
    """Export the role-scoped dashboard headline metrics as CSV."""
    import csv
    from io import StringIO
    output = StringIO()
    writer = csv.writer(output)
    stats = get_dashboard_stats()
    writer.writerow(['Metric', 'Value'])
    labels = {'active_students': 'Active students', 'courses': 'Courses', 'tutors': 'Staff',
              'enquiries': 'Enquiries', 'unresolved_enquiries': 'Unresolved enquiries',
              'monthly_fees_collected': 'Monthly fees collected',
              'avg_student_attendance': 'Average attendance', 'low_attendance_count': 'Low attendance'}
    for key, label in labels.items():
        writer.writerow([label, stats.get(key, '')])
    response = current_app.response_class(output.getvalue(), mimetype='text/csv')
    response.headers['Content-Disposition'] = 'attachment; filename=dashboard-metrics.csv'
    return response
    except Exception:
        current_app.logger.exception('Dashboard predictive analytics failed')
        return jsonify({'summary': 'Predictive analytics are temporarily unavailable.', 'predictions': [], 'degraded': True}), 200

@dashboard_bp.route('/api/dashboard/todays-activities')
@login_required
def api_todays_activities():
    if current_user.role == 'Staff':
        # Staff-specific activities
        tutor = Tutor.query.filter_by(email=current_user.email).first()
        if tutor:
            course_ids = [c.id for c in tutor.courses]
            student_subquery = db.session.query(student_courses.c.student_id).filter(
                student_courses.c.course_id.in_(course_ids)
            ).distinct()
            students = Student.query.filter(Student.id.in_(student_subquery), Student.status == 'Active').all()
            student_ids = [s.id for s in students]
            
            today = date.today()

            # Staff's students with low attendance
            fourteen_days_ago = today - timedelta(days=14)
            att_stats = db.session.query(
                Attendance.person_id,
                func.count(Attendance.id).label('total'),
                func.sum(case((Attendance.status == 'Present', 1), else_=0)).label('present')
            ).filter(
                Attendance.person_type == 'student',
                Attendance.person_id.in_(student_ids),
                Attendance.date >= fourteen_days_ago
            ).group_by(Attendance.person_id).all()
            low_attendance_students = [s.person_id for s in att_stats if s.total >= 3 and (s.present * 100.0 / s.total) < 75]
            
            # Staff's students with real fee dues (GST-inclusive balance > 0)
            fee_due_students = sum(
                1 for r in _fee_due_rows(student_ids) if r['balance'] > 0)
            
            # Staff's pending leaves
            pending_leaves = LeaveRequest.query.filter_by(user_id=current_user.id, status='Pending').count()
            
            # Today's exams for staff's courses
            today_exams_list = Exam.query.filter(Exam.exam_date == today, Exam.course_id.in_(course_ids)).all()
            today_exams = [f'{e.title}' for e in today_exams_list]
            
            data = {
                'low_attendance_count': len(low_attendance_students),
                'fee_due_count': fee_due_students,
                'pending_leaves': pending_leaves,
                'today_exams': today_exams,
                'my_students_count': len(students),
                'my_courses_count': len(course_ids),
            }

            # Check if today's attendance has already been marked for any student
            today_attendance_count = db.session.query(db.func.count(Attendance.id)).filter(
                Attendance.date == today, Attendance.person_type == 'student',
                Attendance.person_id.in_(student_ids) if student_ids else db.false()
            ).scalar() or 0 if student_ids else 0
            attendance_done = today_attendance_count > 0
            attendance_progress = min(100, int(today_attendance_count / len(students) * 100)) if students else 0

            # Staff tasks with full renderer fields: priority, progress, icon, detail
            tasks = [
                {
                    'title': 'Mark Attendance',
                    'detail': f'{today_attendance_count}/{len(students)} students marked today',
                    'priority': 'high' if not attendance_done else 'low',
                    'progress': attendance_progress,
                    'icon': 'calendar2-check-fill',
                    'action_label': 'Mark attendance',
                    'action_url': url_for('attendance.attendance'),
                },
                {
                    'title': 'Leave Requests',
                    'detail': f'{pending_leaves} pending approval' if pending_leaves else 'No pending requests',
                    'priority': 'medium' if pending_leaves else 'low',
                    'progress': 100 if not pending_leaves else 0,
                    'icon': 'calendar-range-fill',
                    'action_label': 'View leaves',
                    'action_url': url_for('leaves.leaves'),
                },
            ]
            if low_attendance_students:
                tasks.append({
                    'title': 'Low Attendance Follow-up',
                    'detail': f'{len(low_attendance_students)} student(s) below 75% in last 14 days',
                    'priority': 'high',
                    'progress': 0,
                    'icon': 'exclamation-triangle-fill',
                    'action_label': 'View students',
                    'action_url': url_for('students.list'),
                })
            if fee_due_students > 0:
                tasks.append({
                    'title': 'Fee Follow-up',
                    'detail': f'{fee_due_students} student(s) with outstanding fees',
                    'priority': 'medium',
                    'progress': 0,
                    'icon': 'cash-stack',
                    'action_label': 'View fees',
                    'action_url': url_for('fees.list'),
                })
            if today_exams:
                tasks.append({
                    'title': 'Exam Today',
                    'detail': ', '.join(today_exams),
                    'priority': 'high',
                    'progress': 0,
                    'icon': 'mortarboard-fill',
                    'action_label': 'View exams',
                    'action_url': url_for('exams.exam_list'),
                })

            # Custom tasks assigned to staff (Item 14)
            assigned_tasks = Task.query.filter_by(tutor_id=tutor.id).filter(Task.status.in_(['Pending', 'In Progress'])).order_by(Task.due_date.asc().nullslast()).all()
            for at in assigned_tasks:
                is_overdue = at.due_date and at.due_date < today
                tasks.append({
                    'title': at.title,
                    'detail': (f'Due: {at.due_date.strftime("%d %b")} · ' if at.due_date else '') + (at.description or at.notes or 'Assigned task'),
                    'priority': 'high' if (is_overdue or at.priority == 'High') else ('medium' if at.priority == 'Medium' else 'low'),
                    'progress': 50 if at.status == 'In Progress' else 0,
                    'icon': 'check2-square',
                    'action_label': 'View task',
                    'action_url': url_for('tasks.list_tasks'),
                })

            return jsonify({'tasks': tasks, 'meta': data})
        else:
            return jsonify({'tasks': [], 'meta': {}})
    
    # Admin activities (original logic)
    today = date.today()

    stale_cutoff = datetime.utcnow() - timedelta(days=3)
    stale_enquiries = Enquiry.query.filter(
        Enquiry.status.in_(['New', 'Contacted']),
        db.func.coalesce(Enquiry.last_contacted_at, Enquiry.created_at) < stale_cutoff
    ).count()

    new_enquiries_today = Enquiry.query.filter(
        db.cast(Enquiry.created_at, db.Date) == today
    ).count()

    fee_rows = _fee_due_rows()
    fee_due_students = sum(1 for r in fee_rows if r['balance'] > 0)
    # Ageing context for the fees-follow-up task: how many dues have crossed
    # 90 days and how long the oldest has run (0 when nothing is owed).
    due_with_age = [(r['days_due'] or 0) for r in fee_rows if r['balance'] > 0]
    fee_due_aged_critical = sum(1 for a in due_with_age if a > 90)
    fee_due_max_age = max(due_with_age) if due_with_age else 0

    low_attendance_count = get_dashboard_stats().get('low_attendance_count', 0)

    pending_leaves = LeaveRequest.query.filter_by(status='Pending').count()

    today_exams_list = Exam.query.filter(Exam.exam_date == today).all()
    today_exams = [f'{e.title}' for e in today_exams_list]

    data = {
        'stale_enquiries': stale_enquiries,
        'fee_due_count': fee_due_students,
        'low_attendance_count': low_attendance_count,
        'pending_leaves': pending_leaves,
        'today_exams': today_exams,
        'new_enquiries_today': new_enquiries_today,
        'fee_due_aged_critical': fee_due_aged_critical,
        'fee_due_max_age': fee_due_max_age,
    }
    try:
        tasks = current_app.ai_engine.generate_todays_tasks(data)
    except Exception:
        current_app.logger.exception('Dashboard todays-task generation failed')
        tasks = []

    route_map = {
        'view pipeline': 'enquiries.kanban',
        'view fees': 'fees.list',
        'view leaves': 'leaves.leaves',
        'view attendance': 'attendance.attendance',
        'view exams': 'exams.exam_list',
        'view enquiries': 'enquiries.list',
        'check now': 'enquiries.kanban',
    }

    for task in tasks:
        label = (task.get('action_label') or '').lower()
        matched = False
        for key, route in route_map.items():
            if key in label:
                task['action_url'] = url_for(route)
                matched = True
                break
        if not matched:
            task.pop('action_url', None)

    # Custom tasks assigned to staff (Item 14 for Admin)
    admin_assigned_tasks = Task.query.filter(Task.status.in_(['Pending', 'In Progress'])).order_by(Task.due_date.asc().nullslast()).limit(3).all()
    for at in admin_assigned_tasks:
        is_overdue = at.due_date and at.due_date < today
        tasks.append({
            'title': f'{at.title} ({at.tutor.name if at.tutor else "Staff"})',
            'detail': (f'Due: {at.due_date.strftime("%d %b")} · ' if at.due_date else '') + (at.description or at.notes or 'Assigned task'),
            'priority': 'high' if (is_overdue or at.priority == 'High') else ('medium' if at.priority == 'Medium' else 'low'),
            'progress': 50 if at.status == 'In Progress' else 0,
            'icon': 'check2-square',
            'action_label': 'Manage Tasks',
            'action_url': url_for('tasks.list_tasks'),
        })

    return jsonify({'tasks': tasks, 'meta': data})
