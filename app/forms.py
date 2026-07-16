import re
from datetime import datetime


class Form:
    _fields = []

    def __init__(self, data=None):
        self.data = data if data is not None else {}
        self.errors = []
        self.cleaned_data = {}

    def validate(self):
        self.errors = []
        self.cleaned_data = {}
        required = getattr(self, 'required', [])
        email_fields = getattr(self, 'email', [])
        phone_fields = getattr(self, 'phone', [])
        integer_fields = getattr(self, 'integer', [])
        float_fields = getattr(self, 'float', [])
        date_fields = getattr(self, 'date', [])
        choice_fields = getattr(self, 'choices', {})
        min_values = getattr(self, 'min', {})
        max_values = getattr(self, 'max', {})
        max_lengths = getattr(self, 'max_length', {})
        regex_patterns = getattr(self, 'regex', {})

        for field in required:
            raw = self.data.get(field)
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                self._error(field, f'{field.replace("_", " ").title()} is required')

        for field in email_fields:
            raw = self.data.get(field, '')
            if raw and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', str(raw)):
                self._error(field, 'Invalid email format')

        for field in phone_fields:
            raw = self.data.get(field, '')
            digits = re.sub(r'\D', '', str(raw))
            if raw and len(digits) < 10:
                self._error(field, 'Phone must have at least 10 digits')

        for field in integer_fields:
            raw = self.data.get(field)
            if raw is not None and raw != '':
                try:
                    self.cleaned_data[field] = int(raw)
                except (ValueError, TypeError):
                    self._error(field, f'{field.replace("_", " ").title()} must be a number')

        for field in float_fields:
            raw = self.data.get(field)
            if raw is not None and raw != '':
                try:
                    val = float(raw)
                    self.cleaned_data[field] = val
                except (ValueError, TypeError):
                    self._error(field, f'{field.replace("_", " ").title()} must be a number')

        for field in date_fields:
            raw = self.data.get(field)
            if raw:
                try:
                    self.cleaned_data[field] = datetime.strptime(str(raw), '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    self._error(field, f'Invalid date format for {field.replace("_", " ").title()} (use YYYY-MM-DD)')

        for field, allowed in choice_fields.items():
            raw = self.data.get(field)
            if raw and str(raw) not in allowed:
                self._error(field, f'{field.replace("_", " ").title()} must be one of: {", ".join(allowed)}')

        for field, limit in min_values.items():
            raw = self.data.get(field)
            if raw is not None and raw != '':
                try:
                    if float(raw) < limit:
                        self._error(field, f'{field.replace("_", " ").title()} must be at least {limit}')
                except (ValueError, TypeError):
                    pass

        for field, limit in max_values.items():
            raw = self.data.get(field)
            if raw is not None and raw != '':
                try:
                    if float(raw) > limit:
                        self._error(field, f'{field.replace("_", " ").title()} must be at most {limit}')
                except (ValueError, TypeError):
                    pass

        for field, limit in max_lengths.items():
            raw = self.data.get(field, '')
            if raw and len(str(raw)) > limit:
                self._error(field, f'{field.replace("_", " ").title()} must be at most {limit} characters')

        for field, pattern in regex_patterns.items():
            raw = self.data.get(field, '')
            if raw and not re.match(pattern, str(raw)):
                self._error(field, f'{field.replace("_", " ").title()} has an invalid format')

        return len(self.errors) == 0

    def _error(self, field, message):
        self.errors.append({'field': field, 'message': message})

    @property
    def error_messages(self):
        return [e['message'] for e in self.errors]

    @property
    def error_dict(self):
        result = {}
        for e in self.errors:
            result.setdefault(e['field'], []).append(e['message'])
        return result


class StudentForm(Form):
    required = ['name', 'email', 'phone']
    email = ['email']
    phone = ['phone']
    integer = ['courses']
    choices = {'status': ['Active', 'Inactive', 'Archived']}
    max_length = {'name': 100, 'email': 100, 'phone': 20}
    regex = {'email': r'^[^@\s]+@[^@\s]+\.[^@\s]+$'}


class TutorForm(Form):
    required = ['name', 'email', 'phone']
    email = ['email']
    phone = ['phone']
    choices = {'status': ['Active', 'Inactive']}
    max_length = {'name': 100, 'email': 100, 'phone': 20, 'specialization': 100}


class CourseForm(Form):
    required = ['name', 'code', 'duration_weeks', 'fees']
    float = ['fees']
    integer = ['duration_weeks']
    choices = {'duration_unit': ['weeks', 'months', 'days']}
    min_values = {'fees': 0, 'duration_weeks': 0}
    max_length = {'name': 100, 'code': 20}
    regex = {'code': r'^[A-Za-z0-9_-]+$'}


class RegistrationForm(Form):
    required = ['name', 'username', 'password', 'confirm_password']
    email = ['email']
    max_length = {'name': 100, 'username': 50, 'email': 100}

    def validate(self):
        base_valid = super().validate()
        pw = self.data.get('password', '')
        cpw = self.data.get('confirm_password', '')
        if pw and len(pw) < 6:
            self._error('password', 'Password must be at least 6 characters')
        if pw != cpw:
            self._error('confirm_password', 'Passwords do not match')
        return len(self.errors) == 0


class LoginForm(Form):
    required = ['username', 'password']


class ForgotPasswordForm(Form):
    required = ['username', 'email']
    email = ['email']

    def validate(self):
        base_valid = super().validate()
        npw = self.data.get('new_password', '')
        cpw = self.data.get('confirm_password', '')
        if npw and len(npw) < 6:
            self._error('new_password', 'Password must be at least 6 characters')
        if cpw and npw != cpw:
            self._error('confirm_password', 'Passwords do not match')
        return len(self.errors) == 0


class FeeForm(Form):
    required = ['student_id', 'amount_paid']
    integer = ['student_id']
    float = ['amount_paid']
    date = ['payment_date']
    choices = {'payment_method': ['Cash', 'UPI', 'Bank Transfer', 'Card', 'Cheque', 'Online']}
    min_values = {'amount_paid': 0, 'student_id': 1}
    max_length = {'remarks': 200}


class ExpenseForm(Form):
    required = ['category_id', 'amount', 'description']
    integer = ['category_id']
    float = ['amount']
    date = ['expense_date']
    min_values = {'amount': 0, 'category_id': 1}


class EnquiryForm(Form):
    required = ['student_name', 'phone', 'course_id']
    phone = ['phone']
    email = ['email']
    integer = ['course_id']
    choices = {'source': ['Walk-in', 'Phone', 'Google Form', 'Referral', 'Social Media', 'Website', 'Other'],
               'status': ['New', 'Contacted', 'Converted', 'Lost']}
    min_values = {'course_id': 1}
    max_length = {'student_name': 100, 'email': 100, 'phone': 20}


class LeaveForm(Form):
    required = ['start_date', 'end_date', 'reason']
    date = ['start_date', 'end_date']

    def validate(self):
        base_valid = super().validate()
        sd = self.cleaned_data.get('start_date')
        ed = self.cleaned_data.get('end_date')
        if sd and ed and sd > ed:
            self._error('end_date', 'End date must be on or after start date')
        return len(self.errors) == 0


class ExamForm(Form):
    required = ['course_id', 'title', 'exam_date', 'max_marks', 'passing_marks']
    integer = ['course_id']
    float = ['max_marks', 'passing_marks']
    date = ['exam_date']
    min_values = {'max_marks': 1, 'passing_marks': 0, 'course_id': 1}
    max_length = {'title': 200}


class AttendanceMarkForm(Form):
    required = ['person_type', 'person_id', 'status']
    integer = ['person_id']
    choices = {'person_type': ['student', 'tutor'], 'status': ['Present', 'Absent', 'Late', 'Half Day']}


class PayrollProcessForm(Form):
    required = ['tutor_id', 'month', 'year']
    integer = ['tutor_id', 'month', 'year']
    min_values = {'month': 1, 'year': 2000}
    max_values = {'month': 12}


class PayrollSettingsForm(Form):
    float = ['base_salary', 'commission_percentage', 'tds_percentage', 'bonus', 'other_deductions']
    min_values = {'base_salary': 0, 'commission_percentage': 0, 'tds_percentage': 0, 'bonus': 0, 'other_deductions': 0}
    max_length = {'bank_name': 100, 'account_number': 50, 'ifsc_code': 20}
