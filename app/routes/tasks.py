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
CLOSED_STATUSES = ('Completed', 'Verified', 'Cancelled')

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
    if request.method == 'POST':
        if not _task_csrf_ok():
            abort(400, description='Invalid task security token.')
        if current_user.role not in ('Admin', 'Operation', 'Operator'):
            flash('Only administrators can assign tasks.', 'danger')
            return redirect(url_for('tasks.list_tasks'))
        tutor_id = request.form.get('tutor_id', type=int)
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        due_date_str = request.form.get('due_date', '').strip()
        priority = request.form.get('priority', 'Medium').strip()
        category = request.form.get('category', 'General').strip()
        recurrence = request.form.get('recurrence', 'None').strip()
        checklist = request.form.get('checklist', '').strip()
        effort_minutes = request.form.get('effort_minutes', type=int)

        if priority not in priorities:
            priority = 'Medium'
        if category not in categories:
            category = 'General'
        if recurrence not in ('None', 'Daily', 'Weekly', 'Monthly'):
            recurrence = 'None'
        if effort_minutes is not None and not 1 <= effort_minutes <= 10080:
            effort_minutes = None

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
                    priority=priority, category=category, recurrence=recurrence,
                    checklist=checklist, effort_minutes=effort_minutes)
        db.session.add(task)
        db.session.flush()
        operator = User.query.filter(
            db.func.lower(User.email) == (tutor_obj.email or '').lower(),
            User.role.in_(('Staff', 'Operation')), User.is_active.is_(True)
        ).first()
        if operator:
            # Notifications are auxiliary. Use a savepoint so an older
            # production database without the notification table cannot
            # abort the task-assignment transaction.
            try:
                with db.session.begin_nested():
                    db.session.add(Notification(
                        user_id=operator.id, task_id=task.id,
                        message=f'New task assigned: {task.title}'
                    ))
                    db.session.flush()
            except Exception:
                current_app.logger.exception('Notification table unavailable; task assignment will continue')
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
    if current_user.role in ('Admin', 'Operation', 'Operator'):
        pass
    else:
        tutor = Tutor.query.filter(db.func.lower(Tutor.email) == (current_user.email or '').strip().lower()).first()
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
        'completed': sum(1 for t in all_tasks if t.status in ('Completed', 'Verified')),
        'overdue': sum(1 for t in all_tasks if t.due_date and t.due_date < today and t.status not in CLOSED_STATUSES)
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
        query = query.filter(Task.due_date < today, ~Task.status.in_(CLOSED_STATUSES))

    if selected_priority and selected_priority in priorities:
        query = query.filter(Task.priority == selected_priority)

    if selected_category and selected_category in categories:
        query = query.filter(Task.category == selected_category)

    if selected_tutor_id and current_user.role in ('Admin', 'Operation', 'Operator'):
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
    kanban_groups = {status: [t for t in tasks if t.status == status] for status in STATUSES}

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
    tutor = Tutor.query.filter(db.func.lower(Tutor.email) == (current_user.email or '').strip().lower()).first()
    if current_user.role not in ('Admin', 'Operation', 'Operator') and (not tutor or task.tutor_id != tutor.id):
        if is_ajax_request() or request.is_json:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        flash('You can only update your own tasks.', 'danger')
        return redirect(url_for('tasks.list_tasks'))
    
    if request.is_json:
        data = request.get_json() or {}
        status = (data.get('status') or '').strip()
        notes = (data.get('notes') or '').strip()
        expected_version = data.get('version')
    else:
        status = request.form.get('status', '').strip()
        notes = request.form.get('notes', '').strip()
        expected_version = request.form.get('version')

    # Clients may send the version they rendered. Reject stale writes instead
    # of silently overwriting a newer status or note.
    if expected_version not in (None, ''):
        try:
            if int(expected_version) != (task.version or 1):
                error = 'This task was updated elsewhere. Refresh it before saving.'
                return jsonify({'success': False, 'error': error, 'conflict': True,
                                'version': task.version}), 409
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Invalid task version.'}), 400

    if status not in STATUSES:
        if is_ajax_request() or request.is_json:
            return jsonify({'success': False, 'error': 'Invalid status'}), 400
        flash('Invalid status.', 'danger')
        return redirect(url_for('tasks.list_tasks'))
    old_status = task.status
    is_admin = current_user.role in ('Admin', 'Operation', 'Operator')
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
    recurring_task = None
    if status in ('Completed', 'Verified') and task.recurrence in ('Daily', 'Weekly', 'Monthly') and not task.recurrence_generated:
        base_date = task.due_date or date.today()
        if task.recurrence == 'Daily':
            next_due = base_date + timedelta(days=1)
        elif task.recurrence == 'Weekly':
            next_due = base_date + timedelta(days=7)
        else:
            month = base_date.month % 12 + 1
            year = base_date.year + (1 if base_date.month == 12 else 0)
            next_due = date(year, month, min(base_date.day, 28))
        recurring_task = Task(tutor_id=task.tutor_id, title=task.title,
                              description=task.description, assigned_by=task.assigned_by,
                              due_date=next_due, priority=task.priority,
                              category=task.category, checklist=task.checklist,
                              recurrence=task.recurrence, effort_minutes=task.effort_minutes)
        task.recurrence_generated = True
        db.session.add(recurring_task)
        db.session.flush()
        _history(recurring_task, 'CREATED', to_status='Pending', details=f'Recurrence from task #{task.id}')
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Task status update failed for task %s', task.id)
        error = 'The task could not be updated. Please try again or contact an administrator.'
        if is_ajax_request() or request.is_json:
            return jsonify({'success': False, 'error': error}), 500
        flash(error, 'danger')
        return redirect(url_for('tasks.list_tasks'))

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
        return jsonify({'success': True, 'status': status, 'id': task.id,
                        'version': task.version,
                        'completed_date': task.completed_date.isoformat() if task.completed_date else None})

    flash(f'Task status updated to {status}.', 'success')
    return redirect(url_for('tasks.list_tasks'))


