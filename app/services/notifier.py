import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime, timedelta, date


class Notifier:
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
            'smtp_server': val('SMTP_SERVER'),
            'smtp_port': int(val('SMTP_PORT') or 587),
            'smtp_use_tls': val('SMTP_USE_TLS') != '0',
            'smtp_username': val('SMTP_USERNAME'),
            'smtp_password': val('SMTP_PASSWORD'),
            'from_email': val('FROM_EMAIL'),
            'from_name': val('FROM_NAME') or 'Guha Academy',
            'admin_email': val('ADMIN_EMAIL'),
        }

    def _send_email(self, to_email, subject, html_body):
        if not to_email:
            return False
        cfg = self._get_settings()
        if not cfg['smtp_server'] or not cfg['from_email']:
            return False
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = f"{cfg['from_name']} <{cfg['from_email']}>"
        msg['To'] = to_email
        msg.set_content(f"Please view this email in HTML mode.\n\n{subject}")
        msg.add_alternative(html_body, subtype='html')
        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(cfg['smtp_server'], cfg['smtp_port'], timeout=15) as server:
                if cfg['smtp_use_tls']:
                    server.starttls(context=ctx)
                if cfg['smtp_username']:
                    server.login(cfg['smtp_username'], cfg['smtp_password'])
                server.send_message(msg)
            return True
        except Exception as e:
            print(f"Email send failed to {to_email}: {e}")
            return False

    def send_test(self, to_email):
        return self._send_email(to_email, "Test Email from Guha Academy",
            "<h2>SMTP Configuration Verified</h2><p>Your email settings are working correctly.</p>")

    def check_low_attendance(self):
        from app.models import Student, Attendance, SystemSetting
        cfg = self._get_settings()
        admin_email = cfg['admin_email']
        if not admin_email:
            return 0
        thirty_days_ago = date.today() - timedelta(days=30)
        alerts = []
        students = Student.query.filter_by(status='Active').all()
        for s in students:
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
            if pct < 60:
                alerts.append((s, pct, total, present))
        if not alerts:
            self._send_email(admin_email, "Attendance OK - Guha Academy",
                "<p>All active students have sufficient attendance this month.</p>")
            return 0
        rows = ''.join(
            f'<tr><td>{s.name}</td><td>{s.email}</td><td>{pct}%</td><td>{present}/{total}</td></tr>'
            for s, pct, total, present in alerts
        )
        html = f"""
        <h2>Low Attendance Alert</h2>
        <p>The following students have attendance below 60% in the last 30 days:</p>
        <table border="1" cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%">
        <tr style="background:#0d2740;color:white"><th>Student</th><th>Email</th><th>Attendance %</th><th>Present/Total</th></tr>
        {rows}
        </table>
        """
        self._send_email(admin_email, f"Low Attendance Alert - {len(alerts)} Student(s)", html)
        return len(alerts)

    def check_fee_due(self):
        from app.models import Student, FeeRecord, SystemSetting
        cfg = self._get_settings()
        admin_email = cfg['admin_email']
        if not admin_email:
            return 0
        reminders = []
        students = Student.query.filter_by(status='Active').all()
        for s in students:
            total_fee = sum(c.fees for c in s.courses)
            total_paid = sum(r.amount_paid for r in s.fee_records)
            balance = total_fee - total_paid
            if balance > 0:
                reminders.append((s, total_fee, total_paid, balance))
        if not reminders:
            return 0
        reminders.sort(key=lambda x: x[3], reverse=True)
        rows = ''.join(
            f'<tr><td>{s.name}</td><td>{s.email}</td><td>₹{fee:,.0f}</td><td>₹{paid:,.0f}</td><td style="color:{"red" if bal>0 else "green"}">₹{bal:,.0f}</td></tr>'
            for s, fee, paid, bal in reminders[:50]
        )
        total_due = sum(b for _, _, _, b in reminders)
        html = f"""
        <h2>Fee Due Summary</h2>
        <p>Total outstanding: <strong>₹{total_due:,.0f}</strong> across {len(reminders)} student(s).</p>
        <table border="1" cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%">
        <tr style="background:#0d2740;color:white"><th>Student</th><th>Email</th><th>Total Fee</th><th>Paid</th><th>Balance</th></tr>
        {rows}
        </table>
        <p style="margin-top:16px;color:#666;">This is an automated reminder from Guha Academy.</p>
        """
        self._send_email(admin_email, f"Fee Due Reminder - ₹{total_due:,.0f} Outstanding", html)
        return len(reminders)

    def check_enquiry_followups(self):
        from app.models import Enquiry, SystemSetting
        cfg = self._get_settings()
        admin_email = cfg['admin_email']
        if not admin_email:
            return 0
        cutoff = datetime.utcnow() - timedelta(days=3)
        stale = Enquiry.query.filter(
            Enquiry.status.in_(['New', 'Contacted']),
            Enquiry.created_at < cutoff
        ).order_by(Enquiry.created_at.asc()).all()
        if not stale:
            return 0
        rows = ''.join(
            f'<tr><td>{e.student_name}</td><td>{e.email or "N/A"}</td><td>{e.phone}</td><td>{e.status}</td><td>{e.created_at.strftime("%d %b %Y")}</td></tr>'
            for e in stale
        )
        html = f"""
        <h2>Enquiry Follow-up Reminder</h2>
        <p>{len(stale)} enquiry(ies) have not been contacted in over 3 days:</p>
        <table border="1" cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%">
        <tr style="background:#0d2740;color:white"><th>Name</th><th>Email</th><th>Phone</th><th>Status</th><th>Created</th></tr>
        {rows}
        </table>
        """
        self._send_email(admin_email, f"Enquiry Follow-up Needed - {len(stale)} Pending", html)
        return len(stale)

    def run_all_checks(self):
        return {
            'attendance_alerts': self.check_low_attendance(),
            'fee_reminders': self.check_fee_due(),
            'enquiry_followups': self.check_enquiry_followups(),
        }
