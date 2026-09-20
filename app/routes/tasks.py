from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Task, Tutor, User
from app.helpers import admin_required, is_ajax_request

tasks_bp = Blueprint('tasks', __name__)


@tasks_bp.route('/tasks', methods=['GET', 'POST'])
@login_required
def list_tasks():
    if request.method == 'POST':
        if current_user.role != 'Admin':
            flash('Only administrators can assign tasks.', 'danger')
            return redirect(url_for('tasks.list_tasks'))
        tutor_id = request.form.get('tutor_id', type=int)
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        due_date_str = request.form.get('due_date', '').strip()
        if not tutor_id:
            flash('Please select a tutor to assign the task to.', 'danger')
            return redirect(url_for('tasks.list_tasks'))
        tutor_obj = Tutor.query.get(tutor_id)
        if not tutor_obj:
            flash('Selected tutor was not found.', 'danger')
            return redirect(url_for('tasks.list_tasks'))
        if not title:
            flash('Task title is required.', 'danger')
            return redirect(url_for('tasks.list_tasks'))
        due_date = None
        if due_date_str:
            try:
                due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        task = Task(tutor_id=tutor_id, title=title, description=description,
                    assigned_by=current_user.id, due_date=due_date)
        db.session.add(task)
        db.session.commit()
        flash('Task assigned successfully!', 'success')
        return redirect(url_for('tasks.list_tasks'))

    tutor = None
    query = Task.query
    if current_user.role == 'Admin':
        pass
    else:
        tutor = Tutor.query.filter_by(email=current_user.email).first()
        if not tutor:
            query = query.filter(db.false())
        else:
            query = query.filter(Task.tutor_id == tutor.id)

    all_tasks = query.all()
    today = date.today()

    # KPI Statistics for the scoped user
    stats = {
        'total': len(all_tasks),
        'pending': sum(1 for t in all_tasks if t.status == 'Pending'),
        'in_progress': sum(1 for t in all_tasks if t.status == 'In Progress'),
        'completed': sum(1 for t in all_tasks if t.status == 'Completed'),
        'overdue': sum(1 for t in all_tasks if t.due_date and t.due_date < today and t.status != 'Completed')
    }

    # Filters
    selected_status = request.args.get('status', '').strip()
    selected_tutor_id = request.args.get('tutor_id', type=int)
    search_q = request.args.get('q', '').strip()

    if selected_status == 'Pending':
        query = query.filter(Task.status == 'Pending')
    elif selected_status == 'In Progress':
        query = query.filter(Task.status == 'In Progress')
    elif selected_status == 'Completed':
        query = query.filter(Task.status == 'Completed')
    elif selected_status == 'Overdue':
        query = query.filter(Task.due_date < today, Task.status != 'Completed')

    if selected_tutor_id and current_user.role == 'Admin':
        query = query.filter(Task.tutor_id == selected_tutor_id)

    if search_q:
        search_filter = f"%{search_q}%"
        query = query.filter(db.or_(
            Task.title.ilike(search_filter),
            Task.description.ilike(search_filter),
            Task.notes.ilike(search_filter)
        ))

    tasks = query.order_by(Task.created_at.desc()).all()
    tutors = Tutor.query.order_by(Tutor.name).all()

    return render_template('tasks.html',
                           tasks=tasks,
                           tutors=tutors,
                           today=today,
                           tutor=tutor,
                           stats=stats,
                           selected_status=selected_status,
                           selected_tutor_id=selected_tutor_id,
                           search_q=search_q)


@tasks_bp.route('/tasks/update-status/<int:id>', methods=['POST'])
@login_required
def update_status(id):
    task = Task.query.get_or_404(id)
    tutor = Tutor.query.filter_by(email=current_user.email).first()
    if current_user.role != 'Admin' and (not tutor or task.tutor_id != tutor.id):
        if is_ajax_request() or request.is_json:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        flash('You can only update your own tasks.', 'danger')
        return redirect(url_for('tasks.list_tasks'))
    
    if request.is_json:
        data = request.get_json() or {}
        status = (data.get('status') or '').strip()
        notes = (data.get('notes') or '').strip()
    else:
        status = request.form.get('status', '').strip()
        notes = request.form.get('notes', '').strip()

    if status not in ('Pending', 'In Progress', 'Completed'):
        if is_ajax_request() or request.is_json:
            return jsonify({'success': False, 'error': 'Invalid status'}), 400
        flash('Invalid status.', 'danger')
        return redirect(url_for('tasks.list_tasks'))
    task.status = status
    if notes:
        task.notes = notes
    if status == 'Completed':
        task.completed_date = datetime.utcnow()
    else:
        task.completed_date = None
    db.session.commit()

    if is_ajax_request() or request.is_json:
        return jsonify({'success': True, 'status': status, 'id': task.id, 'completed_date': task.completed_date.isoformat() if task.completed_date else None})

    flash(f'Task status updated to {status}.', 'success')
    return redirect(url_for('tasks.list_tasks'))


@tasks_bp.route('/tasks/edit/<int:id>', methods=['POST'])
@login_required
@admin_required
def edit_task(id):
    task = Task.query.get_or_404(id)
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    tutor_id = request.form.get('tutor_id', type=int)
    due_date_str = request.form.get('due_date', '').strip()
    status = request.form.get('status', '').strip()
    notes = request.form.get('notes', '').strip()
    if not title:
        flash('Task title is required.', 'danger')
        return redirect(url_for('tasks.list_tasks'))
    task.title = title
    task.description = description
    if tutor_id:
        if Tutor.query.get(tutor_id):
            task.tutor_id = tutor_id
    if due_date_str:
        try:
            task.due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    else:
        task.due_date = None
    if status in ('Pending', 'In Progress', 'Completed'):
        task.status = status
        if status == 'Completed':
            task.completed_date = datetime.utcnow()
        else:
            task.completed_date = None
    task.notes = notes
    db.session.commit()
    flash('Task updated successfully.', 'success')
    return redirect(url_for('tasks.list_tasks'))


@tasks_bp.route('/tasks/delete/<int:id>', methods=['POST', 'GET'])
@login_required
@admin_required
def delete_task(id):
    task = Task.query.get_or_404(id)
    db.session.delete(task)
    db.session.commit()
    flash('Task deleted successfully.', 'success')
    return redirect(url_for('tasks.list_tasks'))