@tasks_bp.route('/tasks/bulk-assign', methods=['POST'])
@login_required
@admin_required
def bulk_assign_tasks():
    if not _task_csrf_ok():
        abort(400, description='Invalid task security token.')
    tutor_id = request.form.get('tutor_id', type=int)
    task_ids = [value for value in request.form.getlist('task_ids') if value.isdigit()]
    tutor = Tutor.query.filter_by(id=tutor_id, status='Active').first() if tutor_id else None
    if not tutor or not task_ids:
        flash('Select an active tutor and at least one task.', 'danger')
        return redirect(url_for('tasks.list_tasks'))
    tasks = Task.query.filter(Task.id.in_([int(value) for value in task_ids]), Task.archived_at.is_(None)).all()
    for task in tasks:
        previous = task.tutor.name if task.tutor else 'Unassigned'
        task.tutor_id = tutor.id
        task.version = (task.version or 1) + 1
        _history(task, 'REASSIGNED', details=f'{previous} → {tutor.name}')
    db.session.commit()
    flash(f'{len(tasks)} task(s) assigned to {tutor.name}.', 'success')
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
    if current_user.role not in ('Admin', 'Operation', 'Operator') and current_user.email != tutor.email:
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
    checklist = request.form.get('checklist', '').strip()
    recurrence = request.form.get('recurrence', 'None').strip()
    effort_minutes = request.form.get('effort_minutes', type=int)
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
        if status != old_status and status not in TASK_TRANSITIONS.get(old_status, set()):
            flash(f'Invalid task transition: {old_status} → {status}.', 'danger')
            return redirect(url_for('tasks.list_tasks'))
        if status in ('Submitted', 'Rejected') and not notes:
            flash('Please provide notes when submitting or rejecting a task.', 'danger')
            return redirect(url_for('tasks.list_tasks'))
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
    if recurrence in ('None', 'Daily', 'Weekly', 'Monthly'):
        task.recurrence = recurrence
    task.checklist = checklist
    task.effort_minutes = effort_minutes if effort_minutes and 1 <= effort_minutes <= 10080 else None
    task.notes = notes
    task.version = (task.version or 1) + 1
    db.session.commit()
    flash('Task updated successfully.', 'success')
    return redirect(url_for('tasks.list_tasks'))


@tasks_bp.route('/tasks/history/<int:id>')
@login_required
@admin_required
def task_history(id):
    task = Task.query.get_or_404(id)
    rows = TaskHistory.query.filter_by(task_id=task.id).order_by(TaskHistory.created_at.desc()).limit(20).all()
    return jsonify({'history': [
        {'action': row.action, 'from_status': row.from_status, 'to_status': row.to_status,
         'details': row.details, 'created_at': row.created_at.strftime('%d %b %Y, %I:%M %p') if row.created_at else ''}
        for row in rows
    ]})

