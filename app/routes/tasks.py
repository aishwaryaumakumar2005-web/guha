from datetime import datetime, date, timedelta
import secrets
import hashlib
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, abort, current_app, Response
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Task, TaskHistory, TaskActionToken, Tutor, User, Notification
from app.helpers import admin_required, is_ajax_request, save_photo_data

tasks_bp = Blueprint('tasks', __name__)

STATUSES = ('Pending', 'Accepted', 'In Progress', 'Submitted', 'Rejected', 'Blocked', 'Completed', 'Verified', 'Cancelled')

TASK_TRANSITIONS = {
    'Pending': {'Accepted', 'Rejected', 'Cancelled'},
    'Accepted': {'In Progress', 'Rejected', 'Cancelled'},
    'In Progress': {'Submitted', 'Rejected', 'Blocked'},
    'Submitted': {'Verified', 'Rejected'},
    'Rejected': {'Accepted', 'Cancelled'},
    'Blocked': {'In Progress', 'Rejected', 'Cancelled'},
    # Legacy Completed records remain viewable; only admins may transition
    # legacy tasks to/from this state during migration.
    'Completed': {'Verified', 'In Progress'},
    'Verified': {'In Progress'},
    'Cancelled': set(),
}


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


def _issue_action_token(task, tutor, action='respond'):
    raw = secrets.token_urlsafe(32)
    token = TaskActionToken(task_id=task.id, tutor_id=tutor.id, action=action,
                            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                            expires_at=datetime.utcnow() + timedelta(days=7))
    db.session.add(token)
    return raw


def _get_action_token(raw):
    if not raw:
        return None
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    token = TaskActionToken.query.filter_by(token_hash=hashed, action='respond').first()
    if not token or token.used_at or token.expires_at < datetime.utcnow():
        return None
    return token


@tasks_bp.route('/tasks', methods=['GET', 'POST'])
@login_required
def list_tasks():
    categories = ['General', 'Syllabus', 'Exam', 'Student Care', 'Admin']
    priorities = ['High', 'Medium', 'Low']
    statuses = list(STATUSES)
    if 'task_csrf_token' not in session:
        session['task_csrf_token'] = secrets.token_urlsafe(32)
    if request.method == 'GET' and current_user.role == 'Operation':
        Notification.query.filter_by(user_id=current_user.id, read_at=None).update(
            {'read_at': datetime.utcnow()}, synchronize_session=False)
        db.session.commit()

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
        operator = User.query.filter(
            db.func.lower(User.email) == (tutor_obj.email or '').lower(),
            User.role == 'Operation', User.is_active.is_(True)
        ).first()
        if operator:
            db.session.add(Notification(
                user_id=operator.id, task_id=task.id,
                message=f'New task assigned: {task.title}'
            ))
        _history(task, 'CREATED', to_status='Pending', details='Task assigned')
        action_token = _issue_action_token(task, tutor_obj)
        db.session.commit()
        try:
            action_url = url_for('tasks.respond_to_task', token=action_token, _external=True)
            ok, detail = current_app.messenger.send_task_assignment(task, tutor_obj, action_url)
            task.notification_status = 'Sent' if ok else 'Failed'
            task.notification_sent_at = datetime.utcnow() if ok else None
            task.notification_error = None if ok else str(detail)
            db.session.commit()
        except Exception as exc:
            task.notification_status = 'Failed'
            task.notification_error = str(exc)
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
    is_admin = current_user.role == 'Admin'
    if not is_admin and status in ('Verified', 'Cancelled', 'Completed'):
        error = 'Only administrators can verify, cancel, or close tasks.'
        if is_ajax_request() or request.is_json:
            return jsonify({'success': False, 'error': error}), 403
        flash(error, 'danger')
        return redirect(url_for('tasks.list_tasks'))
    if status not in TASK_TRANSITIONS.get(old_status, set()):
        error = f'Invalid task transition: {old_status} → {status}.'
        if is_ajax_request() or request.is_json:
            return jsonify({'success': False, 'error': error}), 409
        flash(error, 'danger')
        return redirect(url_for('tasks.list_tasks'))
    if status in ('Submitted', 'Rejected') and not notes:
        error = 'Please provide notes when submitting or rejecting a task.'
        if is_ajax_request() or request.is_json:
            return jsonify({'success': False, 'error': error}), 400
        flash(error, 'danger')
        return redirect(url_for('tasks.list_tasks'))
    task.status = status
    if notes:
        task.notes = notes
    if status == 'Accepted':
        task.acknowledged_at = task.acknowledged_at or datetime.utcnow()
        task.rejection_reason = None
    elif status == 'In Progress':
        task.started_at = task.started_at or datetime.utcnow()
    elif status == 'Submitted':
        task.submitted_at = datetime.utcnow()
        task.completion_notes = notes
        task.completed_date = datetime.utcnow()
        upload = request.files.get('completion_attachment') if request.files else None
        if upload and upload.filename:
            try:
                data, mime = save_photo_data(upload, max_mb=8)
                task.completion_attachment = data
                task.completion_attachment_mime = mime
                task.completion_attachment_name = upload.filename[:255]
            except ValueError as exc:
                error = str(exc)
                if is_ajax_request() or request.is_json:
                    return jsonify({'success': False, 'error': error}), 400
                flash(error, 'danger')
                return redirect(url_for('tasks.list_tasks'))
    elif status == 'Rejected':
        task.rejection_reason = notes
    elif status == 'Completed' and old_status != 'Completed':
        task.completed_date = datetime.utcnow()
    elif status == 'Verified':
        task.verified_at = task.verified_at or datetime.utcnow()
        task.verified_by = current_user.id
        task.verification_notes = notes or task.verification_notes
        task.completed_date = task.completed_date or datetime.utcnow()
    else:
        if status not in ('Completed', 'Submitted', 'Verified'):
            task.completed_date = None
        task.verified_at = None
    task.version = (task.version or 1) + 1
    _history(task, 'STATUS_CHANGED', old_status, status, notes or None)
    db.session.commit()

    if task.tutor:
        try:
            template = {
                'Accepted': 'task_accepted',
                'Submitted': 'task_submitted',
                'Verified': 'task_verified',
                'Rejected': 'task_rejected',
            }.get(status)
            if template:
                current_app.messenger.send_task_event(task, task.tutor, template, notes or status)
        except Exception:
            pass

    if is_ajax_request() or request.is_json:
        return jsonify({'success': True, 'status': status, 'id': task.id, 'completed_date': task.completed_date.isoformat() if task.completed_date else None})

    flash(f'Task status updated to {status}.', 'success')
    return redirect(url_for('tasks.list_tasks'))


