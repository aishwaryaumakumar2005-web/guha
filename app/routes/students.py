from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Student, Course, Tutor, student_courses
from app.helpers import admin_required, is_ajax_request
from app.forms import StudentForm
import tempfile

students_bp = Blueprint('students', __name__)

@students_bp.route('/students', methods=['GET', 'POST'])
@login_required
def list():
    # Handle POST (add student) - only for admin
    if request.method == 'POST':
        if current_user.role != 'Admin':
            if is_ajax_request():
                return jsonify({"success": False, "errors": ["Only admins can add students"]}), 403
            flash("Only admins can add students", 'danger')
            return redirect(url_for('students.list'))
        
        form = StudentForm(request.form)
        if not form.validate():
            if is_ajax_request():
                return jsonify({"success": False, "errors": form.error_messages}), 400
            for msg in form.error_messages:
                flash(msg, 'danger')
            return redirect(url_for('students.list'))
        name = form.data.get('name', '').strip()
        email = form.data.get('email', '').strip()
        phone = form.data.get('phone', '').strip()
        status = form.data.get('status', 'Active')
        selected_courses = request.form.getlist('courses')
        exists = Student.query.filter_by(email=email).first()
        if exists:
            message = f"Student with email '{email}' already exists!"
            if is_ajax_request():
                return jsonify({"success": False, "message": message}), 400
            flash(message, 'danger')
        else:
            new_student = Student(name=name, email=email, phone=phone, status=status)
            for c_id in selected_courses:
                course = Course.query.get(int(c_id))
                if course:
                    new_student.courses.append(course)
            db.session.add(new_student)
            db.session.commit()
            message = "Student enrolled successfully!"
            if is_ajax_request():
                return jsonify({"success": True, "message": message}), 201
            flash(message, "success")
        return redirect(url_for('students.list'))
    
    # GET request - filter students based on user role
    course_filter = request.args.get('course_id', type=int)
    if current_user.role == 'Staff':
        tutor = Tutor.query.filter_by(email=current_user.email).first()
        if tutor:
            course_ids = [c.id for c in tutor.courses]
            student_subquery = db.session.query(student_courses.c.student_id).filter(
                student_courses.c.course_id.in_(course_ids)
            ).distinct()
            all_students = Student.query.filter(Student.id.in_(student_subquery)).all()
        else:
            all_students = []
    else:
        if course_filter:
            student_subquery = db.session.query(student_courses.c.student_id).filter(
                student_courses.c.course_id == course_filter
            ).distinct()
            all_students = Student.query.filter(Student.id.in_(student_subquery)).order_by(Student.id).all()
        else:
            all_students = Student.query.order_by(Student.id).all()
    
    all_courses = Course.query.all()
    return render_template('students.html', students=all_students, courses=all_courses, is_staff=(current_user.role == 'Staff'), selected_course_id=course_filter)

@students_bp.route('/students/edit/<int:id>', methods=['POST'])
@login_required
@admin_required
def edit(id):
    student = Student.query.get_or_404(id)
    form = StudentForm(request.form)
    if not form.validate():
        if is_ajax_request():
            return jsonify({"success": False, "errors": form.error_messages}), 400
        for msg in form.error_messages:
            flash(msg, 'danger')
        return redirect(url_for('students.list'))
    new_email = form.data.get('email', '').strip()
    if new_email != student.email:
        exists = Student.query.filter_by(email=new_email).first()
        if exists:
            flash(f"Email '{new_email}' is already in use by another student.", 'danger')
            return redirect(url_for('students.list'))
    student.name = form.data.get('name', '').strip()
    student.email = new_email
    student.phone = form.data.get('phone', '').strip()
    student.status = form.data.get('status', 'Active')
    student.courses = []
    selected_courses = request.form.getlist('courses')
    for c_id in selected_courses:
        course = Course.query.get(int(c_id))
        if course:
            student.courses.append(course)
    db.session.commit()
    message = "Student details updated!"
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('students.list'))

@students_bp.route('/students/delete/<int:id>')
@login_required
@admin_required
def delete(id):
    student = Student.query.get_or_404(id)
    db.session.delete(student)
    db.session.commit()
    message = "Student record deleted!"
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('students.list'))

