from datetime import date
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Student, Tutor, Course, Enquiry, FeeRecord, Attendance, Expense, ExpenseCategory
from app.helpers import admin_required
from sqlalchemy.orm import subqueryload

api_bp = Blueprint('api', __name__)

@api_bp.route('/api/enquiry/ai-followup/<int:enquiry_id>')
@login_required
@admin_required
def api_enquiry_followup(enquiry_id):
    enquiry = Enquiry.query.get(enquiry_id)
    if not enquiry:
        return jsonify({"error": "Enquiry not found"}), 404
    course = Course.query.get(enquiry.course_id)
    course_name = course.name if course else "Selected Program"
    notes = enquiry.notes if enquiry.notes else "Interested in joining code batch."
    draft = current_app.ai_engine.generate_enquiry_followup(enquiry.student_name, course_name, enquiry.source, notes)
    return jsonify({"followup_draft": draft})

@api_bp.route('/api/fees/ai-analysis')
@login_required
@admin_required
def api_fee_analysis():
    all_records = FeeRecord.query.all()
    student_balances = []
    for student in Student.query.options(subqueryload(Student.courses), subqueryload(Student.fee_records)).all():
        total_course_fee = sum(c.fees for c in student.courses)
        total_paid = sum(r.amount_paid for r in student.fee_records)
        balance = total_course_fee - total_paid
        student_balances.append({"student": student, "total_fee": total_course_fee, "total_paid": total_paid, "balance": balance})
    analysis = current_app.ai_engine.analyze_fee_collection_patterns(all_records, student_balances)
    return jsonify(analysis)

@api_bp.route('/api/attendance/ai-analysis')
@login_required
@admin_required
def api_attendance_analysis():
    attendance_data = Attendance.query.filter_by(person_type='student').all()
    analysis = current_app.ai_engine.analyze_attendance_patterns(attendance_data)
    return jsonify(analysis)

@api_bp.route('/api/courses/<int:course_id>/ai-syllabus-optimization')
@login_required
@admin_required
def api_course_syllabus_optimization(course_id):
    course = Course.query.get_or_404(course_id)
    course_data = {'name': course.name, 'syllabus': course.syllabus, 'duration_weeks': course.duration_weeks, 'duration_unit': course.duration_unit, 'fees': course.fees}
    optimization = current_app.ai_engine.optimize_course_syllabus(course_data)
    return jsonify(optimization)

@api_bp.route('/api/students/<int:student_id>/ai-performance-insights')
@login_required
def api_student_performance_insights(student_id):
    student = Student.query.get_or_404(student_id)
    attendance_data = Attendance.query.filter_by(person_type='student', person_id=student_id).all()
    total_course_fee = sum(c.fees for c in student.courses)
    total_paid = sum(r.amount_paid for r in student.fee_records)
    student_data = {'name': student.name, 'total_fee': total_course_fee, 'total_paid': total_paid, 'courses': student.courses}
    insights = current_app.ai_engine.generate_student_performance_insights(student_data, attendance_data, None)
    return jsonify(insights)

@api_bp.route('/api/students/<int:student_id>/details')
@login_required
def api_student_details(student_id):
    student = Student.query.get_or_404(student_id)
    total_course_fee = sum(c.fees for c in student.courses)
    total_paid = sum(r.amount_paid for r in student.fee_records)
    attendance_records = Attendance.query.filter_by(person_type='student', person_id=student_id).all()
    total_days = len(attendance_records)
    days_present = sum(1 for r in attendance_records if r.status == 'Present')
    days_absent = sum(1 for r in attendance_records if r.status == 'Absent')
    days_late = sum(1 for r in attendance_records if r.status == 'Late')
    return jsonify({
        'id': student.id, 'name': student.name, 'email': student.email, 'phone': student.phone,
        'enrollment_date': student.enrollment_date.strftime('%d %b %Y'), 'status': student.status,
        'qr_code_uuid': student.qr_code_uuid,
        'courses': [{'id': c.id, 'name': c.name, 'code': c.code, 'fees': c.fees, 'duration': f'{c.duration_weeks} {c.duration_unit or "weeks"}'} for c in student.courses],
        'fees': {'total_course_fee': total_course_fee, 'total_paid': total_paid, 'pending': total_course_fee - total_paid},
        'attendance': {'total_days': total_days, 'present': days_present, 'absent': days_absent, 'late': days_late}
    })

