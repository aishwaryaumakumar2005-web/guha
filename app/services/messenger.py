import json
import requests
from datetime import datetime, timedelta, date


class Messenger:
    API_BASE = 'https://graph.facebook.com/v22.0'

    def __init__(self, app=None):
        self.app = app
        if app:
            self.init_app(app)

    def init_app(self, app):
        self.app = app

    def _get_settings(self):
        from app.models import SystemSetting
        def val(key):
            s = SystemSetting.query.filter_by(key=key).first()
            return s.value if s and s.value else ''
        return {
            'whatsapp_token': val('WHATSAPP_TOKEN'),
            'whatsapp_phone_id': val('WHATSAPP_PHONE_ID'),
            'whatsapp_business_id': val('WHATSAPP_BUSINESS_ID'),
        }

    def _send_whatsapp(self, to_phone, template_name, params=None):
        cfg = self._get_settings()
        token = cfg['whatsapp_token']
        phone_id = cfg['whatsapp_phone_id']
        if not token or not phone_id or not to_phone:
            return False, 'Missing configuration or recipient'
        phone = ''.join(c for c in to_phone if c.isdigit())
        if not phone.startswith('1') and not phone.startswith('91') and not phone.startswith(''):
            phone = '91' + phone
        components = []
        if params:
            components.append({
                'type': 'body',
                'parameters': [{'type': 'text', 'text': str(p)} for p in params]
            })
        payload = {
            'messaging_product': 'whatsapp',
            'to': phone,
            'type': 'template',
            'template': {
                'name': template_name,
                'language': {'code': 'en'},
            }
        }
        if components:
            payload['template']['components'] = components
        url = f'{self.API_BASE}/{phone_id}/messages'
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            data = resp.json()
            if resp.ok and data.get('messages'):
                return True, data['messages'][0]['id']
            error = data.get('error', {}).get('message', resp.text)
            return False, error
        except requests.RequestException as e:
            return False, str(e)

    def _format_phone(self, raw):
        digits = ''.join(c for c in raw if c.isdigit())
        if not digits.startswith('+'):
            digits = '+91' + digits if len(digits) == 10 else '+' + digits
        return digits

    def send_fee_reminder(self, student_name, phone, amount_due, due_date):
        cfg = self._get_settings()
        if not cfg['whatsapp_token'] or not cfg['whatsapp_phone_id']:
            return self._send_sms_fallback(student_name, phone, amount_due, due_date)
        ok, _ = self._send_whatsapp(phone, 'fee_reminder', [student_name, f'₹{amount_due:,.0f}', due_date])
        if ok:
            return True
        return self._send_sms_fallback(student_name, phone, amount_due, due_date)

    def send_attendance_alert(self, student_name, phone, course_name, percentage):
        msg = (
            f"Dear {student_name},\n"
            f"Your attendance in {course_name} has dropped to {percentage}%.\n"
            f"Please ensure regular attendance to stay on track.\n"
            f"- Guha Academy"
        )
        return self._send_sms_direct(phone, msg)

    def send_exam_schedule(self, student_name, phone, course_name, exam_date, exam_time, venue):
        msg = (
            f"Exam Schedule - {course_name}\n"
            f"Dear {student_name},\n"
            f"Date: {exam_date}\n"
            f"Time: {exam_time}\n"
            f"Venue: {venue}\n"
            f"Best of luck!\n"
            f"- Guha Academy"
        )
        return self._send_sms_direct(phone, msg)

    def send_bulk(self, recipients, message_type, **kwargs):
        results = {'sent': 0, 'failed': 0, 'errors': []}
        for name, phone, extra in recipients:
            if message_type == 'fee_reminder':
                ok = self.send_fee_reminder(name, phone, extra.get('amount', 0), extra.get('due_date', 'N/A'))
            elif message_type == 'attendance_alert':
                ok = self.send_attendance_alert(name, phone, extra.get('course', 'Course'), extra.get('percentage', 0))
            elif message_type == 'exam_schedule':
                ok = self.send_exam_schedule(name, phone, extra.get('course', 'Course'), extra.get('date', 'TBD'), extra.get('time', 'TBD'), extra.get('venue', 'Institute'))
            else:
                results['failed'] += 1
                results['errors'].append(f"Unknown type {message_type} for {name}")
                continue
            if ok:
                results['sent'] += 1
            else:
                results['failed'] += 1
                results['errors'].append(f"Failed for {name} ({phone})")
        return results

    def _send_sms_direct(self, phone, text):
        cfg = self._get_settings()
        token = cfg['whatsapp_token']
        phone_id = cfg['whatsapp_phone_id']
        if not token or not phone_id:
            return False
        digits = ''.join(c for c in phone if c.isdigit())
        if not digits.startswith('+'):
            digits = '91' + digits if len(digits) == 10 else digits
        payload = {
            'messaging_product': 'whatsapp',
            'to': digits,
            'type': 'text',
            'text': {'body': text, 'preview_url': False}
        }
        url = f'{self.API_BASE}/{phone_id}/messages'
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            return resp.ok
        except requests.RequestException:
            return False

    def _send_sms_fallback(self, student_name, phone, amount_due, due_date):
        text = (
            f"Fee Reminder\nDear {student_name},\n"
            f"Your outstanding balance is ₹{amount_due:,.0f}.\n"
            f"Please clear the dues by {due_date} to avoid late charges.\n"
            f"- Guha Academy"
        )
        return self._send_sms_direct(phone, text)

    def batch_fee_reminders(self):
        from app.models import Student, FeeRecord
        recipients = []
        for s in Student.query.filter_by(status='Active').all():
            total_fee = sum(c.fees for c in s.courses)
            total_paid = sum(r.amount_paid for r in s.fee_records)
            balance = total_fee - total_paid
            if balance > 0 and s.phone:
                recipients.append((s.name, s.phone, {'amount': balance, 'due_date': date.today().strftime('%d %b %Y')}))
        if not recipients:
            return {'sent': 0, 'failed': 0, 'errors': ['No students with outstanding balance']}
        return self.send_bulk(recipients, 'fee_reminder')

    def batch_attendance_alerts(self, threshold=60):
        from app.models import Student, Attendance
        recipients = []
        thirty_days_ago = date.today() - timedelta(days=30)
        for s in Student.query.filter_by(status='Active').all():
            if not s.phone:
                continue
            total = Attendance.query.filter(
                Attendance.person_type == 'student', Attendance.person_id == s.id,
                Attendance.date >= thirty_days_ago
            ).count()
            if total < 5:
                continue
            present = Attendance.query.filter(
                Attendance.person_type == 'student', Attendance.person_id == s.id,
                Attendance.date >= thirty_days_ago, Attendance.status == 'Present'
            ).count()
            pct = round(present / total * 100)
            if pct < threshold:
                course_names = ', '.join(c.name for c in s.courses[:2]) or 'Course'
                recipients.append((s.name, s.phone, {'course': course_names, 'percentage': pct}))
        if not recipients:
            return {'sent': 0, 'failed': 0, 'errors': ['All students have sufficient attendance']}
        return self.send_bulk(recipients, 'attendance_alert')

    def batch_exam_schedule(self, course_id=None, exam_date=None, exam_time='10:00 AM', venue='Main Campus'):
        from app.models import Student, Course
        recipients = []
        courses = Course.query.all() if course_id is None else Course.query.filter_by(id=course_id).all()
        for c in courses:
            for s in c.students:
                if s.status == 'Active' and s.phone:
                    recipients.append((s.name, s.phone, {
                        'course': c.name,
                        'date': exam_date or date.today().strftime('%d %b %Y'),
                        'time': exam_time,
                        'venue': venue,
                    }))
        if not recipients:
            return {'sent': 0, 'failed': 0, 'errors': ['No active students found']}
        return self.send_bulk(recipients, 'exam_schedule')

    def run_all_batches(self):
        return {
            'fee_reminders': self.batch_fee_reminders(),
            'attendance_alerts': self.batch_attendance_alerts(),
        }
