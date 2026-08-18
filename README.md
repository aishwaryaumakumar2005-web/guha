# Guha Academy — Institute Management System

A Flask-based web application for managing a computer institute: students, tutors, courses, attendance, fees, expenses, enquiries, leaves, reports, and extras (dark mode, auto-backup, Excel export).

---

## Quick Start

### Prerequisites
- Python 3.10+
- pip

### Windows
```batch
run.bat
```

### Linux / macOS
```bash
chmod +x run.sh
./run.sh
```

### Manual Setup

```bash
# 1. Clone / extract the project
cd institute

# 2. Install dependencies
pip install -r requirements.txt

# 3. Seed the database (creates tables + sample data)
python init_db.py

# 4. Start the server
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

---

## Default Logins

| Role  | Username | Password |
|-------|----------|----------|
| Admin | `admin`  | `admin123` |
| Staff | `staff`  | `staff123` |

---

## Features

| Module | Description |
|--------|-------------|
| **Dashboard** | Stats cards, revenue chart, recent fees, AI advisor (Admin), quick ops (Staff) |
| **Students** | CRUD, ID card generation, search |
| **Tutors** | CRUD, specialisation, AI quiz generator |
| **Courses** | CRUD, syllabus, fees |
| **Enquiries** | Pipeline management (New → Contacted → Converted) |
| **Fees** | Add/view fee records per student |
| **Expenses** | Category CRUD, expense tracking |
| **Attendance** | Manual mark + QR scanner |
| **Leaves** | Staff leave requests, Admin approval |
| **Reports** | Income/Fees/Expense/Overall tabs, charts, PDF + Excel download, date/quarterly filters |
| **Extras** | Dark mode toggle, auto-backup + manual backup/restore |
| **Admin Console** | DB counts overview |

---

## Project Structure

```
institute/
├── app.py              # Flask application (routes, logic)
├── models.py           # SQLAlchemy models
├── ai_engine.py        # AI advisor engine
├── init_db.py          # Database seeder
├── requirements.txt    # Python dependencies
├── run.bat             # Windows launcher
├── run.sh              # Linux/macOS launcher
├── instance/
│   └── institute.db    # SQLite database (auto-created)
├── static/
│   ├── css/styles.css  # Stylesheet (light + dark mode)
│   └── js/app.js       # Client-side JS
├── templates/          # Jinja2 HTML templates
│   ├── base.html       # Layout (sidebar, dark mode toggle)
│   ├── login.html      # Login page
│   ├── dashboard.html
│   ├── students.html
│   ├── tutors.html
│   ├── courses.html
│   ├── enquiries.html
│   ├── fees.html
│   ├── expenses.html
│   ├── attendance.html
│   ├── leaves.html
│   ├── reports.html
│   ├── extras.html
│   └── admin.html
├── backups/            # Auto-backup & manual backup files
└── README.md
```

---

## Database

The app uses SQLite (`instance/institute.db`).  
Tables are created automatically on first run via `db.create_all()` in `app.py`.

To reset the database:
```bash
del instance\institute.db      # Windows
rm instance/institute.db       # Linux/macOS
python init_db.py
```

---

## Reports

Access at **Reports** tab in the sidebar.

| Tab | Charts | PDF | Excel |
|-----|--------|-----|-------|
| Income | Monthly bar + cumulative line | ✓ | ✓ |
| Fees | Monthly bar + payment doughnut + course doughnut + daily sparkline | ✓ | ✓ |
| Expense | Monthly bar + category doughnut + trend line | ✓ | ✓ |
| Overall | P&L bar + net trend line + P&L table | ✓ | ✓ |

Filter by month, quarter, or custom date range.

---

## Dark Mode

Click the moon/sun icon in the sidebar footer. Preference is saved in `localStorage`.

---

## Backups

- **Auto-backup**: Runs daily on first page load via `@before_request`
- **Manual backup**: `Extras → Backup Now`
- **Restore**: `Extras → Choose a backup → Restore`
- Location: `institute/backups/*.db`

---

## Google Form Integration (Optional)

See detailed workflow in `docs/google_forms_integration.md`.

---

## Technology Stack

- **Backend**: Python, Flask, SQLAlchemy
- **Frontend**: Bootstrap 5, Chart.js, HTML5 QR Scanner
- **Database**: SQLite
- **Reporting**: fpdf2 (PDF), openpyxl (Excel)
- **Auth**: Flask-Login

---

## License

Internal use — Guha Academy
