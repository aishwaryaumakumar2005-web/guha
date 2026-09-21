import csv
from calendar import monthrange
from datetime import date, datetime, timedelta
from io import BytesIO, StringIO
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_
from app.extensions import db
from app.models import LeaveRequest, Tutor, Attendance, User
from app.helpers import admin_required, is_ajax_request
from app.forms import LeaveForm, LEAVE_TYPES

leaves_bp = Blueprint('leaves', __name__)

# Server-side cap so the page never loads unbounded history/pending rows.
LEAVE_LIST_LIMIT = 50
LEAVE_PAGE_SIZE = 25

DEFAULT_LEAVE_TYPE = 'Casual'

FILTER_STATUSES = ('All', 'Pending', 'Approved', 'Rejected', 'Withdrawn', 'Cancelled')


def _month_range(value):
    """Parse 'YYYY-MM' into (month_start, next_month_start) or None."""
    if not value:
        return None
    try:
        y, m = str(value).split('-')
        y, m = int(y), int(m)
        if 1900 <= y <= 2100 and 1 <= m <= 12:
            start = date(y, m, 1)
            if m == 12:
                return start, date(y + 1, 1, 1)
            return start, date(y, m + 1, 1)
    except (ValueError, AttributeError):
        pass
    return None


def _overlap_errors(form, start_date, end_date):
    """Reject a new request that overlaps an existing Pending/Approved one."""
    conflict = LeaveRequest.query.filter(
        LeaveRequest.user_id == current_user.id,
        LeaveRequest.status.in_(['Pending', 'Approved']),
        LeaveRequest.start_date <= end_date,
        LeaveRequest.end_date >= start_date,
    ).first()
    if conflict:
        form._error('start_date', 'You already have a pending or approved leave overlapping these dates.')


def _leave_balance(user):
    """Per leave type: entitlement, days used this year, days remaining."""
    entitlements = current_app.config.get('LEAVE_ENTITLEMENTS', {}).get(user.role, {})
    if not entitlements:
        return {}
    year = date.today().year
    approved = LeaveRequest.query.filter(
        LeaveRequest.user_id == user.id,
        LeaveRequest.status == 'Approved',
        LeaveRequest.start_date <= date(year, 12, 31),
        LeaveRequest.end_date >= date(year, 1, 1),
    ).all()
    used = {}
    for req in approved:
        leave_type = req.leave_type or DEFAULT_LEAVE_TYPE
        lo = max(req.start_date, date(year, 1, 1))
        hi = min(req.end_date, date(year, 12, 31))
        used[leave_type] = used.get(leave_type, 0) + max((hi - lo).days + 1, 0)
    return {
        leave_type: {
            'entitlement': ent,
            'used': used.get(leave_type, 0),
            'remaining': max(ent - used.get(leave_type, 0), 0),
        }
        for leave_type, ent in entitlements.items()
    }


def _days_on_leave_this_month(user_id):
    """Approved leave days that overlap the current calendar month (≤ today)."""
    today = date.today()
    month_start = today.replace(day=1)
    rows = LeaveRequest.query.filter(
        LeaveRequest.user_id == user_id,
        LeaveRequest.status == 'Approved',
        LeaveRequest.start_date <= today,
        LeaveRequest.end_date >= month_start,
    ).all()
    days = 0
    for req in rows:
        lo = max(req.start_date, month_start)
        hi = min(req.end_date, today)
        if hi >= lo:
            days += (hi - lo).days + 1
    return days


def _sync_leave_attendance(leave):
    """Mark the approved dates as Leave for the staff member's tutor record.

    Only fills days that have no attendance record yet, so manual marks are
    never clobbered. Returns the number of rows written.
    """
    if not leave.staff or not leave.staff.email:
        return 0
    tutor = Tutor.query.filter_by(email=leave.staff.email).first()
    if not tutor:
        return 0
    written = 0
    day_count = (leave.end_date - leave.start_date).days + 1
    for offset in range(day_count):
        d = leave.start_date + timedelta(days=offset)
        existing = Attendance.query.filter_by(
            person_type='tutor', person_id=tutor.id, date=d
        ).first()
        if existing:
            continue
        db.session.add(Attendance(
            person_type='tutor', person_id=tutor.id, date=d,
            status='Leave', marked_by=f'auto_leave:{leave.id}'))
        written += 1
    return written


