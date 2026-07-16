# Google Forms Integration — Guha Academy

## Architecture

```
Google Forms (3 forms)
     ↓ submit
Google Sheets (response sheets)
     ↓ onFormSubmit trigger
Google Apps Script (automation)
     ├── Email confirmation (student)
     ├── Faculty notification
     ├── Calendar event creation
     └── Weekly summary report
     ↓ (optional)
Flask webhook → local SQLite (in-app dashboards)
```

---

## Step 1 — Create the 3 Google Forms

### 1A — Admission Form
| Field | Type |
|-------|------|
| Student Name | Short answer |
| Email | Short answer |
| Phone | Short answer |
| Course | Dropdown (list all courses) |
| Guardian Phone | Short answer |
| Address | Paragraph |
| Batch Timing | Dropdown (Morning/Evening/Weekend) |

### 1B — Attendance Form
| Field | Type |
|-------|------|
| Student Email | Short answer |
| Date | Date |
| Status | Multiple choice (Present/Absent) |
| Batch | Dropdown |
| Faculty Name | Short answer |

### 1C — Feedback Form
| Field | Type |
|-------|------|
| Student Email | Short answer |
| Course | Dropdown |
| Faculty | Dropdown |
| Rating | Linear scale (1–5) |
| Comments | Paragraph |

**For each form**: Responses tab → green Sheets icon → Create new spreadsheet.

---

## Step 2 — Apps Script Automation

Open the response sheet: **Extensions → Apps Script**.

Paste the unified script below into `Code.gs`:

```javascript
// === ADMISSION ===
function onAdmissionSubmit(e) {
  var r = e.values;
  var name = r[1], email = r[2], course = r[3];

  // Confirmation email
  GmailApp.sendEmail(email,
    'Welcome to Guha Academy – Admission Confirmed',
    'Dear ' + name + ',\n\nYour admission for ' + course + ' is confirmed.\n'
    + 'Batch timing and orientation details will follow.\n\nRegards,\nAdmissions – Guha Academy'
  );

  // Admin alert
  GmailApp.sendEmail('admin@guha.academy',
    'New Admission: ' + name,
    'Course: ' + course + '\nPhone: ' + r[4] + '\nCheck sheet for details.'
  );

  // (Optional) POST to Flask webhook
  var payload = { name: name, email: email, course: course, phone: r[4] };
  UrlFetchApp.fetch('https://your-domain.com/api/google-form/webhook', {
    method: 'POST',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });
}

// === ATTENDANCE ===
function onAttendanceSubmit(e) {
  var r = e.values;
  var student = r[1], status = r[3], faculty = r[5], batch = r[4];

  if (status === 'Absent') {
    GmailApp.sendEmail(faculty + '@guha.academy',
      'Absent Alert – ' + student,
      'Student: ' + student + '\nBatch: ' + batch + '\nDate: ' + r[2]
    );
  }
}

// === FEEDBACK WEEKLY REPORT ===
function generateFeedbackReport() {
  var ss = SpreadsheetApp.getActive();
  var sheet = ss.getSheetByName('Feedback');
  var data = sheet.getDataRange().getValues();
  var map = {};

  for (var i = 1; i < data.length; i++) {
    var course = data[i][2], rating = Number(data[i][4]);
    if (!map[course]) map[course] = { sum: 0, count: 0 };
    map[course].sum += rating;
    map[course].count++;
  }

  // Create summary sheet
  var dateStr = new Date().toISOString().slice(0, 10);
  var summary = ss.insertSheet('Summary_' + dateStr);
  summary.appendRow(['Course', 'Avg Rating', 'Responses']);
  for (var c in map)
    summary.appendRow([c, (map[c].sum / map[c].count).toFixed(2), map[c].count]);

  // Email XLSX report
  var url = 'https://docs.google.com/spreadsheets/d/' + ss.getId() + '/export?format=xlsx';
  var blob = UrlFetchApp.fetch(url, {
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() }
  }).getBlob('feedback_report.xlsx');

  GmailApp.sendEmail('admin@guha.academy',
    'Feedback Summary – ' + dateStr,
    'See attached weekly feedback report.',
    { attachments: [blob] }
  );
}

// === CALENDAR — Lab Scheduling ===
function scheduleLabBatch() {
  var sheet = SpreadsheetApp.getActiveSheet();
  var data = sheet.getDataRange().getValues();
  var cal = CalendarApp.getCalendarById('primary');

  for (var i = 1; i < data.length; i++) {
    if (data[i][7] === 'Scheduled') continue;
    var name = data[i][1], timing = data[i][6], course = data[i][3];
    if (!timing) continue;

    var now = new Date();
    var start = new Date(now.getFullYear(), now.getMonth(), now.getDate(),
                         parseInt(timing), 0, 0);
    var end = new Date(start.getTime() + 60 * 60 * 1000);

    cal.createEvent('Lab: ' + name + ' (' + course + ')', start, end);
    sheet.getRange(i + 1, 8).setValue('Scheduled');
  }
}
```

### Set Up Triggers

| Function | Trigger Type | Event |
|----------|-------------|-------|
| `onAdmissionSubmit` | On form submit | Admissions form |
| `onAttendanceSubmit` | On form submit | Attendance form |
| `generateFeedbackReport` | Time-driven (weekly) | Sunday 8 PM |
| `scheduleLabBatch` | Time-driven (daily) | Midnight |

**How**: Script Editor → clock icon (Triggers) → Add Trigger → select function and event.

---

## Step 3 — Optional: Flask Webhook

If you want form submissions to appear in the in-app dashboard:

```python
# Add to app.py
@app.route('/api/google-form/webhook', methods=['POST'])
def google_form_webhook():
    data = request.json
    # Map form field names to your model
    student = Student(
        name=data.get('name'),
        email=data.get('email'),
        phone=data.get('phone'),
        # course_id = resolve from data.get('course')
    )
    db.session.add(student)
    db.session.commit()
    return jsonify({'status': 'ok'}), 200
```

Then uncomment the `UrlFetchApp.fetch` call in `onAdmissionSubmit` above, replacing `https://your-domain.com` with your server URL (use ngrok for development).

---

## Step 4 — Export to Excel / Power BI

| Method | Steps |
|--------|-------|
| **Manual** | Google Sheets → File → Download → Microsoft Excel (.xlsx) |
| **Power BI** | Get Data → Google Sheets → authenticate → select sheet |
| **Auto email** | `generateFeedbackReport()` sends weekly `.xlsx` to admin |
| **Power Automate** | Connector: Google Sheets → When a row is added → Export to SharePoint/OneDrive |

---

## IDs You'll Need

| Item | Where to find |
|------|---------------|
| Sheet ID | From URL: `docs.google.com/spreadsheets/d/`**`THIS_PART`**`/edit` |
| Calendar ID | Google Calendar → Settings → Integrate → Calendar ID |
| OAuth scope | Add `https://www.googleapis.com/auth/calendar` in Script Editor → Project Settings → Scopes |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "You do not have permission to call GmailApp" | Script Editor → run function once → accept permissions |
| Calendar event not created | Enable Calendar API in Google Cloud Console, add scope |
| Webhook 404 | Server not running / wrong URL — test with `curl` first |
| Duplicate emails | Check trigger is set to "On form submit" not "On change" |

---

## Files

- Forms: 3 Google Forms (Admission, Attendance, Feedback)
- Script: Apps Script attached to the response spreadsheet
- Server: Flask webhook endpoint (optional)