@tasks_bp.route('/tasks/resend-notification/<int:id>', methods=['POST'])
@login_required
@admin_required
def resend_notification(id):
    """Retry a failed task assignment notification without changing the task."""
    if not _task_csrf_ok():
        abort(400, description='Invalid task security token.')
    task = Task.query.get_or_404(id)
    tutor_obj = Tutor.query.get(task.tutor_id)
    try:
        action_token = _issue_action_token(task, tutor_obj)
        db.session.commit()
        action_url = url_for('tasks.respond_to_task', token=action_token, _external=True)
        ok, detail = current_app.messenger.send_task_assignment(task, tutor_obj, action_url)
        task.notification_status = 'Sent' if ok else 'Failed'
        task.notification_sent_at = datetime.utcnow() if ok else None
        task.notification_error = None if ok else str(detail)
        db.session.commit()
        flash('Task WhatsApp notification sent.' if ok else f'Notification failed: {detail}', 'success' if ok else 'warning')
    except Exception as exc:
        task.notification_status = 'Failed'
        task.notification_error = str(exc)
        db.session.commit()
        flash(f'Notification failed: {exc}', 'warning')
    return redirect(url_for('tasks.list_tasks'))


@tasks_bp.route('/tasks/respond/<token>', methods=['GET', 'POST'])
@login_required
def respond_to_task(token):
    action_token = _get_action_token(token)
    if not action_token:
        abort(410, description='This task response link is expired or has already been used.')
    tutor = Tutor.query.get_or_404(action_token.tutor_id)
    if current_user.role != 'Admin' and current_user.email != tutor.email:
        abort(403)
    task = Task.query.get_or_404(action_token.task_id)
    if request.method == 'POST':
        decision = request.form.get('decision', '').strip()
        reason = request.form.get('reason', '').strip()
        if decision not in ('accept', 'decline'):
            abort(400)
        if decision == 'decline' and not reason:
            flash('Please provide a reason for declining the task.', 'danger')
            return render_template('task_response.html', task=task, tutor=tutor, token=token)
        old_status = task.status
        task.status = 'Accepted' if decision == 'accept' else 'Rejected'
        task.acknowledged_at = datetime.utcnow()
        task.rejection_reason = reason or None
        action_token.used_at = datetime.utcnow()
        _history(task, 'RESPONDED', old_status, task.status, reason or 'Accepted via secure link')
        db.session.commit()
        try:
            current_app.messenger.send_task_event(task, tutor, 'task_accepted' if decision == 'accept' else 'task_rejected', reason or task.status)
        except Exception:
            pass
        flash('Task accepted.' if decision == 'accept' else 'Task declined.', 'success' if decision == 'accept' else 'warning')
        return redirect(url_for('tasks.list_tasks'))
    return render_template('task_response.html', task=task, tutor=tutor, token=token)


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


@tasks_bp.route('/tasks/attachment/<int:id>')
@login_required
def task_attachment(id):
    task = Task.query.get_or_404(id)
    tutor = Tutor.query.filter_by(email=current_user.email).first()
    if current_user.role != 'Admin' and (not tutor or task.tutor_id != tutor.id):
        abort(403)
    if not task.completion_attachment or not task.completion_attachment_mime:
        abort(404)
    safe_name = (task.completion_attachment_name or 'evidence').replace('"', '')
    return Response(task.completion_attachment, mimetype=task.completion_attachment_mime,
                    headers={'Content-Disposition': f'inline; filename="{safe_name}"'})


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