def _reconcile_leave_attendance(leave):
    """Remove only attendance rows created by this leave request."""
    if not leave.staff or not leave.staff.email:
        return 0
    tutor = Tutor.query.filter_by(email=leave.staff.email).first()
    if not tutor:
        return 0
    rows = Attendance.query.filter(
        Attendance.person_type == 'tutor', Attendance.person_id == tutor.id,
        Attendance.marked_by == f'auto_leave:{leave.id}').all()
    for row in rows:
        db.session.delete(row)
    return len(rows)


def _balance_error(user, leave_type, start_date, end_date, exclude_id=None):
    """Return an entitlement error for the request's calendar year, if any."""
    balance = _leave_balance(user).get(leave_type)
    if not balance:
        return None
    requested = (end_date - start_date).days + 1
    used = balance['used']
    if exclude_id:
        old = LeaveRequest.query.get(exclude_id)
        if old and old.status == 'Approved' and old.leave_type == leave_type:
            year = date.today().year
            lo = max(old.start_date, date(year, 1, 1))
            hi = min(old.end_date, date(year, 12, 31))
            used -= max((hi - lo).days + 1, 0)
    if used + requested > balance['entitlement']:
        return f'{leave_type} leave exceeds the available balance ({max(balance["entitlement"] - used, 0)} days remaining).'
    return None


def _send_status_notification(leave):
    """Best-effort email + WhatsApp/SMS on a status change. Never raises."""
    try:
        staff = leave.staff
        if not staff:
            return
        dates_text = f"{leave.start_date.strftime('%d %b %Y')} to {leave.end_date.strftime('%d %b %Y')}"
        if staff.email:
            current_app.notifier.notify_leave_status(
                staff.email, staff.name, dates_text, leave.status, leave.remarks)
        tutor = Tutor.query.filter_by(email=staff.email).first()
        if tutor and tutor.phone:
            current_app.messenger.send_leave_status(
                tutor.phone, staff.name, dates_text, leave.status, leave.remarks)
    except Exception as e:
        current_app.logger.warning('Leave status notification failed: %s', e)


def _apply_q(query, q):
    like = f'%{q}%'
    return query.join(LeaveRequest.staff).filter(or_(
        LeaveRequest.reason.ilike(like),
        User.name.ilike(like),
        User.username.ilike(like),
    ))


def _parse_filters():
    """Read + sanitise the U1 filter query params. Returns (filters, extra)."""
    status = (request.args.get('status') or '').strip()
    if status not in FILTER_STATUSES:
        status = ''
    month = _month_range(request.args.get('month'))
    q = (request.args.get('q') or '').strip()[:100]
    user_scope = None
    if current_user.role == 'Admin':
        raw_uid = (request.args.get('user_id') or '').strip()
        if raw_uid.isdigit():
            uid = int(raw_uid)
            if User.query.get(uid) is not None:
                user_scope = uid
    filters = {
        'status': status or 'All',
        'month': month[0].strftime('%Y-%m') if month else '',
        'user_id': user_scope or '',
        'q': q,
    }
    filter_args = {k: v for k, v in filters.items() if v not in ('', 'All')}
    export_args = dict(filter_args)
    if 'status' in export_args:
        del export_args['status']
    if 'user_id' in export_args:
        export_args['user_id'] = user_scope
    return filters, filter_args, export_args, status, month, q, user_scope