@tasks_bp.route('/tasks/details/<int:id>')
@login_required
def task_details(id):
    task = Task.query.get_or_404(id)
    tutor = Tutor.query.filter(db.func.lower(Tutor.email) == (current_user.email or '').strip().lower()).first()
    if current_user.role not in ('Admin', 'Operation', 'Operator') and (not tutor or task.tutor_id != tutor.id):
        return jsonify({'error': 'Unauthorized'}), 403
    history = TaskHistory.query.filter_by(task_id=task.id).order_by(TaskHistory.created_at.desc()).limit(50).all()
    return jsonify({'id': task.id, 'title': task.title, 'description': task.description or '',
                    'status': task.status, 'priority': task.priority or 'Medium',
                    'category': task.category or 'General', 'assignee': task.tutor.name if task.tutor else 'Unassigned',
                    'due_date': task.due_date.strftime('%d %b %Y') if task.due_date else 'No due date',
                    'notes': task.notes or '', 'attachment': bool(task.completion_attachment),
                    'attachment_url': url_for('tasks.task_attachment', id=task.id) if task.completion_attachment else None,
                    'notification_status': task.notification_status or 'Not sent',
                    'checklist': [item for item in (task.checklist or '').splitlines() if item.strip()],
                    'recurrence': task.recurrence or 'None',
                    'effort_minutes': task.effort_minutes,
                    'version': task.version or 1,
                    'history': [{'action': h.action, 'from_status': h.from_status,
                                 'to_status': h.to_status, 'details': h.details,
                                 'created_at': h.created_at.strftime('%d %b %Y, %I:%M %p') if h.created_at else ''}
                                for h in history]})


@tasks_bp.route('/tasks/checklist/<int:id>', methods=['POST'])
@login_required
def update_checklist(id):
    if not _task_csrf_ok():
        return jsonify({'success': False, 'error': 'Invalid security token'}), 400
    task = Task.query.get_or_404(id)
    tutor = Tutor.query.filter(db.func.lower(Tutor.email) == (current_user.email or '').strip().lower()).first()
    if current_user.role not in ('Admin', 'Operation', 'Operator') and (not tutor or task.tutor_id != tutor.id):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    index = request.form.get('index', type=int)
    checked = request.form.get('checked') == 'true'
    items = [item.strip() for item in (task.checklist or '').splitlines() if item.strip()]
    if index is None or index < 0 or index >= len(items):
        return jsonify({'success': False, 'error': 'Invalid checklist item'}), 400
    text = items[index].removeprefix('[x] ').removeprefix('[ ] ').strip()
    items[index] = ('[x] ' if checked else '[ ] ') + text
    task.checklist = '\n'.join(items)
    task.version = (task.version or 1) + 1
    _history(task, 'CHECKLIST_UPDATED', details=f'Item {index + 1} marked {"complete" if checked else "open"}')
    db.session.commit()
    return jsonify({'success': True, 'checklist': items, 'version': task.version})


@tasks_bp.route('/tasks/analytics')
@login_required
def task_analytics():
    """Role-scoped task metrics for dashboards and future charts."""
    query = Task.query.filter(Task.archived_at.is_(None))
    if current_user.role not in ('Admin', 'Operation', 'Operator'):
        tutor = Tutor.query.filter(db.func.lower(Tutor.email) == (current_user.email or '').strip().lower()).first()
        query = query.filter(Task.tutor_id == tutor.id if tutor else db.false())
    rows = query.all()
    today = date.today()
    by_status = {status: sum(1 for task in rows if task.status == status) for status in STATUSES}
    by_priority = {priority: sum(1 for task in rows if (task.priority or 'Medium') == priority)
                   for priority in ('High', 'Medium', 'Low')}
    overdue = sum(1 for task in rows if task.due_date and task.due_date < today and task.status not in CLOSED_STATUSES)
    durations = [(task.completed_date - task.created_at).total_seconds() / 86400
                 for task in rows if task.completed_date and task.created_at]
    return jsonify({'total': len(rows), 'by_status': by_status, 'by_priority': by_priority,
                    'overdue': overdue,
                    'average_completion_days': round(sum(durations) / len(durations), 2) if durations else 0})


@tasks_bp.route('/tasks/attachment/<int:id>')
@login_required
def task_attachment(id):
    task = Task.query.get_or_404(id)
    tutor = Tutor.query.filter(db.func.lower(Tutor.email) == (current_user.email or '').strip().lower()).first()
    if current_user.role not in ('Admin', 'Operation', 'Operator') and (not tutor or task.tutor_id != tutor.id):
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
