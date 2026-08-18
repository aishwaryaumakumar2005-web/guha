import requests
import re
from datetime import datetime, timedelta, date


class SmsService:
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
            'sms_gateway_url': val('SMS_GATEWAY_URL'),
            'sms_api_key': val('SMS_API_KEY'),
            'sms_sender_id': val('SMS_SENDER_ID'),
            'sms_phone_param': val('SMS_PHONE_PARAM') or 'mobile',
            'sms_msg_param': val('SMS_MSG_PARAM') or 'message',
            'sms_key_param': val('SMS_KEY_PARAM') or 'api_key',
            'sms_sender_param': val('SMS_SENDER_PARAM') or 'sender',
            'sms_method': val('SMS_METHOD') or 'GET',
        }

    def send_sms(self, phone, message):
        cfg = self._get_settings()
        url = cfg['sms_gateway_url']
        if not url or not phone:
            return False

        digits = re.sub(r'\D', '', phone)
        if len(digits) == 10:
            pass
        elif len(digits) > 10:
            digits = digits[-10:]
        else:
            return False

        params = {
            cfg['sms_phone_param']: digits,
            cfg['sms_msg_param']: message,
        }
        if cfg['sms_api_key']:
            params[cfg['sms_key_param']] = cfg['sms_api_key']
        if cfg['sms_sender_id']:
            params[cfg['sms_sender_param']] = cfg['sms_sender_id']

        try:
            if cfg['sms_method'].upper() == 'POST':
                resp = requests.post(url, data=params, timeout=15)
            else:
                resp = requests.get(url, params=params, timeout=15)
            return resp.ok
        except requests.RequestException:
            return False

    def _format_phone(self, raw):
        digits = re.sub(r'\D', '', raw)
        return digits[-10:] if len(digits) >= 10 else raw

    def send_fee_reminder(self, student_name, phone, amount_due, due_date):
        msg = (
            f"Fee Reminder - Guha Academy\n"
            f"Dear {student_name},\n"
            f"Your outstanding balance is Rs.{amount_due:,.0f}.\n"
            f"Please clear it by {due_date} to avoid late fees.\n"
            f"Thank you."
        )
        return self.send_sms(phone, msg)

    def send_attendance_alert(self, student_name, phone, course_name, percentage):
        msg = (
            f"Attendance Alert - Guha Academy\n"
            f"Dear {student_name},\n"
            f"Your attendance in {course_name} is only {percentage}%.\n"
            f"Regular attendance is essential. Please improve.\n"
            f"Thank you."
        )
        return self.send_sms(phone, msg)

    def send_exam_schedule(self, student_name, phone, course_name, exam_date, exam_time, venue):
        msg = (
            f"Exam Schedule - Guha Academy\n"
            f"Dear {student_name},\n"
            f"Course: {course_name}\n"
            f"Date: {exam_date}\n"
            f"Time: {exam_time}\n"
            f"Venue: {venue}\n"
            f"Best of luck!"
        )
        return self.send_sms(phone, msg)

    def send_test(self, phone):
        return self.send_sms(phone, "Test SMS from Guha Academy. Your SMS gateway is configured correctly.")

    def send_bulk(self, recipients, message_type, **kwargs):
        results = {'sent': 0, 'failed': 0, 'errors': []}
        for name, phone, extra in recipients:
            phone = self._format_phone(phone)
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