def _build_summary(user):
    """U2 summary card numbers: on-leave-today, pending days, upcoming, balance/year."""
    today = date.today()
    base = LeaveRequest.query
    if user.role != 'Admin':
        base = base.filter_by(user_id=user.id)
    on_today = base.filter(
        LeaveRequest.status == 'Approved',
        LeaveRequest.start_date <= today,
        LeaveRequest.end_date >= today,
    ).count()
    pending_rows = base.filter_by(status='Pending').all()
    days_pending = sum((r.end_date - r.start_date).days + 1 for r in pending_rows)
    upcoming = base.filter(
        LeaveRequest.status == 'Approved',
        LeaveRequest.start_date > today,
    ).count()
    summary = {'on_leave_today': on_today, 'days_pending': days_pending, 'upcoming': upcoming}
    if user.role == 'Staff':
        balance = _leave_balance(user)
        summary['balance_total'] = sum(b['remaining'] for b in balance.values())
        summary['days_used'] = sum(b['used'] for b in balance.values())
        summary['on_leave_today'] = bool(on_today)
    return summary


def _staff_with_balance(limit=3):
    """Admin U6 empty-state hint: staff who still have leave balance remaining."""
    out = []
    for u in User.query.filter_by(role='Staff').order_by(User.name.asc()).all():
        bal = _leave_balance(u)
        total = sum(b['remaining'] for b in bal.values())
        if total > 0:
            out.append((u.name, total))
        if len(out) >= limit:
            break
    return out


def _calendar_data(month_start, month_end, user_scope, viewer_id):
    """U5: map each day of the month to the leave chips displayed on it."""
    query = LeaveRequest.query.filter(
        LeaveRequest.status.in_(['Approved', 'Pending']),
        LeaveRequest.start_date < month_end,
        LeaveRequest.end_date >= month_start,
    )
    if user_scope:
        query = query.filter_by(user_id=user_scope)
    grid = {}
    last = month_end - timedelta(days=1)
    for row in query.all():
        lo = max(row.start_date, month_start)
        hi = min(row.end_date, last)
        d = lo
        while d <= hi:
            grid.setdefault(d, []).append({
                'staff': row.staff.name if row.staff else 'Unknown',
                'status': row.status,
                'leave_type': row.leave_type or DEFAULT_LEAVE_TYPE,
                'id': row.id,
                'own': row.user_id == viewer_id,
            })
            d += timedelta(days=1)
    return grid


def _calendar_weeks(month_start, grid, today):
    lead = month_start.weekday()  # Monday = 0
    days_in_month = monthrange(month_start.year, month_start.month)[1]
    cells = [None] * lead
    for day in range(1, days_in_month + 1):
        day_date = month_start.replace(day=day)
        cells.append({
            'day': day,
            'date': day_date,
            'today': day_date == today,
            'entries': grid.get(day_date, []),
        })
    while len(cells) % 7 != 0:
        cells.append(None)
    return [cells[i:i + 7] for i in range(0, len(cells), 7)]


