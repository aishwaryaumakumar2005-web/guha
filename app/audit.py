import json
from datetime import datetime, date
from sqlalchemy import event
from flask import g, has_request_context
from app.extensions import db


def _get_audit_user():
    if has_request_context() and hasattr(g, 'audit_user') and g.audit_user:
        return g.audit_user
    return None


def _serialize(val):
    if val is None:
        return None
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    return str(val)


def _insert_audit(connection, action, entity_type, entity_id, changes_json):
    user = _get_audit_user()
    connection.execute(
        db.text("""
            INSERT INTO audit_log (user_id, username, action, entity_type, entity_id, changes, timestamp)
            VALUES (:uid, :uname, :act, :etype, :eid, :chg, :ts)
        """),
        {
            'uid': user.id if user else None,
            'uname': user.username if user else 'system',
            'act': action,
            'etype': entity_type,
            'eid': entity_id,
            'chg': changes_json,
            'ts': datetime.utcnow()
        }
    )


def _new_vals(target):
    vals = {}
    for col in target.__table__.columns:
        name = col.name
        if name in ('id', 'password_hash'):
            continue
        vals[name] = _serialize(getattr(target, name))
    return vals


def _audit_insert(mapper, connection, target):
    vals = _new_vals(target)
    _insert_audit(connection, 'INSERT', target.__class__.__name__, target.id,
                  json.dumps(vals, default=str) if vals else None)


def _audit_before_update(mapper, connection, target):
    from sqlalchemy.orm.attributes import get_history
    changes = {}
    for col in target.__table__.columns:
        name = col.name
        if name in ('id', 'password_hash'):
            continue
        hist = get_history(target, name)
        if hist.has_changes():
            old = _serialize(hist.deleted[0]) if hist.deleted else None
            new = _serialize(hist.added[0]) if hist.added else None
            if old != new:
                changes[name] = {'from': old, 'to': new}
    if changes:
        _insert_audit(connection, 'UPDATE', target.__class__.__name__, target.id,
                      json.dumps(changes, default=str))


def _audit_delete(mapper, connection, target):
    vals = _new_vals(target)
    _insert_audit(connection, 'DELETE', target.__class__.__name__, target.id,
                  json.dumps({'before': vals}, default=str))


def register_audit_events():
    from app.models import (
        Student, Tutor, Course, Enquiry, FeeRecord,
        Expense, ExpenseCategory, Exam, ExamScore, ExamAssignment,
        User, LeaveRequest, PayrollRecord
    )
    models = [
        Student, Tutor, Course, Enquiry, FeeRecord,
        Expense, ExpenseCategory, Exam, ExamScore, ExamAssignment,
        User, LeaveRequest, PayrollRecord
    ]
    for cls in models:
        event.listen(cls, 'after_insert', _audit_insert)
        event.listen(cls, 'before_update', _audit_before_update)
        event.listen(cls, 'after_delete', _audit_delete)
