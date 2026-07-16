# Guha Institute Management System — Workflow & Process Guide

> **Version:** 1.0  
> **Last Updated:** June 2026

---

## Table of Contents

1. [How to Read This Guide](#1-how-to-read-this-guide)
2. [Complete Institute Lifecycle (Big Picture)](#2-complete-institute-lifecycle-big-picture)
3. [Workflow 1: Student Journey (Enquiry → Enrollment → Completion)](#3-workflow-1-student-journey)
4. [Workflow 2: Fee Collection & Tracking](#4-workflow-2-fee-collection--tracking)
5. [Workflow 3: Daily Attendance](#5-workflow-3-daily-attendance)
6. [Workflow 4: Exam Management](#6-workflow-4-exam-management)
7. [Workflow 5: Staff Payroll Cycle](#7-workflow-5-staff-payroll-cycle)
8. [Workflow 6: Leave Management](#8-workflow-6-leave-management)
9. [Workflow 7: Expense Tracking](#9-workflow-7-expense-tracking)
10. [Workflow 8: Communication & Alerts](#10-workflow-8-communication--alerts)
11. [Workflow 9: Reports & Financial Closing](#11-workflow-9-reports--financial-closing)
12. [Workflow 10: Data Backup & Recovery](#12-workflow-10-data-backup--recovery)
13. [Workflow 11: Excel Bulk Import](#13-workflow-11-excel-bulk-import)
14. [Workflow 12: Google Form Sync](#14-workflow-12-google-form-sync)
15. [Cross-Flow Dependencies Diagram](#15-cross-flow-dependencies-diagram)
16. [Quick Reference: Who Does What](#16-quick-reference-who-does-what)
17. [Updating This Guide](#17-updating-this-guide)

---

## 1. How to Read This Guide

Each workflow is presented as a **step-by-step process**. Arrows (→) show the sequence of actions.  

**Symbols used:**

| Symbol | Meaning |
|---|---|
| **→** | Next step in the process |
| **←** | Return to previous step (loop) |
| **⟳** | Recurring / repeating action |
| **⚠️** | Warning or important note |
| **💡** | Tip or shortcut |
| **Admin** | Action only Admin can perform |
| **Staff** | Action Staff can perform |
| **Auto** | Happens automatically |

---

## 2. Complete Institute Lifecycle (Big Picture)

This is how all the workflows connect together at a high level:

```
                         ┌──────────────────────────────────────┐
                         │         GOOGLE FORM / WEBSITE        │
                         │     (Enquiries come in automatically)│
                         └──────────────┬───────────────────────┘
                                        │
                         ┌──────────────▼───────────────────────┐
                         │         MANUAL ENQUIRY LOGGING       │
                         │  (Walk-in / Phone / Referral)        │
                         └──────────────┬───────────────────────┘
                                        │
                         ┌──────────────▼───────────────────────┐
                         │      ENQUIRY FOLLOW-UP & CONTACT     │
                         │                                     │
                         │  ┌──────────┐   ┌──────────┐       │
                         │  │ CONTACTED│ → │ CONVERTED│       │
                         │  └──────────┘   └────┬─────┘       │
                         │  ┌──────────┐        │             │
                         │  │   LOST   │        │             │
                         │  └──────────┘        ▼             │
                         └────────────────────────────────────┘
                                        │
                         ┌──────────────▼───────────────────────┐
                         │         STUDENT ENROLLMENT          │
                         │  (Student + Course Assignment)       │
                         └──────────────┬───────────────────────┘
                                        │
            ┌───────────────────────────┼───────────────────────────┐
            │                           │                           │
            ▼                           ▼                           ▼
   ┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
   │   FEE PAYMENT   │       │   ATTENDANCE   │       │  EXAM / SCORES  │
   │  (Ongoing)      │       │  (Daily)        │       │  (Per Course)   │
   └────────┬────────┘       └────────┬────────┘       └────────┬────────┘
            │                         │                         │
            ▼                         ▼                         ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │                     REPORTS & ANALYTICS                         │
   │  (Income, Expense, P&L, Attendance, Exam Performance)           │
   └─────────────────────────────────────────────────────────────────┘
```

---

## 3. Workflow 1: Student Journey

This is the complete lifecycle of a student — from first inquiry to active enrollment.

### 3.1 Enquiry Comes In

```
START
  │
  ├── [Option A] Walk-in / Phone / Referral
  │     → Admin goes to Enquiries page
  │     → Clicks "New Enquiry"
  │     → Fills: Name, Phone, Course Interested, Source, Notes
  │     → Clicks "Add Enquiry"
  │     → Status is set to "New" automatically
  │
  ├── [Option B] Website / Google Form
  │     → Google Form submission lands in Google Sheet
  │     → Admin goes to Google Sync page
  │     → Clicks "Sync Now"
  │     → System pulls new rows from Google Sheet
  │     → Creates Enquiry records with status "New"
  │     → Skips duplicates automatically
  │
  └── [Option C] Excel Bulk Import
        → Admin prepares Excel file with Name, Email, Phone, Course
        → Goes to Enquiries → Import from Excel
        → System validates and imports
        → Creates Enquiry records with status "New"
```

### 3.2 Enquiry Follow-Up

```
  Enquiry created with status "New"
    │
    ▼
  Admin views Enquiries page
    │
    ├── → Clicks AI icon next to enquiry
    │   → System generates AI follow-up message draft
    │   → Admin copies message and contacts the prospect
    │   → Admin updates status to "Contacted"
    │
    └── → Admin manually contacts prospect (phone/email)
        → Admin updates status to "Contacted"
          │
          ▼
    Prospect responds positively
      │                    │
      ▼                    ▼
  Status → "Converted"   Status → "Lost"
      │                    (End - no further action)
      ▼
  Admin clicks "Convert to Student"
      │
      ▼
  System creates Student record with:
  • Name, Email, Phone (copied from enquiry)
  • Enrolled in the course they were interested in
  • Status = "Active"
      │
      ▼
  Redirected to Students page
  Enquiry status automatically set to "Converted"
```

### 3.3 Direct Enrollment (Without Enquiry)

```
  Admin → Students page → Clicks "Enroll Student"
    │
    ▼
  Fills form: Name, Email, Phone, Selects Courses
    │
    ▼
  Clicks "Enroll Student"
    │
    ▼
  System creates Student record
  Student is linked to selected courses
  Status = "Active"
```

### 3.4 Ongoing Student Management

```
  ┌────────────────────────────────────────────┐
  │         STUDENT IS NOW ACTIVE              │
  │                                            │
  │  • Attendance marked daily (see WF 4)      │
  │  • Fees collected & tracked (see WF 3)     │
  │  • Exam scores recorded (see WF 5)         │
  │  • ID card with QR code available          │
  └────────────────────────────────────────────┘
       │
       ▼
  ⟳ If student needs to change courses:
       → Admin edits student
       → Updates course selections
       → Fees recalculated automatically
       │
       ▼
  ⟳ If student leaves / graduates:
       → Admin edits student
       → Changes status to "Inactive"
       → Student no longer appears in active counts
       → (Records are preserved for history)
```

### 3.5 Student Data Import (Bulk)

```
  Admin has Excel file with student data
    │
    ▼
  Students page → Clicks "Import from Excel"
    │
    ▼
  Uploads .xlsx file
    │
    ▼
  System uses AI to:
  1. Validate each row (check emails, missing data)
  2. Suggest course assignments based on data
    │
    ▼
  Admin reviews validation results
    │
    ├── → Fixes errors in Excel → Upload again
    └── → Confirms import
          │
          ▼
  All valid students are created at once
  Duplicate emails are skipped
```

---

## 4. Workflow 2: Fee Collection & Tracking

### 4.1 Fee Structure Setup

```
  BEFORE any fee can be collected:
    │
    ├── Course must exist with a fee amount set
    │   (Courses → Create Course → Set "Fees" field)
    │
    └── Student must be enrolled in that course
        (Students → Enroll → Select course)
          │
          ▼
  System can now calculate:
  • Total fee = Sum of all enrolled course fees
  • Paid amount = Sum of all payment records
  • Balance = Total fee − Paid amount
```

### 4.2 Recording a Payment

```
  Admin → Fees & Ledger page
    │
    ▼
  Clicks "Record Payment"
    │
    ▼
  Selects Student from searchable dropdown
  Enters: Amount, Payment Method (Cash/Card/UPI/etc.), Remarks
    │
    ▼
  Clicks "Record Payment"
    │
    ▼
  System:
  • Creates FeeRecord with date = today
  • Updates student's paid amount
  • Balance recalculates automatically
    │
    ▼
  Confirmation message shown
```

### 4.3 Fee Monitoring & Follow-Up

```
  ⟳ Ongoing (Admin checks periodically):
    │
    ├── View "Student Balances" table on Fees page
    │   • Shows every student with Total Fee, Paid, Balance
    │   • Outstanding balances are highlighted
    │
    ├── → Click "Analyze Fees"
    │   → AI generates fee collection insights
    │   → Shows trends, default risks, recommendations
    │
    └── → Admin Console → WhatsApp/SMS Campaigns
        → Click "Send Fee Reminders"
        → System finds all students with balance > 0
        → Sends reminder messages automatically
```

### 4.4 Export & Accounting

```
  When payment is recorded, Admin can:
    │
    ├── Click invoice icon next to any payment
    │   → PDF invoice downloads with:
    │     • Institute name, address, GSTIN
    │     • Student details
    │     • Course details
    │     • CGST + SGST breakdown
    │     • Invoice number (auto-incremented)
    │
    ├── Export dropdown → "Tally XML"
    │   → .xml file for Tally accounting software
    │
    └── Export dropdown → "Zoho Books CSV"
        → .csv file for Zoho Books
```

### Fee Flow Summary

```
  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
  │  Course  │ →  │ Student  │ →  │ Payment  │ →  │ Balance  │
  │ Fee Set  │    │ Enrolled │    │ Recorded │    │ Tracked  │
  └──────────┘    └──────────┘    └────┬─────┘    └──────────┘
                                       │
                           ┌───────────┴───────────┐
                           │                       │
                           ▼                       ▼
                    ┌──────────┐           ┌──────────────┐
                    │  Invoice │           │  Reminder    │
                    │   PDF    │           │  (WhatsApp/  │
                    └──────────┘           │   SMS)       │
                                           └──────────────┘
```

---

## 5. Workflow 3: Daily Attendance

### 5.1 Manual Attendance Marking

```
  ⟳ Every day (or as needed):
    │
    ▼
  User goes to Attendance page
    │
    ├── [If Staff / Tutor]
    │   → Selects own name from "Tutor Filter" dropdown
    │   → Only sees students enrolled in their courses
    │
    └── [If Admin]
        → Sees ALL students and ALL staff
    │
    ▼
  Default date = Today (can change to past dates)
    │
    ▼
  For each person in the table:
    │
    ├── Click "Present" button
    │   → Status turns green
    │
    └── Click "Absent" button
        → Status turns red
    │
    ▼
  Status updates instantly (no save button needed)
```

### 5.2 QR Code Attendance (Fast Method)

```
  User → Attendance page → Click "QR Scanner"
    │
    ▼
  Allow camera access in browser
    │
    ▼
  Hold student's or staff's printed ID card to camera
    │
    ▼
  QR code is scanned automatically
    │
    ▼
  Attendance marked as "Present" for today
  Person's name shown on screen as confirmation
```

### 5.3 Attendance Monitoring

```
  ⟳ Admin monitors attendance:
    │
    ├── View 7-day attendance chart on Attendance page
    │   • Shows daily attendance percentage trend
    │
    ├── View 7-day chart on Dashboard
    │   • Same data, visible on home page
    │
    ├── → Click "Analyze Attendance"
    │   → AI identifies at-risk students
    │   → Shows patterns and recommendations
    │
    └── → Admin Console → WhatsApp/SMS Campaigns
        → Click "Send Attendance Alerts"
        → System finds students with <60% attendance (last 30 days)
        → Sends alert messages automatically
```

### Attendance Flow Summary

```
  ┌──────────────────┐
  │  START OF DAY    │
  └────────┬─────────┘
           │
  ┌────────▼─────────┐      ┌──────────────────┐
  │ Manual Marking   │  OR  │ QR Code Scanning │
  │ (Click button)   │      │ (Webcam)         │
  └────────┬─────────┘      └────────┬─────────┘
           │                         │
           └────────────┬────────────┘
                        ▼
              ┌──────────────────┐
              │ Record stored in │
              │  Attendance DB   │
              │  (Person + Date  │
              │   + Status)      │
              └────────┬─────────┘
                       │
          ┌────────────┴────────────┐
          │                         │
          ▼                         ▼
  ┌─────────────────┐     ┌──────────────────┐
  │ 7-Day Chart     │     │ Low Attendance   │
  │ (Attendance %)  │     │ Alert (WhatsApp/ │
  └─────────────────┘     │  SMS)            │
                          └──────────────────┘
```

---

## 6. Workflow 4: Exam Management

### 6.1 Creating an Exam

```
  Admin → Exams page → Click "Create Exam"
    │
    ▼
  Fill in:
  • Course (which course this exam is for)
  • Title (e.g., "Midterm", "Final")
  • Date
  • Maximum Marks (total marks)
  • Passing Marks (minimum to pass)
  • Description (optional notes)
    │
    ▼
  Click "Create Exam"
  Exam appears in the list
```

### 6.2 Entering Scores

```
  Admin → Exams page
    │
    ▼
  Click "Scores" button next to the exam
    │
    ▼
  Table shows all students enrolled in that course
    │
    ▼
  For each student: Enter marks obtained
    │
    ▼
  Click "Save Scores"
  System calculates Pass/Fail based on passing marks
```

### 6.3 Exam Reports

```
  Admin → Exams page
    │
    ├── Click "Report" next to an exam
    │   → PDF downloads with:
    │     • All students ranked by marks
    │     • Pass/Fail status for each
    │     • Class average, highest, lowest marks
    │     • Pass percentage
    │
    └── Click "Student Report" (any time)
        → PDF downloads for a specific student
        → Shows all their exam scores across all courses
        → Performance trend over time
```

### Exam Flow Summary

```
  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
  │  Course  │ →  │  Create  │ →  │  Enter   │ →  │  Report  │
  │ Exists   │    │  Exam    │    │  Scores  │    │  (PDF)   │
  └──────────┘    └──────────┘    └──────────┘    └──────────┘
                                                   │
                                              ┌────┴────┐
                                              │         │
                                              ▼         ▼
                                       ┌────────┐ ┌──────────┐
                                       │ Exam   │ │ Student  │
                                       │ Report │ │ Perform. │
                                       └────────┘ └──────────┘
```

---

## 7. Workflow 5: Staff Payroll Cycle

### 7.1 Payroll Settings Setup (One Time Per Tutor)

```
  Admin → Staff page → Click edit on a tutor
    │
    ▼
  Go to Payroll Settings section
    │
    ▼
  Set:
  • Base Salary (fixed monthly amount)
  • Commission % (of fees collected from their students)
  • TDS % (tax deduction, default 10%)
  • Bonus (if any)
  • Other Deductions (if any)
  • Bank Name, Account Number, IFSC Code
    │
    ▼
  Click "Save Settings"
```

### 7.2 Monthly Payroll Processing

```
  ⟳ Every month:
    │
    ▼
  Admin → Payroll page
    │
    ├── → Click "Process All"
    │   → System processes payroll for ALL active tutors
    │
    └── → Click "Process" next to a specific tutor
        → System processes payroll for ONE tutor
    │
    ▼
  For each tutor, system calculates:
  ┌──────────────────────────────────────────────┐
  │  Base Amount                                  │
  │  + Commission (fees collected × commission%)  │
  │  + Bonus                                      │
  │  − TDS (tax)                                  │
  │  − Other Deductions                           │
  │  ═══════════════════════════════════════════  │
  │  = NET AMOUNT (final salary)                  │
  └──────────────────────────────────────────────┘
    │
    ▼
  Payroll record created with status = "Draft"
    │
    ▼
  Admin reviews the calculated amounts
    │
    ├── → Click "Confirm" (mark as paid)
    │   → Status changes to "Paid"
    │   → Date of payment recorded
    │   → Expense entry created automatically
    │   → Payslip available for download
    │
    ├── → Click "Cancel" (if wrong)
    │   → Draft record is removed
    │   → Can process again after fixing settings
    │
    └── → Click "Payslip" (any time after confirming)
        → PDF payslip downloads
```

### Payroll Flow Summary

```
  ┌──────────────┐
  │  Set Payroll │  (One time per tutor)
  │  Settings    │
  └──────┬───────┘
         │
  ┌──────▼───────┐
  │  Process     │  ⟳ Monthly
  │  Payroll     │
  └──────┬───────┘
         │
  ┌──────▼───────┐      ┌──────────────────┐
  │  Review      │ →    │  Confirm (Paid)  │ → Payslip PDF
  │  (Draft)     │      └──────────────────┘
  └──────┬───────┘
         │
  ┌──────▼───────┐
  │  Cancel      │  (If incorrect)
  │  (Remove)    │
  └──────────────┘
```

---

## 8. Workflow 6: Leave Management

### 8.1 Staff Applies for Leave

```
  Staff → Leaves page
    │
    ▼
  Fills leave form:
  • Start Date
  • End Date
  • Reason for leave
    │
    ▼
  Clicks "Submit Request"
    │
    ▼
  Leave request created with status = "Pending"
```

### 8.2 Admin Approves or Rejects

```
  Admin → Leaves page
    │
    ▼
  Sees all pending leave requests from all staff
    │
    ├── → Click "Approve"
    │   → Status changes to "Approved"
    │
    └── → Click "Reject"
        → Status changes to "Rejected"
    │
    ▼
  Staff can see the updated status when they visit Leaves page
```

### Leave Flow Summary

```
  ┌──────────┐    ┌──────────┐    ┌───────────┐
  │  Staff   │ →  │  Pending │ →  │ Approved  │
  │ Applies  │    │          │    │  OR       │
  └──────────┘    └──────────┘    │ Rejected  │
                                  └───────────┘
```

---

## 9. Workflow 7: Expense Tracking

### 9.1 Recording an Expense

```
  Admin → Expenses page → Click "Add Expense"
    │
    ▼
  Fill in:
  • Category (Rent, Electricity, Salary, Supplies, etc.)
  • Amount
  • Description (what it was for)
  • Date (when it happened)
    │
    ▼
  Click "Add Expense"
  Expense recorded and included in financial reports
```

### 9.2 Viewing & Filtering

```
  Expenses page shows:
    │
    ├── Category Summary Cards
    │   • Total spent in each category (month/year)
    │
    ├── Filter dropdowns
    │   • By Category
    │   • By Month
    │   • By Year
    │   → Table updates to show filtered records
    │
    └── Annual chart (bar chart by month)
```

### 9.3 AI Expense Optimization

```
  Admin → Expenses page → Click "Optimize Expenses"
    │
    ▼
  AI analyzes all expense data and shows:
  • Which categories are overspent
  • Cost-saving recommendations
  • Budget suggestions for next period
```

---

## 10. Workflow 8: Communication & Alerts

### 10.1 Prerequisites

```
  BEFORE sending any messages:
    │
    ├── [WhatsApp] Configure WhatsApp settings in Admin Console
    │   • Token, Phone ID, Business ID from Meta
    │   • Cost: ~₹0.013 per utility message in India
    │
    └── [SMS] Configure SMS Gateway settings in Admin Console
        • Gateway URL, API Key, Sender ID from SMS provider
        • Cost: ~₹0.05–₹0.20 per SMS in India
```

### 10.2 Sending Bulk Messages

```
  Admin → Admin Console → WhatsApp or SMS section
    │
    ├── Click "Send Fee Reminders"
    │   → System finds all students with balance > 0
    │   → Sends message: "Dear {name}, your balance of ₹{amount} is due."
    │   → Result: "X sent, Y failed"
    │
    ├── Click "Send Attendance Alerts"
    │   → System finds students with <60% attendance (last 30 days)
    │   → Sends message: "Dear {name}, your attendance in {course} is {pct}%."
    │   → Result: "X sent, Y failed"
    │
    └── Click "Send Exam Schedule"
        → Select Course (or All), Date, Time, Venue
        → System sends to all active students in selected course(s)
        → Result: "X sent, Y failed"
```

### 10.3 Email Notifications (Automatic)

```
  Auto-triggered by system (or manual via Notifications):
    │
    ├── Low Attendance Alert
    │   → Checks students with <75% attendance in last 30 days
    │   → Sends email to admin
    │
    ├── Fee Due Reminder
    │   → Checks students with unpaid balance >30 days
    │   → Sends email to admin
    │
    └── Enquiry Follow-Up Reminder
        → Checks enquiries with status "New" for >2 days
        → Sends email to admin
```

### 10.4 Automated Cron Jobs

```
  System can be set up to run automatically:
    │
    ├── /api/cron/notify?key=YOUR_SECRET
    │   → Runs all notification checks
    │   → Use with Windows Task Scheduler or cron
    │
    └── /api/cron/whatsapp?key=YOUR_SECRET
        → Runs all WhatsApp batch operations
        → Use with Windows Task Scheduler or cron
```

---

## 11. Workflow 9: Reports & Financial Closing

### 11.1 Generating Reports

```
  Admin → Reports page
    │
    ▼
  Choose report type (tab):
    │
    ├── Income
    │   • Fees collected in the period
    │   • Breakdown by month/quarter
    │
    ├── Fees
    │   • Individual fee records in the period
    │
    ├── Expense
    │   • All expenses in the period
    │
    ├── Overall (P&L)
    │   • Income − Expenses = Profit/Loss
    │   • Net result for the period
    │
    └── Payment Methods
        • How students paid (Cash, Card, UPI, etc.)
    │
    ▼
  Choose filter:
  • Monthly → Select Month + Year
  • Quarterly → Select Quarter + Year
  • Custom → Select Start Date + End Date
    │
    ▼
  View chart + table
    │
    ▼
  Export:
  ├── Click "Download PDF" → Printable report
  └── Click "Download Excel" → Spreadsheet file
```

### Report Flow Summary

```
  ┌──────────┐   ┌──────────┐   ┌───────────┐   ┌──────────┐
  │  Choose  │ → │  Choose  │ → │  View     │ → │  Export  │
  │  Tab     │   │  Filter  │   │  Chart +  │   │  PDF or  │
  │          │   │  Period  │   │  Table    │   │  Excel   │
  └──────────┘   └──────────┘   └───────────┘   └──────────┘
```

---

## 12. Workflow 10: Data Backup & Recovery

### 12.1 Automatic Daily Backup

```
  System runs automatically ONCE per day (no action needed):
    │
    ▼
  Creates backup file: auto_backup_YYYY-MM-DD.db
  Stored in: /backups/ folder
    │
    ▼
  Older backups are preserved (you can download them)
```

### 12.2 Manual Backup

```
  Admin → Extra Features page
    │
    ├── OR → Admin Console → Backup section
    │
    ▼
  Click "Create Backup"
    │
    ▼
  Backup file created immediately with timestamp
```

### 12.3 Downloading Backups

```
  Admin → Extra Features page → Backup section
    │
    ▼
  List of all backup files shown with dates
    │
    ▼
  Click any backup file to download it
```

### 12.4 Restoring from Backup

```
  ⚠️ IMPORTANT: Restoring will OVERWRITE all current data.
     This cannot be undone. Proceed only if you are sure.

    │
    ▼
  Admin → Admin Console → Backup section
    │
    ▼
  Select a backup file from the list
    │
    ▼
  Click "Restore"
    │
    ▼
  System replaces current database with backed-up version
  Page refreshes — system is now at the restored state
```

### Backup Flow Summary

```
  ┌──────────────────┐
  │  AUTO Backup     │  ⟳ Daily (Automatic)
  │  (No action)     │
  └──────────────────┘
         │
  ┌──────▼──────┐        ┌──────────────┐
  │ Manual      │        │ Backup files │
  │ Backup      │  ───→  │ stored in    │
  │ (Optional)  │        │ /backups/    │
  └──────┬──────┘        └──────┬───────┘
         │                      │
         └──────────┬───────────┘
                    ▼
          ┌──────────────────┐       ┌──────────────────┐
          │ Download Backup  │   OR  │ Restore Backup   │
          │ (Save to PC)     │       │ (Replace current │
          └──────────────────┘       │  database)       │
                                     └──────────────────┘
```

---

## 13. Workflow 11: Excel Bulk Import

### 13.1 Student Import

```
  Admin has Excel file with student data
    │
    ▼
  Prepare Excel file:
  • First row = headers (Name, Email, Phone, Course)
  • One student per row
  • Save as .xlsx or .xls
    │
    ▼
  Students page → Click "Import from Excel"
    │
    ▼
  Upload the file
    │
    ▼
  System processes:
  Phase 1 — AI Validation:
  • Checks each row for missing data
  • Validates email format
  • Checks for duplicate emails in system
  • Shows errors per row
    │
  Phase 2 — AI Course Mapping:
  • Reads course name from each row
  • Suggests matching course from system
  • If no match, lets you map manually
    │
    ▼
  Review results:
  ├── If errors → Fix Excel → Upload again
  └── If OK → Click "Confirm Import"
        │
        ▼
  All valid students created in bulk
  Duplicates skipped
  Confirmation shown with count
```

### 13.2 Tutor Import

```
  Same process as students:
  • Tutor page → Import from Excel
  • Columns: Name, Email, Phone, Specialization, Courses
  • AI validates and maps courses
  • Confirm to import
```

---

## 14. Workflow 12: Google Form Sync

### 14.1 Initial Setup (One Time)

```
  Admin → Google Sync page
    │
    ▼
  Step 1: Upload Service Account Key
  • Go to Google Cloud Console
  • Create Service Account → Download JSON key
  • Upload the JSON file here
    │
    ▼
  Step 2: Set Spreadsheet ID
  • Open your Google Sheet
  • Copy the ID from the URL
  • Paste and save
    │
    ▼
  Step 3: Set Form URL (optional, for reference)
  • Your Google Form URL
    │
    ▼
  Click "Test Connection" to verify
    │
    ▼
  ✅ If successful: Green checkmark shown
  ❌ If failed: Error message with details
```

### 14.2 Regular Syncing

```
  ⟳ As needed (when new form submissions come in):
    │
    ▼
  Admin → Google Sync page → Click "Sync Now"
    │
    ▼
  System:
  1. Connects to Google Sheet
  2. Reads new rows since last sync
  3. For each row:
     • Creates Enquiry with status "New"
     • If course doesn't exist → Creates new course
     • If duplicate (same data) → Skips
  4. Shows sync results
    │
    ▼
  Go to Enquiries page → New entries are visible
  Proceed with normal enquiry follow-up workflow
```

---

## 15. Cross-Flow Dependencies Diagram

This shows which workflows depend on others:

```
  ┌─────────────────────────────────────────────────────────────────────┐
  │                                                                     │
  │  WF 12: Google Sync ─────────────────────────────────────────┐     │
  │  WF 11: Excel Import ─────────────────────────────────────┐  │     │
  │                                                            ▼  ▼     │
  │  WF 1: Student Journey ──────────────────────────→  WF 2: Fees    │
  │  (Enquiry → Enrollment)                               WF 3: Attend.│
  │                                                       WF 4: Exams  │
  │                                                            │       │
  │                     WF 7: Expenses ◄────────────────────────┘       │
  │                     WF 5: Payroll ──── uses WF 2 data ──────────┐   │
  │                     WF 8: Communication ── uses WF 2,3,4 ──────┐│   │
  │                                                                 ▼▼   │
  │  WF 9: Reports ────────── uses data from WF 2,3,4,5,7               │
  │                                                                     │
  │  WF 6: Leaves ═══ (independent, no dependencies on other WFs)      │
  │  WF 10: Backup ═══ (independent, backs up everything)              │
  │                                                                     │
  └─────────────────────────────────────────────────────────────────────┘
```

---

## 16. Quick Reference: Who Does What

| Workflow | Admin | Staff | System (Auto) |
|---|---|---|---|
| **WF 1: Student Journey** | Creates enquiries, converts to students | — | AI follow-up draft, duplicate check |
| **WF 2: Fees** | Records payments, reviews balances, sends reminders | — | Balance calculation, AI analysis |
| **WF 3: Attendance** | Marks attendance (all), views AI analysis | Marks attendance (own courses) | QR scan recognition, low attendance alerts |
| **WF 4: Exams** | Creates exams, enters scores, downloads reports | — | Pass/Fail calculation, ranking, PDF reports |
| **WF 5: Payroll** | Sets settings, processes, confirms payments | — | Salary calculation, expense creation |
| **WF 6: Leaves** | Approves/rejects | Applies for leave | Status tracking |
| **WF 7: Expenses** | Records, categorizes, AI optimization | — | Category totals, charts |
| **WF 8: Communication** | Configures gateways, sends campaigns | — | Finds defaulters/low attendance, cron jobs |
| **WF 9: Reports** | Views, filters, exports | — | Data aggregation, chart rendering |
| **WF 10: Backup** | Triggers manual, restores | — | Daily auto backup |
| **WF 11: Excel Import** | Uploads, reviews, confirms | — | AI validation, course mapping |
| **WF 12: Google Sync** | Configures, syncs | — | Dedup, course creation |

---

## 17. Updating This Guide

When a new feature is added to the app, follow these steps to update this guide:

1. **Identify the workflow** — Does the new feature create a new workflow (add a new section) or modify an existing one (edit an existing section)?
2. **Add a new section** — Copy the format of an existing workflow section:
   - Write step-by-step instructions
   - Use → arrows for sequence
   - Mark who performs each step (Admin / Staff / Auto)
   - Add a flow summary box at the end
3. **Update the Big Picture** (Section 2) — If the new workflow connects to other workflows, update the diagram.
4. **Update Quick Reference** (Section 16) — Add the new workflow to the table.
5. **Update Table of Contents** — Add the new section.
6. **Bump the version** at the top of this file.

### Format Template for New Workflows

Use this template when adding a new workflow:

```
## Workflow N: [Workflow Name]

### N.1 [First Phase]

```
  [Role] → [Page / Action]
    │
    ▼
  [Step description]
    │
    ▼
  [Next step]
```

### N.2 [Second Phase]

### Flow Summary

```
  ┌──────────┐   ┌──────────┐   ┌──────────┐
  │  Step 1  │ → │  Step 2  │ → │  Step 3  │
  └──────────┘   └──────────┘   └──────────┘
```
```

---

*This guide describes the end-to-end business processes for **Guha Institute Management System**. Update it whenever new features or workflows are added.*