@leaves_bp.route('/leaves', methods=['GET', 'POST'])
@login_required
def leaves():
    if request.method == 'POST':
        form = LeaveForm(request.form)
        valid = form.validate()
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date') or start_date
        if valid and start_date:
            _overlap_errors(form, start_date, end_date)
            valid = len(form.errors) == 0
        if not valid:
            if is_ajax_request():
                return jsonify({"success": False, "errors": form.error_messages}), 400
            for msg in form.error_messages:
                flash(msg, 'danger')
            return redirect(url_for('leaves.leaves'))
        reason = request.form.get('reason', '').strip()
        leave_type = (request.form.get('leave_type') or DEFAULT_LEAVE_TYPE).strip() or DEFAULT_LEAVE_TYPE
        if leave_type not in LEAVE_TYPES:
            leave_type = DEFAULT_LEAVE_TYPE
        leave_type = leave_type if leave_type in LEAVE_TYPES else DEFAULT_LEAVE_TYPE
        balance_error = _balance_error(current_user, leave_type, start_date, end_date)
        if balance_error:
            if is_ajax_request():
                return jsonify({"success": False, "errors": [balance_error]}), 400
            flash(balance_error, 'danger')
            return redirect(url_for('leaves.leaves'))
        new_leave = LeaveRequest(
            user_id=current_user.id, start_date=start_date, end_date=end_date,
            reason=reason, leave_type=leave_type, status='Pending'
        )
        db.session.add(new_leave)
        db.session.commit()
        message = "Leave request submitted successfully!"
        if is_ajax_request():
            return jsonify({"success": True, "message": message}), 201
        flash(message, "success")
        return redirect(url_for('leaves.leaves'))

    today = date.today()
    filters, filter_args, export_args, status, month, q, user_scope = _parse_filters()

    is_admin = current_user.role == 'Admin'
    base_q = LeaveRequest.query
    if not is_admin:
        base_q = base_q.filter_by(user_id=current_user.id)
    elif user_scope:
        base_q = base_q.filter_by(user_id=user_scope)
    if month:
        ms, me = month
        base_q = base_q.filter(LeaveRequest.start_date < me, LeaveRequest.end_date >= ms)
    if q:
        base_q = _apply_q(base_q, q)
    pending_q = base_q.filter(LeaveRequest.status == 'Pending')
    history_q = base_q.filter(LeaveRequest.status != 'Pending')
    if status and status != 'All':
        history_q = history_q.filter(LeaveRequest.status == status)
    pending_total = pending_q.count()
    history_total = history_q.count()
    try:
        pending_page = max(int(request.args.get('pending_page', 1)), 1)
        history_page = max(int(request.args.get('history_page', 1)), 1)
    except (TypeError, ValueError):
        pending_page, history_page = 1, 1
    pending_leaves = pending_q.order_by(LeaveRequest.created_at.asc()).offset((pending_page - 1) * LEAVE_PAGE_SIZE).limit(LEAVE_PAGE_SIZE).all()
    history_leaves = history_q.order_by(LeaveRequest.created_at.desc()).offset((history_page - 1) * LEAVE_PAGE_SIZE).limit(LEAVE_PAGE_SIZE).all()

    # U5 calendar: default view follows the month filter when present.
    cal = (request.args.get('cal') or (month[0].strftime('%Y-%m') if month else today.strftime('%Y-%m')))
    cal_range = _month_range(cal) or (date(today.year, today.month, 1),
                                      date(today.year, today.month + 1, 1) if today.month < 12
                                      else date(today.year + 1, 1, 1))
    month_start, month_end = cal_range
    cal_scope = user_scope if is_admin else current_user.id
    grid = _calendar_data(month_start, month_end, cal_scope, current_user.id)

    summary = _build_summary(current_user)
    if is_admin:
        summary_cards = [
            {'label': 'On leave today', 'value': summary['on_leave_today'], 'sub': 'Approved staff', 'icon': 'bi-calendar2-check', 'theme': 'courses'},
            {'label': 'Days pending', 'value': summary['days_pending'], 'sub': 'Across staff requests', 'icon': 'bi-hourglass-split', 'theme': 'enrollments'},
            {'label': 'Upcoming leaves', 'value': summary['upcoming'], 'sub': 'Approved, future dated', 'icon': 'bi-calendar2-event', 'theme': 'staff'},
        ]
        staff_users = User.query.filter_by(role='Staff').order_by(User.name.asc()).all()
        staff_with_balance = _staff_with_balance()
        staff_balance_names = ', '.join(n for n, _ in staff_with_balance)
    else:
        summary_cards = [
            {'label': 'Balance left', 'value': summary['balance_total'], 'sub': f'Across {today.year}', 'icon': 'bi-pie-chart-fill', 'theme': 'lc-active'},
            {'label': 'Days used', 'value': summary['days_used'], 'sub': f'This year ({today.year})', 'icon': 'bi-calendar2-minus', 'theme': 'staff'},
            {'label': 'Days pending', 'value': summary['days_pending'], 'sub': 'Awaiting review', 'icon': 'bi-hourglass-split', 'theme': 'enrollments'},
            {'label': 'Upcoming leaves', 'value': summary['upcoming'], 'sub': 'Approved, future dated', 'icon': 'bi-calendar2-event', 'theme': 'courses'},
            {'label': 'On leave today', 'value': 'Yes' if summary['on_leave_today'] else 'No', 'sub': '', 'icon': 'bi-calendar2-check', 'theme': 'lc-danger' if summary['on_leave_today'] else 'lc-muted'},
        ]
        staff_users = []
        staff_with_balance = []
        staff_balance_names = ''

    return render_template(
        'leaves.html',
        pending_leaves=pending_leaves,
        history_leaves=history_leaves,
        pending_total=pending_total,
        history_total=history_total,
        list_limit=LEAVE_PAGE_SIZE,
        pending_page=pending_page,
        history_page=history_page,
        pending_pages=max((pending_total + LEAVE_PAGE_SIZE - 1) // LEAVE_PAGE_SIZE, 1),
        history_pages=max((history_total + LEAVE_PAGE_SIZE - 1) // LEAVE_PAGE_SIZE, 1),
        leave_balance=_leave_balance(current_user) if not is_admin else None,
        leave_types=LEAVE_TYPES,
        aging_days=current_app.config.get('LEAVE_AGING_DAYS', 7),
        today=today,
        filters=filters,
        filter_args=filter_args,
        export_args=export_args,
        status_filter=status or 'All',
        staff_users=staff_users,
        summary_cards=summary_cards,
        staff_with_balance=staff_with_balance,
        staff_balance_names=staff_balance_names,
        cal_weeks=_calendar_weeks(month_start, grid, today),
        cal_label=month_start.strftime('%B %Y'),
        cal_prev=(month_start - timedelta(days=1)).strftime('%Y-%m'),
        cal_next=month_end.strftime('%Y-%m'),
    )


@leaves_bp.route('/leaves/action/<int:leave_id>/<string:action>', methods=['POST'])
@login_required
@admin_required
def leave_action(leave_id, action):
    # Lock the request for the duration of the decision so two admins cannot
    # approve/reject the same pending row concurrently on transactional DBs.
    leave = LeaveRequest.query.with_for_update().filter_by(id=leave_id).first_or_404()
    if action in ('approve', 'reject') and leave.status != 'Pending':
        message = (f"Leave request for {leave.staff.name} was already actioned "
                   f"(current status: {leave.status}).")
        if is_ajax_request():
            return jsonify({"success": False, "message": message}), 400
        flash(message, "danger")
        return redirect(url_for('leaves.leaves'))
    if action == 'approve':
        leave_type = leave.leave_type or DEFAULT_LEAVE_TYPE
        balance_error = _balance_error(leave.staff, leave_type, leave.start_date, leave.end_date)
        if balance_error:
            if is_ajax_request():
                return jsonify({"success": False, "message": balance_error}), 400
            flash(balance_error, 'danger')
            return redirect(url_for('leaves.leaves'))
        leave.status = 'Approved'
        message = f"Leave request for {leave.staff.name} approved."
        _sync_leave_attendance(leave)
    elif action == 'reject':
        leave.status = 'Rejected'
        message = f"Leave request for {leave.staff.name} rejected."
    else:
        message = "Invalid action."
        if is_ajax_request():
            return jsonify({"success": False, "message": message}), 400
        flash(message, "danger")
        return redirect(url_for('leaves.leaves'))
    leave.approved_by = current_user.id
    leave.actioned_at = datetime.utcnow()
    leave.remarks = (request.form.get('remarks') or '').strip() or None
    db.session.commit()
    _send_status_notification(leave)
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('leaves.leaves'))


@leaves_bp.route('/leaves/withdraw/<int:leave_id>', methods=['POST'])
@login_required
def withdraw_leave(leave_id):
    leave = LeaveRequest.query.get_or_404(leave_id)
    if leave.user_id != current_user.id:
        message = "You can only cancel your own leave requests."
        if is_ajax_request():
            return jsonify({"success": False, "message": message}), 403
        flash(message, "danger")
        return redirect(url_for('leaves.leaves'))
    if leave.status not in ('Pending', 'Approved'):
        message = f"Only pending or future approved requests can be cancelled (current status: {leave.status})."
        if is_ajax_request():
            return jsonify({"success": False, "message": message}), 400
        flash(message, "danger")
        return redirect(url_for('leaves.leaves'))
    if leave.status == 'Approved' and leave.start_date <= date.today():
        message = 'Leave that has already started cannot be cancelled.'
        if is_ajax_request():
            return jsonify({"success": False, "message": message}), 400
        flash(message, 'danger')
        return redirect(url_for('leaves.leaves'))
    if leave.status == 'Approved':
        _reconcile_leave_attendance(leave)
    leave.status = 'Withdrawn'
    leave.actioned_at = datetime.utcnow()
    leave.approved_by = current_user.id
    leave.remarks = (request.form.get('remarks') or '').strip() or leave.remarks
    db.session.commit()
    message = "Leave request withdrawn successfully."
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('leaves.leaves'))


