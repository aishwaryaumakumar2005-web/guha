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
        tutor_id = request.form.get('tutor_id', type=int)
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        due_date_str = request.form.get('due_date', '').strip()
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
    if current_user.role == 'Admin':
        tasks = Task.query.order_by(Task.created_at.desc()).all()
    else:
        tutor = Tutor.query.filter_by(email=current_user.email).first()
        if not tutor:
            tasks = []
        else:
            tasks = Task.query.filter_by(tutor_id=tutor.id).order_by(Task.created_at.desc()).all()
    tutors = Tutor.query.order_by(Tutor.name).all()
    today = date.today()
    return render_template('tasks.html', tasks=tasks, tutors=tutors, today=today, tutor=tutor)


@tasks_bp.route('/tasks/update-status/<int:id>', methods=['POST'])
@login_required
def update_status(id):
    task = Task.query.get_or_404(id)
    tutor = Tutor.query.filter_by(email=current_user.email).first()
    if current_user.role != 'Admin' and (not tutor or task.tutor_id != tutor.id):
        flash('You can only update your own tasks.', 'danger')
        return redirect(url_for('tasks.list_tasks'))
    status = request.form.get('status', '').strip()
    notes = request.form.get('notes', '').strip()
    if status not in ('Pending', 'In Progress', 'Completed'):
        flash('Invalid status.', 'danger')
        return redirect(url_for('tasks.list_tasks'))
    task.status = status
    if notes:
        task.notes = notes
    if status == 'Completed':
        task.completed_date = datetime.utcnow()
    db.session.commit()
    flash(f'Task status updated to {status}.', 'success')
    return redirect(url_for('tasks.list_tasks'))


@tasks_bp.route('/tasks/edit/<int:id>', methods=['POST'])
@login_required
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
    task.notes = notes
    db.session.commit()
    flash('Task updated successfully.', 'success')
    return redirect(url_for('tasks.list_tasks'))


@tasks_bp.route('/tasks/delete/<int:id>')
@login_required
def delete_task(id):
    task = Task.query.get_or_404(id)
    db.session.delete(task)
    db.session.commit()
    flash('Task deleted successfully.', 'success')
    return redirect(url_for('tasks.list_tasks'))
