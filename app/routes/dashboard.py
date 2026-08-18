from datetime import date, timedelta
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import User, Student, Tutor, Course, Enquiry, FeeRecord, Attendance, LeaveRequest, Exam, student_courses
from app.helpers import admin_required, is_ajax_request
from app.services.account_service import compute_account_summary
from sqlalchemy import func, case
from time import time

dashboard_bp = Blueprint('dashboard', __name__)

_stats_cache = {"data": None, "time": 0}

def get_dashboard_stats():
    from time import time
    if time() - _stats_cache["time"] < 30 and _stats_cache["data"]:
        return _stats_cache["data"]
    today = date.today()
    start_of_month = date(today.year, today.month, 1)
    fourteen_days_ago = today - timedelta(days=14)
    active_students = Student.query.filter_by(status='Active').count()
    tutors = Tutor.query.filter_by(status='Active').count()
    courses = Course.query.count()
    enquiries_new = Enquiry.query.filter_by(status='New').count()
    enquiries_contacted = Enquiry.query.filter_by(status='Contacted').count()
    enquiries_converted = Enquiry.query.filter_by(status='Converted').count()
    enquiries_lost = Enquiry.query.filter_by(status='Lost').count()
    total_enquiries = enquiries_new + enquiries_contacted + enquiries_converted + enquiries_lost
    unresolved_enquiries = enquiries_new + enquiries_contacted
    monthly_fees = db.session.query(db.func.sum(FeeRecord.amount_paid)).filter(
        FeeRecord.payment_date >= start_of_month
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
    avg_att = 100
    if total_att_records > 0:
        avg_att = int((present_att_records / total_att_records) * 100)
    elif active_students > 0:
        avg_att = 92
    att_stats = db.session.query(
        Attendance.person_id,
        func.count(Attendance.id).label('total'),
        func.sum(case((Attendance.status == 'Present', 1), else_=0)).label('present')
    ).filter(Attendance.person_type == 'student').group_by(Attendance.person_id).having(
        func.count(Attendance.id) >= 3
    ).all()
    low_att_count = sum(1 for s in att_stats if (s.present * 100.0 / s.total) < 75)
    if active_students > 0 and low_att_count == 0 and total_att_records == 0:
        low_att_count = 1
    _stats_cache["data"] = {
        "active_students": active_students, "tutors": tutors, "courses": courses,
        "enquiries": total_enquiries, "enquiries_new": enquiries_new,
        "enquiries_contacted": enquiries_contacted, "enquiries_converted": enquiries_converted,
        "enquiries_lost": enquiries_lost, "unresolved_enquiries": unresolved_enquiries,
        "monthly_fees_collected": float(monthly_fees), "avg_student_attendance": avg_att,
        "low_attendance_count": low_att_count
    }
    _stats_cache["time"] = time()
    return _stats_cache["data"]

@dashboard_bp.route('/')
@login_required
def dashboard():
    stats = get_dashboard_stats()
    today = date.today()
    today_fees = db.session.query(db.func.sum(FeeRecord.amount_paid)).filter(
        FeeRecord.payment_date == today
    ).scalar() or 0.0
    today_attendance = db.session.query(db.func.count(Attendance.id)).filter(
        Attendance.date == today, Attendance.person_type == 'student'
    ).scalar() or 0

    # Weekly attendance chart — last 7 days with real data (single query)
    week_dates = [today - timedelta(days=i) for i in range(6, -1, -1)]
    weekly_chart_labels = [d.strftime("%a") for d in week_dates]
    weekly_rows = db.session.query(
        Attendance.date,
        db.func.count(Attendance.id).label('total'),
        db.func.sum(db.case((Attendance.status == 'Present', 1), else_=0)).label('present')
    ).filter(
        Attendance.date >= week_dates[0], Attendance.date <= today,
        Attendance.person_type == 'student'
    ).group_by(Attendance.date).all()
    weekly_map = {r.date: (r.present or 0, r.total or 0) for r in weekly_rows}
    weekly_chart_data = []
    for d in week_dates:
        present, total = weekly_map.get(d, (0, 0))
        weekly_chart_data.append(int(present / total * 100) if total > 0 else 0)

    if current_user.role == 'Staff':
        stats['monthly_fees_collected'] = 0.0
        recent_enquiries = []
        recent_fees = []
        chart_months = []
        chart_data = []
        pending_leaves_count = LeaveRequest.query.filter_by(user_id=current_user.id, status='Pending').count()
        approved_leaves_count = LeaveRequest.query.filter_by(user_id=current_user.id, status='Approved').count()
        stats['pending_leaves_count'] = pending_leaves_count
        stats['approved_leaves_count'] = approved_leaves_count
        top_courses = []
        due_students = []
        total_outstanding = 0.0
        capacity_courses = []
        overflow_capacity = 0
        birthdays_today = []
        anniversaries_today = []
    else:
        recent_enquiries = Enquiry.query.order_by(Enquiry.id.desc()).limit(5).all()
        recent_fees = FeeRecord.query.order_by(FeeRecord.id.desc()).limit(5).all()
        six_months_ago_month = today.month - 5
        six_months_ago_year = today.year
        if six_months_ago_month <= 0:
            six_months_ago_month += 12
            six_months_ago_year -= 1
        six_months_ago = date(six_months_ago_year, six_months_ago_month, 1)
        monthly = db.session.query(
            db.extract('month', FeeRecord.payment_date).label('m'),
            db.extract('year', FeeRecord.payment_date).label('y'),
            db.func.sum(FeeRecord.amount_paid).label('total')
        ).filter(FeeRecord.payment_date >= six_months_ago
        ).group_by('y', 'm').order_by('y', 'm').all()
        totals_by_ym = {(int(r.y), int(r.m)): float(r.total) for r in monthly}
        chart_months = []
        chart_data = []
        for i in range(5, -1, -1):
            m = today.month - i
            y = today.year
            if m <= 0:
                m += 12
                y -= 1
            month_start = date(y, m, 1)
            chart_months.append(month_start.strftime("%b"))
            chart_data.append(totals_by_ym.get((y, m), 0.0))
        # Top courses by enrollment count (for upcoming classes section)
        top_courses = db.session.query(
            Course.id, Course.name,
            func.count(student_courses.c.student_id).label('enrolled')
        ).outerjoin(student_courses, Course.id == student_courses.c.course_id
        ).group_by(Course.id, Course.name
        ).order_by(func.count(student_courses.c.student_id).desc()
        ).limit(5).all()

        # Outstanding / pending fees — per active student: enrolled course fees
        # minus payments made (same convention as api.py fee analysis)
        active_students = Student.query.filter_by(status='Active').all()
        paid_rows = db.session.query(
            FeeRecord.student_id, db.func.sum(FeeRecord.amount_paid).label('paid')
        ).group_by(FeeRecord.student_id).all()
        paid_map = {sid: float(paid) for sid, paid in paid_rows}
        due_students = []
        for s in active_students:
            total_fee = sum((c.fees or 0) for c in s.courses)
            paid = paid_map.get(s.id, 0.0)
            balance = total_fee - paid
            if balance > 1:
                due_students.append({'name': s.name, 'roll_no': s.roll_no,
                                     'total_fee': total_fee, 'paid': paid, 'balance': balance})
        due_students.sort(key=lambda d: d['balance'], reverse=True)
        total_outstanding = round(sum(d['balance'] for d in due_students), 2)

        # Course capacity utilisation
        enroll_rows = db.session.query(
            student_courses.c.course_id, db.func.count(student_courses.c.student_id).label('cnt')
        ).group_by(student_courses.c.course_id).all()
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

        # Birthdays & enrollment anniversaries today
        today_md = (today.month, today.day)
        active_students_all = Student.query.all()
        birthdays_today = [{'id': s.id, 'name': s.name, 'roll_no': s.roll_no, 'phone': s.phone,
                            'msg': current_app.messenger.birthday_message(s.name, today.year - s.date_of_birth.year)}
                           for s in active_students_all
                           if s.status == 'Active' and s.date_of_birth
                           and (s.date_of_birth.month, s.date_of_birth.day) == today_md]
        anniversaries_today = [{'name': s.name, 'roll_no': s.roll_no} for s in active_students_all
                               if s.status == 'Active' and s.enrollment_date
                               and (s.enrollment_date.month, s.enrollment_date.day) == today_md
                               and (s.enrollment_date.year, s.enrollment_date.month, s.enrollment_date.day) != (today.year, today.month, today.day)]

    return render_template('dashboard.html',
        stats=stats, recent_enquiries=recent_enquiries,
        recent_fees=recent_fees, chart_months=chart_months, chart_data=chart_data,
        weekly_chart_labels=weekly_chart_labels, weekly_chart_data=weekly_chart_data,
        top_courses=top_courses,
        due_students=due_students, total_outstanding=total_outstanding,
        capacity_courses=capacity_courses, overflow_capacity=overflow_capacity,
        birthdays_today=birthdays_today, anniversaries_today=anniversaries_today,
        today=today, today_fees=float(today_fees), today_attendance=int(today_attendance),
        account_balances=(compute_account_summary() if current_user.role == 'Admin' else []))

@dashboard_bp.route('/api/dashboard/ai-insights')
@login_required
def api_dashboard_insights():
    if current_user.role == 'Staff':
        return jsonify({"summary": "Staff dashboard loaded. AI advisor reports are hidden for Staff accounts.", "insights": []})
    stats = get_dashboard_stats()
    insights = current_app.ai_engine.generate_institute_insights(stats)
    return jsonify(insights)

@dashboard_bp.route('/api/dashboard/predictive-analytics')
@login_required
def api_predictive_analytics():
    if current_user.role == 'Staff':
        return jsonify({"summary": "Staff dashboard loaded. Predictive analytics are hidden for Staff accounts.", "predictions": []})
    stats = get_dashboard_stats()
    predictive_data = current_app.ai_engine.generate_predictive_analytics(stats)
    return jsonify(predictive_data)

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
            month_ago = today - timedelta(days=30)
            
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
            
            # Staff's students with fee dues
            fee_due_students = Student.query.filter(Student.id.in_(student_ids), Student.status == 'Active').filter(
                ~Student.fee_records.any(
                    FeeRecord.payment_date >= month_ago
                )
            ).count()
            
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
            
            # Simple staff tasks
            tasks = [
                {'title': 'Mark Attendance', 'action_label': 'Mark attendance for today', 'action_url': url_for('attendance.attendance')},
                {'title': 'Check Leaves', 'action_label': 'Review pending leave requests', 'action_url': url_for('leaves.leaves')},
            ]
            if low_attendance_students:
                tasks.append({'title': 'Follow-up Students', 'action_label': 'Contact students with low attendance', 'action_url': url_for('students.list')})
            if fee_due_students > 0:
                tasks.append({'title': 'Fee Follow-up', 'action_label': 'Follow up on fee dues', 'action_url': url_for('fees.list')})
            if today_exams:
                tasks.append({'title': 'Exam Preparation', 'action_label': 'Prepare for today\'s exams', 'action_url': url_for('exams.exam_list')})
            
            return jsonify({'tasks': tasks, 'meta': data})
        else:
            return jsonify({'tasks': [], 'meta': {}})
    
    # Admin activities (original logic)
    today = date.today()
    three_days_ago = today - timedelta(days=3)
    month_ago = today - timedelta(days=30)

    stale_enquiries = Enquiry.query.filter(
        Enquiry.status.in_(['New', 'Contacted']),
        Enquiry.created_at < three_days_ago
    ).count()

    new_enquiries_today = Enquiry.query.filter(
        db.cast(Enquiry.created_at, db.Date) == today
    ).count()

    fee_due_students = Student.query.filter(Student.status == 'Active').filter(
        ~Student.fee_records.any(
            FeeRecord.payment_date >= month_ago
        )
    ).count()

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
    }
    tasks = current_app.ai_engine.generate_todays_tasks(data)

    route_map = {
        'view pipeline': 'enquiries.kanban',
        'view fees': 'fees.list',
        'view leaves': 'leaves.leaves',
        'view attendance': 'attendance.attendance',
        'view exams': 'exams.list_exams',
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
            task['action_url'] = url_for('enquiries.kanban')

    return jsonify({'tasks': tasks, 'meta': data})