@leaves_bp.route('/leaves/export')
@login_required
def export_leaves():
    query = LeaveRequest.query
    if current_user.role != 'Admin':
        query = query.filter_by(user_id=current_user.id)
    status = (request.args.get('status') or '').strip()
    leave_type = (request.args.get('leave_type') or '').strip()
    if status:
        query = query.filter_by(status=status)
    if leave_type:
        query = query.filter_by(leave_type=leave_type)
    month = _month_range(request.args.get('month'))
    if month:
        ms, me = month
        query = query.filter(LeaveRequest.start_date < me, LeaveRequest.end_date >= ms)
    q = (request.args.get('q') or '').strip()[:100]
    if q:
        query = _apply_q(query, q)
    if current_user.role == 'Admin':
        raw_uid = (request.args.get('user_id') or '').strip()
        if raw_uid.isdigit() and User.query.get(int(raw_uid)) is not None:
            # NOTE: explicit entity — filter_by() after _apply_q()'s join would
            # resolve against the joined User entity, not LeaveRequest.
            query = query.filter(LeaveRequest.user_id == int(raw_uid))
    rows = query.order_by(LeaveRequest.created_at.desc()).all()
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(['ID', 'Staff Name', 'Username', 'Leave Type', 'Start Date', 'End Date',
                     'Duration Days', 'Reason', 'Status', 'Approved By', 'Actioned At',
                     'Remarks', 'Created At'])
    for req in rows:
        writer.writerow([
            req.id,
            req.staff.name if req.staff else '',
            req.staff.username if req.staff else '',
            req.leave_type or DEFAULT_LEAVE_TYPE,
            req.start_date.isoformat(),
            req.end_date.isoformat(),
            (req.end_date - req.start_date).days + 1,
            req.reason or '',
            req.status,
            req.approver.name if req.approver else '',
            req.actioned_at.isoformat() if req.actioned_at else '',
            req.remarks or '',
            req.created_at.isoformat() if req.created_at else '',
        ])
    output = buf.getvalue().encode('utf-8-sig')
    return send_file(BytesIO(output), mimetype='text/csv', as_attachment=True,
                     download_name=f'leave_history_{date.today().strftime("%Y%m%d")}.csv')


@leaves_bp.route('/leaves/report')
@login_required
@admin_required
def leave_report():
    """Compact JSON report for analytics and scheduled reporting consumers."""
    year = request.args.get('year', type=int) or date.today().year
    year = min(max(year, 1900), 2100)
    start, end = date(year, 1, 1), date(year + 1, 1, 1)
    rows = LeaveRequest.query.filter(
        LeaveRequest.start_date < end, LeaveRequest.end_date >= start).all()
    report = {'year': year, 'total_requests': len(rows), 'by_status': {},
              'by_type': {}, 'approved_days': 0, 'pending_days': 0}
    for row in rows:
        report['by_status'][row.status] = report['by_status'].get(row.status, 0) + 1
        leave_type = row.leave_type or DEFAULT_LEAVE_TYPE
        report['by_type'][leave_type] = report['by_type'].get(leave_type, 0) + 1
        lo, hi = max(row.start_date, start), min(row.end_date, end - timedelta(days=1))
        days = max((hi - lo).days + 1, 0)
        if row.status == 'Approved':
            report['approved_days'] += days
        elif row.status == 'Pending':
            report['pending_days'] += days
    return jsonify(report)
