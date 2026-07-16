import os
from datetime import datetime, date, timedelta
from app import create_app
from app.extensions import db
from app.models import Course, Student, Tutor, Attendance, FeeRecord, Enquiry, User, LeaveRequest, ExpenseCategory, Expense
from werkzeug.security import generate_password_hash

def seed_database():
    print("Starting database seeding...")
    
    # 1. Clean existing tables
    db.drop_all()
    db.create_all()
    print("Database tables re-created successfully.")
    
    # 1.5. Add default Users (Admin & Staff)
    admin_user = User(
        username="admin",
        password_hash=generate_password_hash("admin123"),
        role="Admin",
        name="System Administrator",
        email="admin@institute.edu"
    )
    staff_user = User(
        username="staff",
        password_hash=generate_password_hash("staff123"),
        role="Staff",
        name="Operations Staff",
        email="staff@institute.edu"
    )
    db.session.add(admin_user)
    db.session.add(staff_user)
    db.session.commit()
    print("Added default users (Admin & Staff).")
    
    # 2. Add Courses
    courses_data = [
        {
            "name": "Python & Backend Automation",
            "code": "PY-101",
            "description": "Comprehensive course covering Python syntax, data structures, scripting, and system automation scripts.",
            "duration_weeks": 8,
            "duration_unit": "weeks",
            "fees": 8000.0,
            "gst_applicable": True,
            "syllabus": "Week 1: Introduction to Variables & Loops\nWeek 2: Data Structures (Lists, Dicts, Tuples)\nWeek 3: Functions & Modular Programming\nWeek 4: File I/O & Exception Handling\nWeek 5: Core Automation (OS, Subprocess, Requests)\nWeek 6: SQLite & Database Queries\nWeek 7: Web Scraping with BeautifulSoup\nWeek 8: Capstone Automation Project"
        },
        {
            "name": "Full-stack Modern Web Development",
            "code": "WEB-301",
            "description": "Create stunning, fully responsive interfaces using modern HTML5, CSS3, Bootstrap 5, interactive JavaScript, and Flask backends.",
            "duration_weeks": 12,
            "duration_unit": "weeks",
            "fees": 12000.0,
            "gst_applicable": True,
            "syllabus": "Week 1-2: HTML5 Semantic Elements & CSS Grid\nWeek 3-4: Bootstrap Layouts & Custom Themes\nWeek 5-6: JavaScript DOM & Async Fetch Requests\nWeek 7-8: Flask Web Framework Routes\nWeek 9-10: Database Integration (SQLAlchemy)\nWeek 11-12: Full Stack Deployment & Responsive QA"
        },
        {
            "name": "Structured SQL & Database Design",
            "code": "DB-202",
            "description": "Master schemas, table relations, indexes, transactions, and performance tuning inside SQLite and PostgreSQL.",
            "duration_weeks": 6,
            "duration_unit": "weeks",
            "fees": 300.0,
            "syllabus": "Week 1: Relational Schema & Entity Diagrams\nWeek 2: Basic SQL Queries (Select, Where, Join)\nWeek 3: Subqueries, Group By & Aggregations\nWeek 4: Table Indexes & Query Optimizations\nWeek 5: Database Constraints & Transactions\nWeek 6: Designing Production Grade Architectures"
        },
        {
            "name": "Data Science & Pandas Fundamentals",
            "code": "DS-404",
            "description": "Introduction to data analysis, scientific plots, Pandas, NumPy, and simple linear regression models in Python.",
            "duration_weeks": 10,
            "duration_unit": "weeks",
            "fees": 500.0,
            "syllabus": "Week 1: Python for Data Analysis Overview\nWeek 2: NumPy Arrays & Numeric Computations\nWeek 3: Pandas DataFrames & Loading CSV/SQL\nWeek 4: Data Cleaning & Handling Missing Values\nWeek 5: Matplotlib & Seaborn Data Plots\nWeek 6: Exploratory Data Analysis Pipelines\nWeek 7: Grouping, Joining & Splitting Datasets\nWeek 8: Introduction to Scikit-Learn\nWeek 9: Predictive Modeling & Evaluations\nWeek 10: Final Analytical Dashboard Presentation"
        }
    ]
    
    courses = []
    for c in courses_data:
        course = Course(**c)
        db.session.add(course)
        courses.append(course)
    db.session.commit()
    print(f"Added {len(courses)} courses.")

    # 3. Add Tutors
    tutors_data = [
        {
            "name": "Jane Doe",
            "email": "jane.doe@institute.edu",
            "phone": "555-0101",
            "specialization": "Python & Backend Systems",
            "status": "Active"
        },
        {
            "name": "John Smith",
            "email": "john.smith@institute.edu",
            "phone": "555-0102",
            "specialization": "Front-end & CSS Architecture",
            "status": "Active"
        },
        {
            "name": "Alan Turing",
            "email": "alan.turing@institute.edu",
            "phone": "555-0103",
            "specialization": "Databases & Algorithms",
            "status": "Active"
        }
    ]
    
    tutors = []
    for t in tutors_data:
        tutor = Tutor(**t)
        # Assign courses
        if "Python" in tutor.specialization:
            tutor.courses.append(courses[0]) # Python
            tutor.courses.append(courses[3]) # Data Science
        elif "Front-end" in tutor.specialization:
            tutor.courses.append(courses[1]) # Web
        elif "Databases" in tutor.specialization:
            tutor.courses.append(courses[2]) # Database
            
        db.session.add(tutor)
        tutors.append(tutor)
    db.session.commit()
    print(f"Added {len(tutors)} tutors.")

    # 4. Add Students
    students_data = [
        {
            "name": "Alice Cooper",
            "email": "alice@gmail.com",
            "phone": "555-0201",
            "status": "Active"
        },
        {
            "name": "Bob Dylan",
            "email": "bob@gmail.com",
            "phone": "555-0202",
            "status": "Active"
        },
        {
            "name": "Charlie Chaplin",
            "email": "charlie@gmail.com",
            "phone": "555-0203",
            "status": "Active"
        },
        {
            "name": "Diana Prince",
            "email": "diana@gmail.com",
            "phone": "555-0204",
            "status": "Active"
        }
    ]
    
    students = []
    for i, s in enumerate(students_data):
        student = Student(**s)
        # Assign courses
        if i == 0:
            student.courses.append(courses[0]) # Python
            student.courses.append(courses[2]) # SQL
        elif i == 1:
            student.courses.append(courses[1]) # Web
        elif i == 2:
            student.courses.append(courses[0]) # Python
        elif i == 3:
            student.courses.append(courses[3]) # Data Science
            
        db.session.add(student)
        students.append(student)
    db.session.commit()
    print(f"Added {len(students)} students.")

    # 5. Add Fee Records
    # Alice Cooper paid PY-101 (fee 8000 + GST 1440 = 9440) and partial DB-202
    # Bob Dylan paid partial WEB-301 (fee 12000 + GST 2160 = 14160)
    # Charlie Chaplin paid PY-101 (fee 8000 + GST 1440 = 9440)
    # Diana Prince has paid nothing (outstanding)
    today = date.today()
    fee_records = [
        FeeRecord(student_id=students[0].id, amount_paid=9440.0, payment_date=today - timedelta(days=20), payment_method="Bank Transfer", remarks="Python Full Course Fee (incl GST)"),
        FeeRecord(student_id=students[0].id, amount_paid=150.0, payment_date=today - timedelta(days=5), payment_method="UPI", remarks="SQL Part Payment"),
        FeeRecord(student_id=students[1].id, amount_paid=5000.0, payment_date=today - timedelta(days=15), payment_method="Card", remarks="Web Dev Part Payment"),
        FeeRecord(student_id=students[2].id, amount_paid=9440.0, payment_date=today - timedelta(days=12), payment_method="UPI", remarks="Python full course payment (incl GST)")
    ]
    for fr in fee_records:
        db.session.add(fr)
    db.session.commit()
    print("Added fee transaction records.")

    # 6. Add Enquiries
    enquiries = [
        Enquiry(student_name="Bruce Wayne", email="bruce@waynecorp.com", phone="555-8888", course_id=courses[0].id, source="Social Media", status="New", notes="Interested in Python scripting for automation. Prefers evening batches."),
        Enquiry(student_name="Clark Kent", email="clark@dailyplanet.com", phone="555-9999", course_id=courses[1].id, source="Referral", status="Contacted", notes="Spoke about HTML/CSS course. Says he will visit lab on Wednesday to finalize enrollment."),
        Enquiry(student_name="Barry Allen", email="barry@star.labs", phone="555-7777", course_id=courses[2].id, source="Website", status="Converted", notes="Enquired about relational database optimization. Immediately enrolled (mapped to Charlie Cooper)."),
        Enquiry(student_name="Selina Kyle", email="selina@cat.org", phone="555-4444", course_id=courses[1].id, source="Walk-in", status="Lost", notes="Enquired on full-stack but courses was too expensive for budget. Might follow up later.")
    ]
    for enq in enquiries:
        db.session.add(enq)
    db.session.commit()
    print("Added prospect enquiries.")

    # 7. Add Attendance History
    # We will seed attendance for the past 5 days
    # Alice: present all
    # Bob: absent on day -3, present others
    # Charlie: late on day -2, present others
    # Diana: absent on day -1 and day -2 (Low attendance simulator)
    for day_offset in range(5, 0, -1):
        target_date = today - timedelta(days=day_offset)
        
        # Student 1: Alice
        db.session.add(Attendance(person_type="student", person_id=students[0].id, date=target_date, status="Present", marked_by="manual"))
        # Student 2: Bob
        s2_status = "Absent" if day_offset == 3 else "Present"
        db.session.add(Attendance(person_type="student", person_id=students[1].id, date=target_date, status=s2_status, marked_by="manual"))
        # Student 3: Charlie
        s3_status = "Late" if day_offset == 2 else "Present"
        db.session.add(Attendance(person_type="student", person_id=students[2].id, date=target_date, status=s3_status, marked_by="qr"))
        # Student 4: Diana (Absent twice - triggering risk predictor)
        s4_status = "Absent" if day_offset in [1, 2] else "Present"
        db.session.add(Attendance(person_type="student", person_id=students[3].id, date=target_date, status=s4_status, marked_by="manual"))
        
        # Tutors present always
        db.session.add(Attendance(person_type="tutor", person_id=tutors[0].id, date=target_date, status="Present", marked_by="manual"))
        db.session.add(Attendance(person_type="tutor", person_id=tutors[1].id, date=target_date, status="Present", marked_by="qr"))
        db.session.add(Attendance(person_type="tutor", person_id=tutors[2].id, date=target_date, status="Present", marked_by="manual"))
        
    db.session.commit()
    print("Added historical attendance records.")

    print("Database seeding completed successfully!")

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        seed_database()