@students_bp.route('/api/students/import-excel', methods=['POST'])
@login_required
@admin_required
def import_excel():
    from werkzeug.utils import secure_filename
    from openpyxl import load_workbook
    import os
    if 'excel_file' not in request.files:
        return jsonify({"success": False, "errors": ["No file uploaded"]}), 400
    file = request.files['excel_file']
    if file.filename == '':
        return jsonify({"success": False, "errors": ["No file selected"]}), 400
    if not file.filename.endswith(('.xlsx', '.xls')):
        return jsonify({"success": False, "errors": ["Invalid file format. Please upload .xlsx or .xls file"]}), 400
    ai_validation = request.form.get('ai_validation', 'true').lower() == 'true'
    auto_course_mapping = request.form.get('auto_course_mapping', 'false').lower() == 'true'
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_file:
            file.save(tmp_file.name)
            tmp_file_path = tmp_file.name
        workbook = load_workbook(tmp_file_path)
        sheet = workbook.active
        headers = []
        for cell in sheet[1]:
            headers.append(cell.value)
        headers = [str(h).strip().lower() if h else '' for h in headers]
        column_map = {}
        for idx, header in enumerate(headers):
            if 'name' in header:
                column_map['name'] = idx
            elif 'email' in header:
                column_map['email'] = idx
            elif 'phone' in header or 'mobile' in header:
                column_map['phone'] = idx
            elif 'status' in header:
                column_map['status'] = idx
            elif 'course' in header:
                column_map['courses'] = idx
        required_columns = ['name', 'email', 'phone']
        missing_columns = [col for col in required_columns if col not in column_map]
        if missing_columns:
            return jsonify({
                "success": False,
                "errors": [f"Missing required columns: {', '.join(missing_columns)}"],
                "suggestions": ["Ensure your Excel file has columns: Name, Email, Phone"]
            }), 400
        students_data = []
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if not any(row):
                continue
            student_data = {
                'name': str(row[column_map['name']]).strip() if column_map['name'] < len(row) else '',
                'email': str(row[column_map['email']]).strip() if column_map['email'] < len(row) else '',
                'phone': str(row[column_map['phone']]).strip() if column_map['phone'] < len(row) else '',
                'status': str(row[column_map['status']]).strip() if 'status' in column_map and column_map['status'] < len(row) else 'Active',
                'courses': str(row[column_map['courses']]).strip() if 'courses' in column_map and column_map['courses'] < len(row) else ''
            }
            students_data.append(student_data)
        os.unlink(tmp_file_path)
        if not students_data:
            return jsonify({"success": False, "errors": ["No data found in Excel file"]}), 400
        ai_engine = current_app.ai_engine
        if ai_validation:
            validation_result = ai_engine.validate_student_data(students_data)
        else:
            validation_result = {"valid": True, "errors": [], "warnings": [], "suggestions": [], "enriched_data": students_data}
        if not validation_result["valid"]:
            return jsonify({
                "success": False, "errors": validation_result.get("errors", []),
                "warnings": validation_result.get("warnings", []),
                "suggestions": validation_result.get("suggestions", [])
            }), 400
        imported_count = 0
        skipped_count = 0
        all_courses = Course.query.all()
        all_courses_lower = {c.code.lower(): c for c in all_courses}
        existing_emails = set(email for (email,) in db.session.query(Student.email).all())
        for student_data in validation_result["enriched_data"]:
            if student_data['email'] in existing_emails:
                skipped_count += 1
                continue
            new_student = Student(
                name=student_data['name'], email=student_data['email'],
                phone=student_data['phone'], status=student_data.get('status', 'Active')
            )
            if student_data.get('courses'):
                course_codes = [c.strip() for c in student_data['courses'].split(',')]
                for code in course_codes:
                    course = all_courses_lower.get(code.lower())
                    if course:
                        new_student.courses.append(course)
            elif auto_course_mapping:
                suggested_courses = ai_engine.suggest_course_mapping(student_data, all_courses)
                for course_id in suggested_courses:
                    course = next((c for c in all_courses if c.id == course_id), None)
                    if course:
                        new_student.courses.append(course)
            db.session.add(new_student)
            existing_emails.add(student_data['email'])
            imported_count += 1
        db.session.commit()
        return jsonify({
            "success": True, "message": f"Successfully imported {imported_count} students. Skipped {skipped_count} duplicates.",
            "imported": imported_count, "skipped": skipped_count,
            "warnings": validation_result.get("warnings", [])
        }), 200
    except Exception as e:
        return jsonify({"success": False, "errors": [f"Error processing file: {str(e)}"]}), 500