@api_bp.route('/api/tutors/<int:tutor_id>/details')
@login_required
def api_tutor_details(tutor_id):
    tutor = Tutor.query.get_or_404(tutor_id)
    attendance_records = Attendance.query.filter_by(person_type='tutor', person_id=tutor_id).all()
    total_days = len(attendance_records)
    days_present = sum(1 for r in attendance_records if r.status == 'Present')
    days_absent = sum(1 for r in attendance_records if r.status == 'Absent')
    days_late = sum(1 for r in attendance_records if r.status == 'Late')
    salary_cat = ExpenseCategory.query.filter_by(name="Salary").first()
    salary_payments = Expense.query.filter(
        Expense.category_id == salary_cat.id, Expense.description.ilike(f'%{tutor.name}%')
    ).order_by(Expense.expense_date.desc()).all() if salary_cat else []
    total_salary_paid = sum(s.amount for s in salary_payments)
    return jsonify({
        'id': tutor.id, 'name': tutor.name, 'email': tutor.email, 'phone': tutor.phone,
        'specialization': tutor.specialization or 'N/A', 'status': tutor.status, 'qr_code_uuid': tutor.qr_code_uuid,
        'courses': [{'id': c.id, 'name': c.name, 'code': c.code, 'duration': f'{c.duration_weeks} {c.duration_unit or "weeks"}'} for c in tutor.courses],
        'attendance': {'total_days': total_days, 'present': days_present, 'absent': days_absent, 'late': days_late},
        'salary': {'total_paid': total_salary_paid, 'recent_payments': [{'date': s.expense_date.strftime('%d %b %Y'), 'amount': s.amount, 'description': s.description[:60]} for s in salary_payments[:10]]}
    })

@api_bp.route('/api/expenses/ai-optimization')
@login_required
@admin_required
def api_expense_optimization():
    current_month = date.today().month
    current_year = date.today().year
    expense_data = Expense.query.filter(
        db.extract('month', Expense.expense_date) == current_month,
        db.extract('year', Expense.expense_date) == current_year
    ).all()
    category_data = ExpenseCategory.query.all()
    optimization = current_app.ai_engine.generate_expense_optimization_insights(expense_data, category_data)
    return jsonify(optimization)

@api_bp.route('/api/search')
@login_required
def api_search():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify({'results': {'students': [], 'tutors': [], 'courses': [], 'enquiries': []}})
    like = f'%{q}%'
    results = {'students': [], 'tutors': [], 'courses': [], 'enquiries': []}
    for s in Student.query.filter(
        db.or_(Student.name.ilike(like), Student.email.ilike(like), Student.phone.ilike(like))
    ).limit(5).all():
        results['students'].append({'id': s.id, 'name': s.name, 'subtitle': s.email or s.phone, 'url': url_for('students.list'), 'badge': s.status})
    for t in Tutor.query.filter(
        db.or_(Tutor.name.ilike(like), Tutor.email.ilike(like), Tutor.phone.ilike(like))
    ).limit(5).all():
        results['tutors'].append({'id': t.id, 'name': t.name, 'subtitle': t.specialization or t.email, 'url': url_for('tutors.list'), 'badge': t.status})
    for c in Course.query.filter(
        db.or_(Course.name.ilike(like), Course.code.ilike(like))
    ).limit(5).all():
        results['courses'].append({'id': c.id, 'name': f'{c.code}: {c.name}', 'subtitle': f'Rs.{c.fees:,.0f}', 'url': url_for('courses.list'), 'badge': ''})
    for e in Enquiry.query.filter(
        db.or_(Enquiry.student_name.ilike(like), Enquiry.email.ilike(like), Enquiry.phone.ilike(like))
    ).limit(5).all():
        results['enquiries'].append({'id': e.id, 'name': e.student_name, 'subtitle': e.course.name if e.course else '', 'url': url_for('enquiries.list'), 'badge': e.status})
    return jsonify({'results': results})
