from datetime import datetime, date
import secrets
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, abort, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Task, TaskHistory, Tutor, User
from app.helpers import admin_required, is_ajax_request

tasks_bp = Blueprint('tasks', __name__)

STATUSES = ('Pending', 'In Progress', 'Blocked', 'Completed', 'Verified', 'Cancelled')


def _task_csrf_ok():
    """Use the project's session token convention when CSRF is enabled."""
    if not current_app.config.get('WTF_CSRF_ENABLED', False):
        return True
    token = request.form.get('task_csrf_token') or request.headers.get('X-CSRFToken')
    expected = session.get('task_csrf_token')
    return bool(token and expected and secrets.compare_digest(token, expected))


def _history(task, action, from_status=None, to_status=None, details=None):
    db.session.add(TaskHistory(task_id=task.id, user_id=current_user.id, action=action,
                               from_status=from_status, to_status=to_status, details=details))


@tasks_bp.route('/tasks', methods=['GET', 'POST'])
@login_required
def list_tasks():
    categories = ['General', 'Syllabus', 'Exam', 'Student Care', 'Admin']
    priorities = ['High', 'Medium', 'Low']
    statuses = list(STATUSES)
    if 'task_csrf_token' not in session:
        session['task_csrf_token'] = secrets.token_urlsafe(32)

    if request.method == 'POST':
        if not _task_csrf_ok():
            abort(400, description='Invalid task security token.')
        if current_user.role != 'Admin':
            flash('Only administrators can assign tasks.', 'danger')
            return redirect(url_for('tasks.list_tasks'))
        tutor_id = request.form.get('tutor_id', type=int)
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        due_date_str = request.form.get('due_date', '').strip()
        priority = request.form.get('priority', 'Medium').strip()
        category = request.form.get('category', 'General').strip()

        if priority not in priorities:
            priority = 'Medium'
        if category not in categories:
            category = 'General'

        if not tutor_id:
            flash('Please select a tutor to assign the task to.', 'danger')
            return redirect(url_for('tasks.list_tasks'))
        tutor_obj = Tutor.query.filter_by(id=tutor_id, status='Active').first()
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
                flash('Please enter a valid due date.', 'danger')
                return redirect(url_for('tasks.list_tasks'))
        task = Task(tutor_id=tutor_id, title=title, description=description,
                    assigned_by=current_user.id, due_date=due_date,
                    priority=priority, category=category)
        db.session.add(task)
        db.session.flush()
        _history(task, 'CREATED', to_status='Pending', details='Task assigned')
        db.session.commit()
        flash('Task assigned successfully!', 'success')
        return redirect(url_for('tasks.list_tasks'))

    tutor = None
    query = Task.query.filter(Task.archived_at.is_(None))
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
    selected_priority = request.args.get('priority', '').strip()
    selected_category = request.args.get('category', '').strip()
    search_q = request.args.get('q', '').strip()
    view_mode = request.args.get('view', 'table').strip().lower()
    if view_mode not in ('table', 'kanban'):
        view_mode = 'table'

    if selected_status in STATUSES:
        query = query.filter(Task.status == selected_status)
    elif selected_status == 'Pending':
        query = query.filter(Task.status == 'Pending')
    elif selected_status == 'In Progress':
        query = query.filter(Task.status == 'In Progress')
    elif selected_status == 'Completed':
        query = query.filter(Task.status == 'Completed')
    elif selected_status == 'Overdue':
        query = query.filter(Task.due_date < today, Task.status != 'Completed')

    if selected_priority and selected_priority in priorities:
        query = query.filter(Task.priority == selected_priority)

    if selected_category and selected_category in categories:
        query = query.filter(Task.category == selected_category)

    if selected_tutor_id and current_user.role == 'Admin':
        query = query.filter(Task.tutor_id == selected_tutor_id)

    if search_q:
        search_filter = f"%{search_q}%"
        query = query.filter(db.or_(
            Task.title.ilike(search_filter),
            Task.description.ilike(search_filter),
            Task.notes.ilike(search_filter)
        ))

    # Server-side pagination keeps large task lists responsive.
    page = max(request.args.get('page', 1, type=int) or 1, 1)
    per_page = min(max(request.args.get('per_page', 25, type=int) or 25, 10), 100)
    total_filtered = query.count()
    tasks = query.order_by(Task.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    tutors = Tutor.query.filter_by(status='Active').order_by(Tutor.name).all()

    # Prepare kanban board groupings
    kanban_groups = {
        'Pending': [t for t in tasks if t.status == 'Pending'],
        'In Progress': [t for t in tasks if t.status == 'In Progress'],
        'Completed': [t for t in tasks if t.status == 'Completed']
    }

    return render_template('tasks.html',
                           tasks=tasks,
                           kanban_groups=kanban_groups,
                           tutors=tutors,
                           today=today,
                           tutor=tutor,
                           stats=stats,
                           categories=categories,
                           priorities=priorities,
                           selected_status=selected_status,
                           selected_tutor_id=selected_tutor_id,
                           selected_priority=selected_priority,
                           selected_category=selected_category,
                           search_q=search_q,
                           view_mode=view_mode,
                           statuses=statuses,
                           page=page, per_page=per_page, total_filtered=total_filtered,
                           task_csrf_token=session['task_csrf_token'])


@tasks_bp.route('/tasks/update-status/<int:id>', methods=['POST'])
@login_required
def update_status(id):
    if not _task_csrf_ok():
        return jsonify({'success': False, 'error': 'Invalid security token'}), 400
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

    if status not in STATUSES:
        if is_ajax_request() or request.is_json:
            return jsonify({'success': False, 'error': 'Invalid status'}), 400
        flash('Invalid status.', 'danger')
        return redirect(url_for('tasks.list_tasks'))
    old_status = task.status
    task.status = status
    if notes:
        task.notes = notes
    if status == 'Completed' and old_status != 'Completed':
        task.completed_date = datetime.utcnow()
    elif status == 'Verified':
        task.verified_at = task.verified_at or datetime.utcnow()
        task.completed_date = task.completed_date or datetime.utcnow()
    else:
        if status not in ('Completed', 'Verified'):
            task.completed_date = None
        task.verified_at = None
    task.version = (task.version or 1) + 1
    _history(task, 'STATUS_CHANGED', old_status, status, notes or None)
    db.session.commit()

    if is_ajax_request() or request.is_json:
        return jsonify({'success': True, 'status': status, 'id': task.id, 'completed_date': task.completed_date.isoformat() if task.completed_date else None})

    flash(f'Task status updated to {status}.', 'success')
    return redirect(url_for('tasks.list_tasks'))


@tasks_bp.route('/tasks/edit/<int:id>', methods=['POST'])
@login_required
@admin_required
def edit_task(id):
    if not _task_csrf_ok():
        abort(400, description='Invalid task security token.')
    task = Task.query.get_or_404(id)
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    tutor_id = request.form.get('tutor_id', type=int)
    due_date_str = request.form.get('due_date', '').strip()
    status = request.form.get('status', '').strip()
    priority = request.form.get('priority', '').strip()
    category = request.form.get('category', '').strip()
    notes = request.form.get('notes', '').strip()
    if not title:
        flash('Task title is required.', 'danger')
        return redirect(url_for('tasks.list_tasks'))
    task.title = title
    task.description = description
    if tutor_id:
        if not Tutor.query.filter_by(id=tutor_id, status='Active').first():
            flash('Tasks can only be assigned to active tutors.', 'danger')
            return redirect(url_for('tasks.list_tasks'))
        task.tutor_id = tutor_id
    if due_date_str:
        try:
            task.due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Please enter a valid due date.', 'danger')
            return redirect(url_for('tasks.list_tasks'))
    else:
        task.due_date = None
    if status in STATUSES:
        old_status = task.status
        task.status = status
        if status == 'Completed' and old_status != 'Completed':
            task.completed_date = datetime.utcnow()
        elif status not in ('Completed', 'Verified'):
            task.completed_date = None
        if status == 'Verified':
            task.verified_at = task.verified_at or datetime.utcnow()
        _history(task, 'EDITED', old_status, status)
    if priority in ('High', 'Medium', 'Low'):
        task.priority = priority
    if category in ('General', 'Syllabus', 'Exam', 'Student Care', 'Admin'):
        task.category = category
    task.notes = notes
    task.version = (task.version or 1) + 1
    db.session.commit()
    flash('Task updated successfully.', 'success')
    return redirect(url_for('tasks.list_tasks'))


@tasks_bp.route('/tasks/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_task(id):
    if not _task_csrf_ok():
        abort(400, description='Invalid task security token.')
    task = Task.query.get_or_404(id)
    old_status = task.status
    task.archived_at = datetime.utcnow()
    task.archived_by = current_user.id
    task.status = 'Cancelled'
    task.version = (task.version or 1) + 1
    _history(task, 'ARCHIVED', old_status, 'Cancelled', 'Task archived')
    db.session.commit()
    flash('Task deleted successfully.', 'success')
    return redirect(url_for('tasks.list_tasks'))
