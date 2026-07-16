# Guha Institute Management System — User Manual

> **Version:** 1.0  
> **Last Updated:** June 2026

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Getting Started](#2-getting-started)
   - 2.1 [Logging In](#21-logging-in)
   - 2.2 [First Time Setup — Registration](#22-first-time-setup--registration)
   - 2.3 [Forgot Password](#23-forgot-password)
   - 2.4 [User Roles: Admin vs Staff](#24-user-roles-admin-vs-staff)
3. [The Dashboard](#3-the-dashboard)
   - 3.1 [Overview Cards](#31-overview-cards)
   - 3.2 [Charts & Graphs](#32-charts--graphs)
   - 3.3 [AI Institute Advisor](#33-ai-institute-advisor)
   - 3.4 [Predictive Analytics (Admin Only)](#34-predictive-analytics-admin-only)
4. [Sidebar Navigation](#4-sidebar-navigation)
   - 4.1 [Sidebar Layout](#41-sidebar-layout)
   - 4.2 [Global Search](#42-global-search)
   - 4.3 [Dark Mode](#43-dark-mode)
5. [Academic Section](#5-academic-section)
   - 5.1 [Students](#51-students)
   - 5.2 [Courses](#52-courses)
   - 5.3 [Staff (Tutors)](#53-staff-tutors)
   - 5.4 [Attendance](#54-attendance)
   - 5.5 [Exams](#55-exams)
   - 5.6 [Leaves](#56-leaves)
6. [Finance Section](#6-finance-section)
   - 6.1 [Fees & Ledger](#61-fees--ledger)
   - 6.2 [Expenses](#62-expenses)
   - 6.3 [Payroll](#63-payroll)
   - 6.4 [Enquiries](#64-enquiries)
   - 6.5 [Salary Calculator](#65-salary-calculator)
7. [Analytics Section](#7-analytics-section)
   - 7.1 [Reports](#71-reports)
   - 7.2 [Google Sync](#72-google-sync)
8. [Extra Features](#8-extra-features)
9. [Admin Console](#9-admin-console)
   - 9.1 [AI Engine Keys](#91-ai-engine-keys)
   - 9.2 [SMTP (Email) Settings](#92-smtp-email-settings)
   - 9.3 [WhatsApp Settings](#93-whatsapp-settings)
   - 9.4 [SMS Gateway Settings](#94-sms-gateway-settings)
   - 9.5 [Organization & GST Settings](#95-organization--gst-settings)
   - 9.6 [User Management](#96-user-management)
   - 9.7 [Database Backup & Restore](#97-database-backup--restore)
10. [AI Chatbot Assistant](#10-ai-chatbot-assistant)
11. [QR Code ID Cards & Attendance Scanning](#11-qr-code-id-cards--attendance-scanning)
12. [Accounting & GST](#12-accounting--gst)
    - 12.1 [GST Invoice](#121-gst-invoice)
    - 12.2 [Tally Export](#122-tally-export)
    - 12.3 [Zoho Books Export](#123-zoho-books-export)
13. [Importing from Excel](#13-importing-from-excel)
14. [Reports & Downloads](#14-reports--downloads)
15. [Tips & Shortcuts](#15-tips--shortcuts)
16. [Troubleshooting](#16-troubleshooting)

---

## 1. Introduction

Welcome to **Guha Institute Management System**! This is a web-based software that helps you run your educational institute smoothly. It handles everything from enrolling students, managing courses, tracking attendance, collecting fees, paying staff salaries, and much more.

This manual explains every feature in simple language so that anyone — even if you're not tech-savvy — can use the system confidently.

---

## 2. Getting Started

### 2.1 Logging In

1. Open your web browser (Chrome, Edge, or Firefox).
2. Go to the web address where the system is hosted (e.g., `http://localhost:5000` or your institute's URL).
3. You will see the **Login Page**.
4. Enter your **Username** and **Password**.
5. Click the **"Sign In"** button.
6. If the details are correct, you will be taken to the **Dashboard**.

**Default logins (for testing):**

| Username | Password | Role |
|---|---|---|
| `admin` | `admin123` | Admin |
| `staff` | `staff123` | Staff |

> **Tip:** Change your password after first login.

---

### 2.2 First Time Setup — Registration

If you are a new staff member and do not have a login yet:

1. Click **"Create Account"** link on the login page.
2. Fill in:
   - **Username** — a unique name for login (e.g., `john_doe`)
   - **Name** — your full name
   - **Email** — your email address
   - **Password** — choose a strong password
3. Click **"Register"**.
4. You can now log in with your new username.

---

### 2.3 Forgot Password

If you forget your password:

1. Click **"Forgot Password?"** on the login page.
2. Step 1 — Enter your **Username** and **Email**. Click **"Verify Identity"**.
3. Step 2 — Enter your new password. Click **"Reset Password"**.
4. Log in with your new password.

---

### 2.4 User Roles: Admin vs Staff

The system has two types of users:

| Feature | Admin | Staff |
|---|---|---|
| View Dashboard | ✅ Yes | ✅ Yes (limited view) |
| Manage Students, Courses, Staff | ✅ Yes | ❌ No |
| Manage Fees, Expenses, Payroll | ✅ Yes | ❌ No |
| Mark Attendance | ✅ Yes | ✅ Yes (own courses) |
| Apply for Leave | ✅ Yes | ✅ Yes |
| View Reports | ✅ Yes | ❌ No |
| Admin Console (settings) | ✅ Yes | ❌ No |
| AI Features | ✅ Yes | ✅ Yes (limited) |
| AI Chatbot | ✅ Yes | ✅ Yes |

> **Note:** If you are a **Staff** member, you will only see the Dashboard, Attendance, Leaves, Extra Features, and the Chatbot. All other menu items are hidden.

---

## 3. The Dashboard

The **Dashboard** is the first page you see after logging in. It gives you a bird's eye view of your institute's health.

> ***(For Staff users, the dashboard shows a simpler view without financial data.)***

### 3.1 Overview Cards

At the top, you see several cards with numbers:

- **Active Students** — Total students currently enrolled
- **Staff** — Total tutors/instructors
- **Courses** — Total courses offered
- **Active Enquiries** — Total enquiries (potential students) still open
- **Monthly Fees Collected** — Total fees collected this month (Admin only)
- **Monthly Expenses** — Total expenses this month (Admin only)

### 3.2 Charts & Graphs

- **Revenue / Fees Trend** (6-month line chart) — Shows fees collected month-by-month
- **Weekly Attendance** (7-day bar chart) — Shows attendance percentage for the last 7 days
- **Recent Payments** — Latest fee payments recorded
- **Recent Enrollments** — Students enrolled recently
- **Top Courses by Enrollment** — Courses with the most students

### 3.3 AI Institute Advisor

On the right side of the dashboard (Admin only), you will see the **AI Institute Advisor** panel. This uses Artificial Intelligence to give you smart suggestions about your institute, such as:

- Which courses are performing well
- Attendance trends and areas of concern
- Fee collection patterns
- Recommendations to improve operations

Click **"Refresh Insights"** to get the latest AI analysis.

### 3.4 Predictive Analytics (Admin Only)

Below the AI Advisor, you will find **Predictive Analytics** — forecasts for the next 3 months, including:

- **Enrollment Forecast** — How many new students to expect
- **Revenue Forecast** — Expected fees collection
- **Growth Opportunities** — Areas where you can expand
- **Risk Factors** — Things to watch out for

Click **"Refresh Forecasts"** to update.

---

## 4. Sidebar Navigation

### 4.1 Sidebar Layout

The sidebar is the dark panel on the left side of the screen. It contains all the main sections organized in collapsible groups:

| Section | What's Inside |
|---|---|
| **Dashboard** | Main overview page |
| **Academic** | Students, Courses, Staff, Attendance, Exams, Leaves |
| **Finance** | Fees & Ledger, Expenses, Payroll, Enquiries, Salary Calculator |
| **Analytics** | Reports, Google Sync |
| **Extra Features** | Dark mode, database tools |
| **Admin Console** | All settings and configurations |

> Click on a group heading (e.g., "Academic") to expand or collapse it.

At the bottom of the sidebar you will see:
- Your **Name** and **Role**
- **Dark Mode** toggle (moon icon)
- **Logout** button (arrow icon)

### 4.2 Global Search

At the top of the main content area, you'll find the **Global Search** bar (marked with an amber "GLOBAL SEARCH" label).

- Type any keyword (minimum 2 letters) to search across:
  - **Students** (by name, email, or phone)
  - **Staff / Tutors** (by name, email, or phone)
  - **Courses** (by name or code)
  - **Enquiries** (by name, email, or phone)
- Results appear in a dropdown instantly as you type.
- Click on any result to go directly to that record.

### 4.3 Dark Mode

- Click the **moon/sun icon** at the bottom of the sidebar to toggle between light and dark mode.
- Your preference is saved automatically for next time.

---

## 5. Academic Section

### 5.1 Students

> **Note:** This section is only visible to Admin users.

The **Students** page lists all students enrolled in your institute.

#### Viewing Students
- The table shows: Name, Email, Phone, Enrollment Date, Status, and Actions.
- The table is **sortable** (click column headers) and **paginated** (10 students per page).

#### Enrolling a New Student
1. Click the **"Enroll Student"** button.
2. Fill in the form:
   - **Name** — Student's full name
   - **Email** — Student's email address
   - **Phone** — Contact number
   - **Courses** — Select one or more courses (use the searchable dropdown)
3. Click **"Enroll Student"**.

#### Editing a Student
1. Click the **pencil icon** (✏️) next to the student.
2. Update the details in the modal form.
3. Click **"Update Student"**.

#### Deleting a Student
1. Click the **trash icon** (🗑️) next to the student.
2. Confirm the deletion.

#### Printing ID Card
1. Click the **ID card icon** next to the student.
2. The ID card modal will open with a QR code and student details.
3. Click **"Print ID Card"** to print.

#### Excel Import
1. Click **"Import from Excel"**.
2. Upload an Excel file (`.xlsx` or `.xls`).
3. The system validates the data using AI and suggests course mappings.
4. Confirm the import.

> **See also:** [Importing from Excel](#13-importing-from-excel)

---

### 5.2 Courses

> **Note:** This section is only visible to Admin users.

The **Courses** page displays all courses / classes offered.

#### Viewing Courses
- Each course card shows: Name, Code, Duration, Fees, Enrolled Students count.

#### Creating a New Course
1. Click the **"Create Course"** button.
2. Fill in:
   - **Name** — e.g., "Python Programming"
   - **Code** — Short code, e.g., "PYTHON101"
   - **Description** — What the course covers
   - **Duration** — Number of weeks/months
   - **Fees** — Course fee amount
   - **Syllabus** — Topics covered (optional)
3. Click **"Create Course"**.

#### Editing a Course
1. Click the **pencil icon** on the course card.
2. Update the fields.
3. Click **"Update Course"**.

#### Deleting a Course
1. Click the **trash icon** on the course card.
2. Confirm deletion.

> **Note:** Deleting a course will also remove all associated exam records.

---

### 5.3 Staff (Tutors)

> **Note:** This section is only visible to Admin users.

The **Staff** page manages all instructors/tutors.

#### Adding a Staff Member
1. Click **"Add Staff"**.
2. Fill in: Name, Email, Phone, Specialization, Courses they teach.
3. Click **"Add Staff"**.

#### Editing / Deleting Staff
- Same process as Students — use the pencil or trash icons.

#### Assigning Courses
- When adding or editing a staff member, select the courses they teach from the multi-select dropdown.

#### Excel Import
- Similar to student import — upload an Excel file with staff data.

---

### 5.4 Attendance

> **Note:** This section is visible to ALL logged-in users. Staff can mark attendance only for their own courses.

The **Attendance** page is where you mark who is present or absent each day.

#### Marking Attendance
1. Select the **date** (defaults to today).
2. You will see tables for **Students** and **Staff**.
3. Click the **"Present"** or **"Absent"** button next to each person's name.
4. The status updates instantly.

#### Filtering by Tutor (for Staff users)
- If you are a tutor, select your name from the **"Tutor Filter"** dropdown.
- Only students enrolled in your courses will be shown.

#### 7-Day History
- A chart at the bottom shows attendance trends for the last 7 days.

#### QR Code Scanning
1. Click the **"QR Scanner"** button.
2. Allow camera access when prompted.
3. Hold a student's or staff member's ID card QR code in front of the camera.
4. Attendance is marked automatically.

#### AI Attendance Analysis (Admin only)
- Click **"Analyze Attendance"** to get AI-powered insights about attendance patterns and at-risk students.

---

### 5.5 Exams

> **Note:** This section is only visible to Admin users.

The **Exams** page lets you create exams, enter scores, and generate reports.

#### Creating an Exam
1. Click **"Create Exam"**.
2. Fill in:
   - **Course** — Select the course from dropdown
   - **Title** — e.g., "Midterm Exam"
   - **Date** — Exam date
   - **Max Marks** — Total marks for the exam
   - **Passing Marks** — Minimum marks to pass
   - **Description** — Any notes (optional)
3. Click **"Create Exam"**.

#### Entering Scores
1. Click the **"Scores"** button next to an exam.
2. For each student, enter the marks obtained.
3. Click **"Save Scores"**.

#### Exam Reports
1. Click the **"Report"** button next to an exam.
2. A PDF report will be generated with:
   - Student rankings
   - Pass/Fail status
   - Class average, highest, and lowest marks

#### Student Performance Report
1. Go to any student's page or the exams page.
2. Click **"Student Performance Report"**.
3. A PDF shows all exam scores for that student.

---

### 5.6 Leaves

> **Note:** This section is visible to ALL logged-in users.

The **Leaves** page manages staff leave requests.

#### Applying for Leave (Staff)
1. Fill in the form:
   - **Start Date** — When your leave begins
   - **End Date** — When your leave ends
   - **Reason** — Why you need leave
2. Click **"Submit Request"**.
3. Your leave will be marked as **"Pending"** until an Admin approves it.

#### Approving/Rejecting Leave (Admin only)
1. View all pending leave requests in the table.
2. Click **"Approve"** or **"Reject"** next to each request.
3. The status will update accordingly.

#### Leave History
- Both Admin and Staff can view their leave history in the table below the form.

---

## 6. Finance Section

### 6.1 Fees & Ledger

> **Note:** This section is only visible to Admin users.

The **Fees & Ledger** page manages all fee collections.

#### Recording a Payment
1. Click **"Record Payment"**.
2. Fill in:
   - **Student** — Select from the searchable dropdown
   - **Amount Paid** — How much the student paid
   - **Payment Method** — Cash, Card, UPI, Bank Transfer, etc.
   - **Remarks** — Any notes (optional)
3. Click **"Record Payment"**.

#### Viewing Student Balances
- The **Student Balances** section shows a table with:
  - Student name
  - Total fees (sum of enrolled course fees)
  - Total paid
  - Outstanding balance
  - Payment status indicator

#### AI Fee Analysis
1. Click **"Analyze Fees"**.
2. The AI will analyze fee collection patterns and show:
   - Monthly collection trends
   - Default risk predictions
   - Recommendations to improve collections

#### Export Options
- Click the **"Export"** dropdown:
  - **Tally XML** — For Tally accounting software
  - **Zoho Books CSV** — For Zoho Books
  - **Invoice PDF** — GST-compliant invoice for any fee record

> **See also:** [Accounting & GST](#12-accounting--gst)

---

### 6.2 Expenses

> **Note:** This section is only visible to Admin users.

The **Expenses** page tracks all institute spending.

#### Adding an Expense
1. Click **"Add Expense"**.
2. Fill in:
   - **Category** — e.g., Rent, Electricity, Salary, Supplies
   - **Amount** — How much spent
   - **Description** — What the expense was for
   - **Date** — When it was incurred
3. Click **"Add Expense"**.

#### Filtering Expenses
- Use the **Category**, **Month**, and **Year** dropdowns to filter the list.

#### Viewing Category Totals
- The card above the table shows total expenses for each category.

#### AI Expense Optimization (Admin only)
1. Click **"Optimize Expenses"**.
2. The AI analyzes spending patterns and suggests:
   - Which categories are overspent
   - Cost-saving opportunities
   - Budget recommendations

---

### 6.3 Payroll

> **Note:** This section is only visible to Admin users.

The **Payroll** page manages staff salaries.

#### Setting Up Payroll for a Tutor
1. Go to a tutor's profile and set:
   - **Base Salary** — Fixed monthly amount
   - **Commission %** — Percentage of fees collected from their students
   - **TDS %** — Tax deduction at source
   - **Bonus** — Any additional amount
   - **Other Deductions** — Any deductions
   - **Bank Details** — Bank name, account number, IFSC code

#### Processing Payroll
1. Click **"Process Payroll"** for a single tutor, or **"Process All"** for all active tutors.
2. The system calculates:
   - Base amount + Commission + Bonus − TDS − Deductions = **Net Amount**
3. The payroll record is created as **"Draft"**.

#### Confirming Payment
1. Click **"Confirm"** next to a draft payroll record.
2. This creates an expense entry and marks the payroll as **"Paid"**.

#### Cancelling Payroll
1. Click **"Cancel"** to void a draft payroll record.

#### Downloading Payslip
1. Click **"Payslip"** next to any payroll record.
2. A PDF payslip is downloaded.

#### Filtering Payroll Records
- Use the **Month**, **Year**, and **Status** dropdowns to filter.

---

### 6.4 Enquiries

> **Note:** This section is only visible to Admin users.

The **Enquiries** page manages potential students who have shown interest.

#### Logging a New Enquiry
1. Click **"New Enquiry"**.
2. Fill in:
   - **Student Name** — Name of the prospective student
   - **Email** (optional)
   - **Phone** — Contact number
   - **Course Interested In** — Select from the dropdown
   - **Source** — How they heard about you (Walk-in, Website, Referral, Social Media, etc.)
   - **Notes** — Any additional information
3. Click **"Add Enquiry"**.

#### Managing Enquiry Status
- Each enquiry can have one of these statuses:
  - **New** — Just came in
  - **Contacted** — You've reached out
  - **Converted** — They enrolled as a student
  - **Lost** — Not interested

#### Converting to Student
1. Click **"Convert to Student"** next to an enquiry.
2. The system automatically creates a student record with the same details.
3. You are redirected to the Students page.

#### AI Follow-up Messages
1. Click the **AI icon** next to an enquiry.
2. The AI generates a personalized follow-up message draft.
3. Use this message to contact the prospect.

#### Pipeline View
- The top of the page shows the enquiry pipeline with counts for each status:
  - **New** → **Contacted** → **Converted** / **Lost**

---

### 6.5 Salary Calculator

> **Note:** This section is only visible to Admin users.

The **Salary Calculator** helps you compute tutor salaries based on fees collected.

1. Select a **Tutor** from the dropdown.
2. Enter the **Commission %** (or use default from payroll settings).
3. Choose the **Period** (month or date range).
4. Click **"Calculate"**.
5. The system shows:
   - Total fees collected from the tutor's students
   - Commission amount
   - Final salary amount
   - Breakdown by student

---

## 7. Analytics Section

### 7.1 Reports

> **Note:** This section is only visible to Admin users.

The **Reports** page gives you detailed financial reports.

#### Available Report Tabs
| Tab | What It Shows |
|---|---|
| **Income** | Fees collected period-wise (broken down by month/quarter/custom) |
| **Fees** | Individual fee records within the selected period |
| **Expense** | All expenses period-wise |
| **Overall (P&L)** | Profit & Loss statement — Income minus Expenses |
| **Payment Methods** | How students are paying (Cash, Card, UPI, etc.) |

#### Filtering Reports
- **Monthly** — Pick a month and year
- **Quarterly** — Pick a quarter (Jan-Mar, Apr-Jun, Jul-Sep, Oct-Dec) and year
- **Custom** — Pick start and end dates

#### Charts
- Each report tab shows a chart visualizing the data.

#### Downloading Reports
- **PDF** — Click **"Download PDF"** for a printable report
- **Excel** — Click **"Download Excel"** for a spreadsheet file

---

### 7.2 Google Sync

> **Note:** This section is only visible to Admin users.

The **Google Sync** feature lets you pull enquiries directly from a **Google Form** into the system.

#### Setup
1. **Upload Service Account Key** — Upload the JSON key file from Google Cloud Console.
2. **Set Spreadsheet ID** — The ID from your Google Sheet URL (the long string in the address bar).
3. **Set Form URL** — The URL of your Google Form.
4. Click **"Save Settings"**.

#### Testing the Connection
1. Click **"Test Connection"** to verify everything is set up correctly.

#### Syncing Data
1. Click **"Sync Now"** to pull all new form submissions into the Enquiries table.
2. The system automatically:
   - Creates new course entries if the form mentions a course that doesn't exist yet
   - Skips duplicate entries (already synced)

---

## 8. Extra Features

The **Extra Features** page is accessible to ALL users and contains:

### Dark Mode Toggle
- A card with the dark mode toggle switch (same as the sidebar toggle).

### Database Backup & Restore
> **Note:** Full backup/restore features are only for Admin users.

- **Manual Backup** — Click to create a backup of the entire database.
- **Download Backup** — List and download previous backup files.
- **Restore Backup** — Restore the system to a previous state from a backup file.

> **Warning:** Restoring a backup will overwrite all current data.

---

## 9. Admin Console

> **Note:** This section is only visible to Admin users.

The **Admin Console** is the control center for all system settings. Access it from the sidebar (shield icon at the bottom).

### 9.1 AI Engine Keys

Here you can configure API keys for the AI features:

- **Gemini API Key** — From [Google AI Studio](https://aistudio.google.com)
- **OpenAI API Key** — From [OpenAI Platform](https://platform.openai.com)

> If no keys are configured, the AI features will still work using built-in rule-based responses, but the quality will be lower.

Click **"Save API Keys"** after entering.

### 9.2 SMTP (Email) Settings

Configure email sending for notifications:

| Field | What to Enter |
|---|---|
| **SMTP Server** | e.g., `smtp.gmail.com` |
| **SMTP Port** | Usually `587` for TLS |
| **SMTP Username** | Your email address |
| **SMTP Password** | Your email password or app password |
| **Sender Email** | The "From" address for emails |
| **Use TLS** | Keep checked for security |

**Test Email:** Enter a recipient email and click **"Send Test Email"** to verify.

### 9.3 WhatsApp Settings

Configure WhatsApp messaging via Meta Cloud API:

| Field | Description |
|---|---|
| **Permanent Access Token** | From Meta Business Suite > WhatsApp > API Setup |
| **Phone Number ID** | Your WhatsApp Business phone number ID |
| **Business Account ID** | Your WhatsApp Business Account ID |

**Test Message:** Enter a phone number and click **"Send Test via WhatsApp"** to verify.

**Bulk Campaigns:**
- **Send Fee Reminders** — Sends WhatsApp to all students with outstanding balance
- **Send Attendance Alerts** — Sends WhatsApp to students with <60% attendance
- **Send Exam Schedule** — Sends WhatsApp with exam details

> **Cost:** WhatsApp charges per conversation (approximately ₹0.013 per utility message in India).

### 9.4 SMS Gateway Settings

Configure SMS sending via any HTTP SMS gateway:

| Field | Description |
|---|---|
| **Gateway URL** | The HTTP endpoint of your SMS provider |
| **API Key** | Your provider's API key |
| **Sender ID** | e.g., `GUHAAC` (6 characters) |
| **HTTP Method** | GET or POST |
| **Phone Param** | The parameter name for phone number (default: `mobile`) |
| **Message Param** | The parameter name for message text (default: `message`) |
| **Key Param Name** | The parameter name for API key (default: `api_key`) |
| **Sender Param Name** | The parameter name for sender ID (default: `sender`) |

**Test Message:** Enter a phone number and click **"Send Test SMS"** to verify.

**Bulk Campaigns:**
- Same options as WhatsApp — Fee Reminders, Attendance Alerts, Exam Schedule

> **Cost:** Varies by provider — typically ₹0.05–₹0.20 per SMS in India.

### 9.5 Organization & GST Settings

Configure your institute's details:

| Field | Description |
|---|---|
| **Organization Name** | Your institute's legal name |
| **Address** | Registered address |
| **GSTIN** | GST Identification Number (if registered) |
| **HSN Code** | Service HSN code (typically `999293`) |
| **State Code** | Your state's GST code |
| **CGST %** | Central GST rate (default: 9%) |
| **SGST %** | State GST rate (default: 9%) |
| **Invoice Prefix** | e.g., `GUHA/23-24/` |

These settings are used in GST invoices and accounting exports.

### 9.6 User Management

- View all system users in a table.
- Use the **"Delete"** button to remove a user.

> **Note:** You cannot delete your own account while logged in.

### 9.7 Database Backup & Restore

- **Manual Backup** — Click to create a database backup immediately.
- **Auto-backup** — The system automatically creates a backup once every day.
- **Restore** — Select a backup file and click **"Restore"** to go back to that point in time.

> **Warning:** Restoring will replace ALL current data with the backed-up data. This cannot be undone.

---

## 10. AI Chatbot Assistant

A **Chatbot** is available on every page — look for the **smiley face** button at the bottom-right corner.

### How to Use
1. Click the **smiley face** button.
2. The chat panel opens.
3. Type your question in the input box and press Enter (or click the send button).
4. The AI will respond instantly.

### What You Can Ask
The chatbot understands questions like:

| Question | Example |
|---|---|
| Student count | "How many students are there?" |
| Students in a course | "How many students are in Dance Class?" |
| Fees collected | "How much fees collected this month?" |
| Defaulters | "Who hasn't paid fees?" |
| Today's attendance | "What is today's attendance?" |
| Attendance rate | "What is the overall attendance percentage?" |
| Low attendance | "Show students with low attendance" |
| Course count | "How many courses do we have?" |
| Staff count | "How many tutors are there?" |
| Upcoming exams | "When is the next exam?" |
| Pending leaves | "Are there any pending leave requests?" |
| Recent enquiries | "Show me recent enquiries" |
| Help | "What can you do?" or "Help" |

> The chatbot uses the Gemini or OpenAI AI if configured. If no API key is set, it falls back to rule-based answers that still query the database.

---

## 11. QR Code ID Cards & Attendance Scanning

Every student and staff member has a unique QR code that can be used for identification and attendance.

### Viewing / Printing ID Cards
1. Go to **Students** or **Staff** page.
2. Click the **ID card icon** next to a person's name.
3. A modal shows the ID card with name, email, phone, and QR code.
4. Click **"Print ID Card"** to print.

### Scanning for Attendance
1. Go to **Attendance** page.
2. Click **"QR Scanner"**.
3. Allow camera access when prompted.
4. Hold the printed ID card in front of your webcam.
5. Attendance is marked automatically.

---

## 12. Accounting & GST

### 12.1 GST Invoice
- Go to **Fees & Ledger** page.
- Click the **invoice icon** next to any fee record.
- A PDF invoice is generated with:
  - Invoice number (auto-incremented)
  - Student and course details
  - Amount breakdown
  - CGST and SGST calculations
  - Organization details (from Admin Console settings)

### 12.2 Tally Export
- Click **"Export" > "Tally XML"** on the Fees page.
- Downloads an XML file that can be imported into Tally accounting software.

### 12.3 Zoho Books Export
- Click **"Export" > "Zoho Books CSV"** on the Fees page.
- Downloads a CSV file that can be imported into Zoho Books.

---

## 13. Importing from Excel

You can import students and staff in bulk from Excel files.

### Preparing Your Excel File
- Use **.xlsx** or **.xls** format.
- The first row should be column headers.
- Required columns: **Name**, **Email**, **Phone**
- Optional columns: **Course** (for students), **Specialization** (for tutors)

### Import Process
1. Go to the **Students** or **Staff** page.
2. Click **"Import from Excel"**.
3. Select your Excel file and click **"Upload"**.
4. The system will:
   - Validate each row (check for missing data, duplicate emails, etc.) using AI
   - For students, suggest which course each student should be mapped to
   - Show a summary of what will be imported
5. Confirm the import.

---

## 14. Reports & Downloads

| Report | Where to Find | Format |
|---|---|---|
| Financial Reports | **Reports** page | PDF, Excel |
| Exam Reports | **Exams** page (click "Report") | PDF |
| Student Performance | **Exams** page (click "Student Report") | PDF |
| GST Invoice | **Fees & Ledger** (click invoice icon) | PDF |
| Payslip | **Payroll** (click "Payslip") | PDF |
| Tally Export | **Fees & Ledger** (Export dropdown) | XML |
| Zoho Books Export | **Fees & Ledger** (Export dropdown) | CSV |

---

## 15. Tips & Shortcuts

- **Global Search** — Use the amber search bar at the top to quickly find any student, tutor, course, or enquiry.
- **Dark Mode** — Toggle from the sidebar footer for comfortable viewing at night.
- **AI Chatbot** — Ask the chatbot questions instead of navigating menus for quick information.
- **QR Scanner** — Use the webcam to mark attendance quickly without clicking buttons.
- **Modals** — Most forms open in popup modals. The first field is automatically focused so you can start typing immediately.
- **Sidebar Accordion** — Click "Academic", "Finance", or "Analytics" to expand/collapse menu groups.
- **Table Sorting** — Click any column header in a table to sort by that column.
- **Auto-backup** — The system backs up automatically every day. You don't need to do it manually.

---

## 16. Troubleshooting

### Login Issues
| Problem | Solution |
|---|---|
| Forgot password | Click "Forgot Password?" and follow the steps |
| Account locked | Contact the Admin to check your account |
| "Invalid credentials" | Check your username and password spelling |

### Attendance Issues
| Problem | Solution |
|---|---|
| Student not showing in attendance | Make sure the student is enrolled in a course |
| QR scanner not working | Allow camera access in your browser settings |
| Can't mark attendance for a past date | The date selector allows picking any date |

### Search Issues
| Problem | Solution |
|---|---|
| No results found | Try different keywords (minimum 2 characters required) |
| Search seems slow | The first search may be slower while the database loads |

### AI / Chatbot Issues
| Problem | Solution |
|---|---|
| Chatbot says "I don't understand" | Try rephrasing your question. Ask "Help" to see what questions are supported. |
| AI insights missing | Make sure you have data in the system (students, attendance, etc.) |
| No AI features visible | Configure an API key in Admin Console for best results (optional) |

### Browser Issues
| Problem | Solution |
|---|---|
| Page looks broken | Do a hard refresh: `Ctrl + F5` (Windows) or `Cmd + Shift + R` (Mac) |
| Changes not showing | Clear your browser cache or use hard refresh |
| HTMX navigation issues | Click the sidebar link again to reload the page normally |

### Database / Backup
| Problem | Solution |
|---|---|
| Need to undo changes | Restore from a backup in Admin Console |
| Accidentally deleted something | Restore from the most recent backup |
| Backup download not starting | Check your browser's pop-up blocker settings |

---

## Need Help?

- Use the **AI Chatbot** (smiley face at bottom-right) for quick questions
- Contact your system **Admin** for account or permission issues
- For technical support, check the system logs or contact the developer

---

*This manual was generated for **Guha Institute Management System**. Keep it updated as the app grows.*
