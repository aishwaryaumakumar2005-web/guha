# Admin Guide — Guha Academy

## Running the Application

### Option 1: One-click (Windows)
Double-click **`run.bat`** — it installs deps, seeds the DB, and starts the server.

### Option 2: Manual
```bash
pip install -r requirements.txt
python init_db.py
python app.py
```

The server starts at **http://127.0.0.1:5000**.

---

## Default Accounts

| Role  | Username | Password | URL |
|-------|----------|----------|-----|
| Admin | `admin`  | `admin123` | Dashboard + all modules |
| Staff | `staff`  | `staff123` | Dashboard, Attendance, Leaves |

---

## Module Overview

| Page | URL | Who can access |
|------|-----|---------------|
| Dashboard | `/` | All |
| Students | `/students` | Admin |
| Tutors | `/tutors` | Admin |
| Courses | `/courses` | Admin |
| Enquiries | `/enquiries` | Admin |
| Fees | `/fees` | Admin |
| Expenses | `/expenses` | Admin |
| Reports | `/reports` | Admin |
| Attendance | `/attendance` | All |
| Leaves | `/leaves` | All |
| Extras | `/extras` | All |
| Admin Console | `/admin` | Admin |

---

## Database

- **Location**: `instance/institute.db`
- **Technology**: SQLite (no separate DB server needed)
- **Reset**: Delete the file and run `python init_db.py`
- **Backup**: Auto-backup runs daily. Manual: Extras → Backup Now

### Schema Overview

```
User ──┬── Student
       ├── Tutor
       ├── Attendance
       ├── FeeRecord
       ├── LeaveRequest
       └── Enquiry

Course ── student_courses (M2M) ── Student
ExpenseCategory ─── Expense
```

---

## Reports

**URL**: `/reports`

| Tab | Charts | Download |
|-----|--------|----------|
| Income | Monthly bar, Cumulative line | PDF, Excel |
| Fees | Monthly bar, Payment doughnut, Course doughnut, Daily sparkline | PDF, Excel |
| Expense | Monthly bar, Category doughnut, Trend line | PDF, Excel |
| Overall | P&L bar, Net trend line, P&L table | PDF, Excel |

Filter by: Month, Quarter, or Custom date range.

---

## Extra Features

### Dark Mode
Click moon/sun icon in sidebar footer. Preference saved per-browser.

### Auto-Backup
Runs daily on first page visit. Backups stored in `backups/` folder.

### Manual Backup
Extras → Backup Now → creates timestamped `.db` copy.

### Restore
Extras → select backup from list → Restore → reloads that `.db`.

---

## Google Forms Integration

See `docs/google_forms_integration.md` for full guide.

Quick steps:
1. Create 3 Google Forms (Admission, Attendance, Feedback)
2. Link each to a Google Sheet
3. Add Apps Script triggers for email alerts + calendar scheduling
4. (Optional) Flask webhook for in-app sync

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `pip` not found | Install Python 3.10+ and ensure it's in PATH |
| Port 5000 in use | Edit `app.py` line 1753: change `port=5000` |
| "No module named ..." | Run `pip install -r requirements.txt` |
| Login doesn't work | Run `python init_db.py` to seed default users |
| Blank page / 500 error | Check terminal for traceback; ensure DB isn't corrupted |
| Charts not visible | Hard refresh (Ctrl+F5) or clear browser cache |
| Dark mode not working | Hard refresh (CSS is cached) |
| PDF download fails | Ensure `fpdf2` is installed |
| Excel download fails | Ensure `openpyxl` is installed |

---

## File Structure

```
institute/
├── app.py
├── models.py
├── ai_engine.py
├── init_db.py
├── requirements.txt
├── run.bat / run.sh
├── README.md
├── instance/institute.db
├── static/
│   ├── css/styles.css
│   └── js/app.js
├── templates/ (14 HTML files)
├── backups/
└── docs/
    ├── google_forms_integration.md
    └── admin_guide.md
```
