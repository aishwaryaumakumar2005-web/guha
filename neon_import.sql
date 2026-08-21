BEGIN TRANSACTION;
CREATE TABLE attendance (
	id INTEGER NOT NULL, 
	person_type VARCHAR(10) NOT NULL, 
	person_id INTEGER NOT NULL, 
	date DATE NOT NULL, 
	status VARCHAR(20), 
	marked_by VARCHAR(10), 
	timestamp DATETIME, 
	PRIMARY KEY (id)
);
INSERT INTO "attendance" VALUES(1,'student',1,'2026-06-17','Present','manual','2026-06-22 04:40:17.894807');
INSERT INTO "attendance" VALUES(2,'student',2,'2026-06-17','Present','manual','2026-06-22 04:40:17.897628');
INSERT INTO "attendance" VALUES(3,'student',3,'2026-06-17','Present','qr','2026-06-22 04:40:17.898952');
INSERT INTO "attendance" VALUES(4,'student',4,'2026-06-17','Present','manual','2026-06-22 04:40:17.900236');
INSERT INTO "attendance" VALUES(5,'tutor',1,'2026-06-17','Present','manual','2026-06-22 04:40:17.905176');
INSERT INTO "attendance" VALUES(6,'tutor',2,'2026-06-17','Present','qr','2026-06-22 04:40:17.906461');
INSERT INTO "attendance" VALUES(7,'tutor',3,'2026-06-17','Present','manual','2026-06-22 04:40:17.909449');
INSERT INTO "attendance" VALUES(8,'student',1,'2026-06-18','Present','manual','2026-06-22 04:40:17.909454');
INSERT INTO "attendance" VALUES(9,'student',2,'2026-06-18','Present','manual','2026-06-22 04:40:17.909456');
INSERT INTO "attendance" VALUES(10,'student',3,'2026-06-18','Present','qr','2026-06-22 04:40:17.909457');
INSERT INTO "attendance" VALUES(11,'student',4,'2026-06-18','Present','manual','2026-06-22 04:40:17.909459');
INSERT INTO "attendance" VALUES(12,'tutor',1,'2026-06-18','Present','manual','2026-06-22 04:40:17.909461');
INSERT INTO "attendance" VALUES(13,'tutor',2,'2026-06-18','Present','qr','2026-06-22 04:40:17.909463');
INSERT INTO "attendance" VALUES(14,'tutor',3,'2026-06-18','Present','manual','2026-06-22 04:40:17.909465');
INSERT INTO "attendance" VALUES(15,'student',1,'2026-06-19','Present','manual','2026-06-22 04:40:17.909467');
INSERT INTO "attendance" VALUES(16,'student',2,'2026-06-19','Absent','manual','2026-06-22 04:40:17.909468');
INSERT INTO "attendance" VALUES(17,'student',3,'2026-06-19','Present','qr','2026-06-22 04:40:17.909470');
INSERT INTO "attendance" VALUES(18,'student',4,'2026-06-19','Present','manual','2026-06-22 04:40:17.909472');
INSERT INTO "attendance" VALUES(19,'tutor',1,'2026-06-19','Present','manual','2026-06-22 04:40:17.909474');
INSERT INTO "attendance" VALUES(20,'tutor',2,'2026-06-19','Present','qr','2026-06-22 04:40:17.909475');
INSERT INTO "attendance" VALUES(21,'tutor',3,'2026-06-19','Present','manual','2026-06-22 04:40:17.909477');
INSERT INTO "attendance" VALUES(22,'student',1,'2026-06-20','Present','manual','2026-06-22 04:40:17.909479');
INSERT INTO "attendance" VALUES(23,'student',2,'2026-06-20','Present','manual','2026-06-22 04:40:17.909480');
INSERT INTO "attendance" VALUES(24,'student',3,'2026-06-20','Late','qr','2026-06-22 04:40:17.909482');
INSERT INTO "attendance" VALUES(25,'student',4,'2026-06-20','Absent','manual','2026-06-22 04:40:17.909484');
INSERT INTO "attendance" VALUES(26,'tutor',1,'2026-06-20','Present','manual','2026-06-22 04:40:17.909486');
INSERT INTO "attendance" VALUES(27,'tutor',2,'2026-06-20','Present','qr','2026-06-22 04:40:17.909487');
INSERT INTO "attendance" VALUES(28,'tutor',3,'2026-06-20','Present','manual','2026-06-22 04:40:17.909489');
INSERT INTO "attendance" VALUES(29,'student',1,'2026-06-21','Present','manual','2026-06-22 04:40:17.909491');
INSERT INTO "attendance" VALUES(30,'student',2,'2026-06-21','Present','manual','2026-06-22 04:40:17.909492');
INSERT INTO "attendance" VALUES(31,'student',3,'2026-06-21','Present','qr','2026-06-22 04:40:17.909494');
INSERT INTO "attendance" VALUES(32,'student',4,'2026-06-21','Absent','manual','2026-06-22 04:40:17.909496');
INSERT INTO "attendance" VALUES(33,'tutor',1,'2026-06-21','Present','manual','2026-06-22 04:40:17.909498');
INSERT INTO "attendance" VALUES(34,'tutor',2,'2026-06-21','Present','qr','2026-06-22 04:40:17.909499');
INSERT INTO "attendance" VALUES(35,'tutor',3,'2026-06-21','Present','manual','2026-06-22 04:40:17.909501');
INSERT INTO "attendance" VALUES(36,'student',1,'2026-06-26','Present','manual','2026-06-26 05:28:48.439525');
INSERT INTO "attendance" VALUES(37,'student',2,'2026-06-26','Present','manual','2026-06-26 05:37:07.555302');
INSERT INTO "attendance" VALUES(38,'student',3,'2026-06-26','Present','manual','2026-06-26 05:58:41.934554');
INSERT INTO "attendance" VALUES(39,'student',4,'2026-06-26','Present','manual','2026-06-26 05:58:42.931346');
INSERT INTO "attendance" VALUES(40,'student',6,'2026-06-26','Present','manual','2026-06-26 05:58:45.105086');
INSERT INTO "attendance" VALUES(41,'student',5,'2026-06-26','Present','manual','2026-06-26 05:58:46.101094');
INSERT INTO "attendance" VALUES(42,'student',7,'2026-06-26','Present','manual','2026-06-26 05:58:47.357765');
INSERT INTO "attendance" VALUES(43,'student',8,'2026-06-26','Present','manual','2026-06-26 05:58:48.315717');
INSERT INTO "attendance" VALUES(44,'tutor',1,'2026-06-26','Present','manual','2026-06-26 06:01:52.648468');
INSERT INTO "attendance" VALUES(45,'student',9,'2026-06-26','Present','manual','2026-06-26 06:15:45.189265');
INSERT INTO "attendance" VALUES(46,'student',10,'2026-06-26','Present','manual','2026-06-26 06:15:46.430364');
INSERT INTO "attendance" VALUES(47,'tutor',2,'2026-06-26','Present','manual','2026-06-26 06:19:41.169248');
INSERT INTO "attendance" VALUES(48,'student',11,'2026-06-26','Present','manual','2026-06-26 06:19:59.629772');
INSERT INTO "attendance" VALUES(49,'student',12,'2026-06-26','Present','manual','2026-06-26 06:20:00.814017');
INSERT INTO "attendance" VALUES(50,'student',18,'2026-06-26','Present','manual','2026-06-26 06:54:15.884930');
INSERT INTO "attendance" VALUES(51,'student',17,'2026-06-26','Present','manual','2026-06-26 06:54:16.950143');
INSERT INTO "attendance" VALUES(52,'student',16,'2026-06-26','Present','manual','2026-06-26 06:54:18.051154');
INSERT INTO "attendance" VALUES(53,'student',15,'2026-06-26','Present','manual','2026-06-26 06:54:21.267747');
INSERT INTO "attendance" VALUES(54,'student',14,'2026-06-26','Present','manual','2026-06-26 06:54:22.370908');
INSERT INTO "attendance" VALUES(55,'student',13,'2026-06-26','Present','manual','2026-06-26 06:54:24.381331');
INSERT INTO "attendance" VALUES(56,'tutor',3,'2026-06-26','Present','manual','2026-06-26 06:54:37.080089');
INSERT INTO "attendance" VALUES(57,'tutor',4,'2026-06-26','Present','manual','2026-06-26 06:54:39.540465');
CREATE TABLE audit_log (
	id INTEGER NOT NULL, 
	user_id INTEGER, 
	username VARCHAR(50), 
	action VARCHAR(10) NOT NULL, 
	entity_type VARCHAR(50) NOT NULL, 
	entity_id INTEGER, 
	changes TEXT, 
	timestamp DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user (id) ON DELETE SET NULL
);
INSERT INTO "audit_log" VALUES(1,1,'admin','INSERT','Student',23,'{"name": "AuditTest", "email": "audit_04dcad07@test.com", "phone": "9999999999", "enrollment_date": "2026-07-04", "status": "Active", "qr_code_uuid": "ecab65fc-cc60-4433-b9f1-c2e98b04fff6"}','2026-07-04 07:28:21.146621');
INSERT INTO "audit_log" VALUES(2,1,'admin','DELETE','Student',23,'{"before": {"id": "23", "name": "AuditTest2", "email": "audit_04dcad07@test.com", "phone": "9999999998", "enrollment_date": "2026-07-04", "status": "Active", "qr_code_uuid": "ecab65fc-cc60-4433-b9f1-c2e98b04fff6"}}','2026-07-04 07:28:21.359253');
INSERT INTO "audit_log" VALUES(3,1,'admin','INSERT','Student',23,'{"name": "AuditTest", "email": "audit_8413c136@test.com", "phone": "9999999999", "enrollment_date": "2026-07-04", "status": "Active", "qr_code_uuid": "2019c621-dd37-404c-b83c-b53c68e26306"}','2026-07-04 07:28:47.739249');
INSERT INTO "audit_log" VALUES(4,1,'admin','DELETE','Student',23,'{"before": {"id": "23", "name": "AuditTest2", "email": "audit_8413c136@test.com", "phone": "9999999998", "enrollment_date": "2026-07-04", "status": "Active", "qr_code_uuid": "2019c621-dd37-404c-b83c-b53c68e26306"}}','2026-07-04 07:28:47.941142');
INSERT INTO "audit_log" VALUES(5,1,'admin','INSERT','Student',23,'{"name": "AuditTest", "email": "audit_c7bc49a0@test.com", "phone": "9999999999", "enrollment_date": "2026-07-04", "status": "Active", "qr_code_uuid": "b8754559-135f-4d9c-847b-693f3c980b4c"}','2026-07-04 07:30:15.082982');
INSERT INTO "audit_log" VALUES(6,1,'admin','UPDATE','Student',23,'{"name": {"from": "AuditTest", "to": "AuditTest2"}, "phone": {"from": "9999999999", "to": "9999999998"}}','2026-07-04 07:30:15.221612');
INSERT INTO "audit_log" VALUES(7,1,'admin','DELETE','Student',23,'{"before": {"name": "AuditTest2", "email": "audit_c7bc49a0@test.com", "phone": "9999999998", "enrollment_date": "2026-07-04", "status": "Active", "qr_code_uuid": "b8754559-135f-4d9c-847b-693f3c980b4c"}}','2026-07-04 07:30:15.283870');
INSERT INTO "audit_log" VALUES(8,1,'admin','INSERT','Student',23,'{"name": "TestStudent", "email": "test@test.com", "phone": "9876543210", "enrollment_date": "2026-07-05", "status": "Active", "qr_code_uuid": "0b32f7b7-0efc-4391-96a3-6821b1b530a5"}','2026-07-05 19:03:34.836429');
INSERT INTO "audit_log" VALUES(9,1,'admin','INSERT','Course',10,'{"name": "TestCourse", "code": "TC101", "description": "", "duration_weeks": "12", "duration_unit": "weeks", "fees": "5000.0", "gst_applicable": "False", "syllabus": ""}','2026-07-05 19:03:35.004951');
INSERT INTO "audit_log" VALUES(10,1,'admin','INSERT','Enquiry',5,'{"student_name": "TestEnq", "email": "", "phone": "9876543210", "course_id": "1", "source": "Walk-in", "status": "New", "notes": "", "created_at": "2026-07-05T19:03:35.069287"}','2026-07-05 19:03:35.069913');
INSERT INTO "audit_log" VALUES(11,1,'admin','INSERT','FeeRecord',17,'{"student_id": "1", "amount_paid": "1000.0", "payment_date": "2026-07-06", "payment_method": "Cash", "remarks": ""}','2026-07-05 19:03:35.164538');
INSERT INTO "audit_log" VALUES(12,1,'admin','INSERT','Tutor',5,'{"name": "TestTutor", "email": "tutor@test.com", "phone": "9876543210", "specialization": "", "status": "Active", "qr_code_uuid": "23fe67cf-600a-40a7-8e45-83fda4980afd"}','2026-07-05 19:03:35.227018');
INSERT INTO "audit_log" VALUES(13,1,'admin','INSERT','LeaveRequest',1,'{"user_id": "1", "start_date": "2026-07-10", "end_date": "2026-07-12", "reason": "Test leave", "status": "Pending", "created_at": "2026-07-05T19:03:46.179274"}','2026-07-05 19:03:46.180011');
INSERT INTO "audit_log" VALUES(14,1,'admin','UPDATE','Student',1,'{"name": {"from": "J.P. Pranavi", "to": "UpdatedName"}, "email": {"from": "pranavi@gmail.com", "to": "updated@test.com"}, "phone": {"from": "9941032524", "to": "9876543210"}}','2026-07-05 19:03:56.201782');
INSERT INTO "audit_log" VALUES(15,1,'admin','UPDATE','Course',1,'{"name": {"from": "Python & Backend Automation", "to": "UpdatedCourse"}, "code": {"from": "PY-101", "to": "UC999"}, "description": {"from": "Comprehensive course covering Python syntax, data structures, scripting, and system automation scripts.", "to": ""}, "duration_weeks": {"from": "8", "to": "12"}, "fees": {"from": "450.0", "to": "5000.0"}, "gst_applicable": {"from": "True", "to": "False"}, "syllabus": {"from": "Week 1: Introduction to Variables & Loops\nWeek 2: Data Structures (Lists, Dicts, Tuples)\nWeek 3: Functions & Modular Programming\nWeek 4: File I/O & Exception Handling\nWeek 5: Core Automation (OS, Subprocess, Requests)\nWeek 6: SQLite & Database Queries\nWeek 7: Web Scraping with BeautifulSoup\nWeek 8: Capstone Automation Project", "to": ""}}','2026-07-05 19:03:56.323997');
INSERT INTO "audit_log" VALUES(16,1,'admin','UPDATE','Tutor',1,'{"name": {"from": "ISHWARYA KUMAR", "to": "UpdatedTutor"}, "email": {"from": "ishwaryakumar417@gmail.com", "to": "tutor2@test.com"}, "phone": {"from": "9715692647", "to": "9876543210"}, "specialization": {"from": " sketching, drawing", "to": ""}}','2026-07-05 19:03:56.395787');
INSERT INTO "audit_log" VALUES(17,1,'admin','DELETE','Student',22,'{"before": {"name": "Krishika", "email": "krishika@gmail.com", "phone": "9944543175", "enrollment_date": "2026-06-26", "status": "Active", "qr_code_uuid": "80730a1c-bdf5-4a9f-bb34-2da7352f4376"}}','2026-07-05 19:03:56.541467');
INSERT INTO "audit_log" VALUES(18,1,'admin','INSERT','PayrollRecord',2,'{"tutor_id": "1", "month": "7", "year": "2026", "base_amount": "25000.0", "commission_amount": "0.0", "bonus_amount": "1000.0", "tds_amount": "2600.0", "other_deductions": "500.0", "net_amount": "22900.0", "status": "Draft", "expense_id": null, "paid_date": null, "notes": null, "created_at": "2026-07-05T19:04:06.062676", "updated_at": "2026-07-05T19:04:06.062683"}','2026-07-05 19:04:06.063400');
INSERT INTO "audit_log" VALUES(19,1,'admin','UPDATE','Student',1,'{"phone": {"from": "9876543210", "to": "987654321044"}}','2026-07-05 19:21:44.821334');
INSERT INTO "audit_log" VALUES(20,1,'admin','UPDATE','Student',1,'{"phone": {"from": "9876543210", "to": "987654321044"}}','2026-07-05 19:21:44.833632');
INSERT INTO "audit_log" VALUES(21,1,'admin','DELETE','FeeRecord',1,'{"before": {"student_id": "1", "amount_paid": "1000.0", "payment_date": "2026-06-26", "payment_method": "Savings Account", "remarks": ""}}','2026-07-05 19:43:05.612488');
INSERT INTO "audit_log" VALUES(22,1,'admin','DELETE','FeeRecord',17,'{"before": {"student_id": "1", "amount_paid": "1000.0", "payment_date": "2026-07-06", "payment_method": "Cash", "remarks": ""}}','2026-07-05 19:43:05.613460');
INSERT INTO "audit_log" VALUES(23,1,'admin','DELETE','Student',1,'{"before": {"name": "UpdatedName", "email": "updated@test.com", "phone": "987654321044", "enrollment_date": "2026-06-26", "status": "Active", "qr_code_uuid": "a23014a7-19eb-406c-82da-5efa3290ca00"}}','2026-07-05 19:43:05.618933');
INSERT INTO "audit_log" VALUES(24,1,'admin','DELETE','Tutor',5,'{"before": {"name": "TestTutor", "email": "tutor@test.com", "phone": "9876543210", "specialization": "", "status": "Active", "qr_code_uuid": "23fe67cf-600a-40a7-8e45-83fda4980afd"}}','2026-07-05 19:44:57.245981');
INSERT INTO "audit_log" VALUES(25,1,'admin','DELETE','Tutor',2,'{"before": {"name": "UMA MAHESHWARI", "email": "uma@gmail.com", "phone": "9790286498", "specialization": "Communication", "status": "Active", "qr_code_uuid": "9ac77636-03e4-43c0-a632-6d933a6a7cf1"}}','2026-07-05 19:46:38.226311');
INSERT INTO "audit_log" VALUES(26,1,'admin','INSERT','Tutor',5,'{"name": "DeleteTestTutor", "email": "deletetest@test.com", "phone": "9876543210", "specialization": "", "status": "Active", "qr_code_uuid": "52a26c49-2bf4-4e34-bb65-c8d80ce2f743"}','2026-07-05 19:46:56.314218');
INSERT INTO "audit_log" VALUES(27,1,'admin','UPDATE','Tutor',5,'{"name": {"from": "DeleteTestTutor", "to": "DeleteTestTutorRenamed"}, "email": {"from": "deletetest@test.com", "to": "deletetest2@test.com"}, "phone": {"from": "9876543210", "to": "9876543211"}}','2026-07-05 19:46:56.364749');
INSERT INTO "audit_log" VALUES(28,1,'admin','DELETE','Tutor',5,'{"before": {"name": "DeleteTestTutorRenamed", "email": "deletetest2@test.com", "phone": "9876543211", "specialization": "", "status": "Active", "qr_code_uuid": "52a26c49-2bf4-4e34-bb65-c8d80ce2f743"}}','2026-07-05 19:46:56.423427');
INSERT INTO "audit_log" VALUES(29,1,'admin','INSERT','Tutor',5,'{"name": "FreshTutor", "email": "fresh@test.com", "phone": "1234567890", "specialization": "Math", "status": "Active", "qr_code_uuid": "41e73caa-3da0-4106-a4c2-486027e9489d"}','2026-07-05 19:48:11.076593');
INSERT INTO "audit_log" VALUES(30,1,'admin','INSERT','Tutor',6,'{"name": "DeleteTest", "email": "deletetest@test.com", "phone": "1112223333", "specialization": "Test", "status": "Active", "qr_code_uuid": "5416c0ca-6bc6-4e59-ad6e-20bc8f2dad09"}','2026-07-05 19:53:16.196869');
INSERT INTO "audit_log" VALUES(31,1,'admin','DELETE','Tutor',6,'{"before": {"name": "DeleteTest", "email": "deletetest@test.com", "phone": "1112223333", "specialization": "Test", "status": "Active", "qr_code_uuid": "5416c0ca-6bc6-4e59-ad6e-20bc8f2dad09"}}','2026-07-05 19:53:21.957167');
INSERT INTO "audit_log" VALUES(32,1,'admin','DELETE','Tutor',5,'{"before": {"name": "FreshTutor", "email": "fresh@test.com", "phone": "1234567890", "specialization": "Math", "status": "Active", "qr_code_uuid": "41e73caa-3da0-4106-a4c2-486027e9489d"}}','2026-07-05 19:53:31.471855');
INSERT INTO "audit_log" VALUES(33,1,'admin','DELETE','Tutor',4,'{"before": {"name": "VELMURUGAN", "email": "veklmurugan@gmail.com", "phone": "9344440438", "specialization": "dance course", "status": "Active", "qr_code_uuid": "7edf16ae-5261-4b9f-be11-44bca278b5ff"}}','2026-07-05 19:53:49.808381');
INSERT INTO "audit_log" VALUES(34,1,'admin','INSERT','Tutor',4,'{"name": "UserScenario", "email": "user-scenario@test.com", "phone": "9998887770", "specialization": "Physics", "status": "Active", "qr_code_uuid": "2c014e4d-5f6e-4522-9756-c639f01a3102"}','2026-07-05 19:54:01.622630');
INSERT INTO "audit_log" VALUES(35,1,'admin','UPDATE','Tutor',4,'{"name": {"from": "UserScenario", "to": "UserScenarioEdited"}, "email": {"from": "user-scenario@test.com", "to": "user-edited@test.com"}, "specialization": {"from": "Physics", "to": "Chemistry"}}','2026-07-05 19:54:16.857907');
INSERT INTO "audit_log" VALUES(36,1,'admin','DELETE','Tutor',4,'{"before": {"name": "UserScenarioEdited", "email": "user-edited@test.com", "phone": "9998887770", "specialization": "Chemistry", "status": "Active", "qr_code_uuid": "2c014e4d-5f6e-4522-9756-c639f01a3102"}}','2026-07-05 19:54:16.961530');
INSERT INTO "audit_log" VALUES(37,1,'admin','INSERT','Tutor',4,'{"name": "ReproTest", "email": "repro@test.com", "phone": "1110002222", "specialization": "Test", "status": "Active", "qr_code_uuid": "9f109d11-58c7-4b9c-bafa-b6ccd8462527"}','2026-07-05 19:54:28.679436');
INSERT INTO "audit_log" VALUES(38,1,'admin','UPDATE','Tutor',3,'{"name": {"from": "SUDHARSHAN", "to": "SudharshanUpdated"}, "email": {"from": "sudharshan@gmail.com", "to": "sudharshan-updated@gmail.com"}, "phone": {"from": "9003505169", "to": "1234567890"}, "specialization": {"from": "Tuition", "to": "Math"}}','2026-07-05 19:54:29.216347');
INSERT INTO "audit_log" VALUES(39,1,'admin','DELETE','Tutor',3,'{"before": {"name": "SudharshanUpdated", "email": "sudharshan-updated@gmail.com", "phone": "1234567890", "specialization": "Math", "status": "Active", "qr_code_uuid": "3e256168-c66a-416b-97f6-a9ab4ef603e0"}}','2026-07-05 19:54:29.280347');
INSERT INTO "audit_log" VALUES(40,1,'admin','DELETE','Tutor',4,'{"before": {"name": "ReproTest", "email": "repro@test.com", "phone": "1110002222", "specialization": "Test", "status": "Active", "qr_code_uuid": "9f109d11-58c7-4b9c-bafa-b6ccd8462527"}}','2026-07-05 19:54:55.920764');
INSERT INTO "audit_log" VALUES(41,1,'admin','UPDATE','Student',1,'{"phone": {"from": "9941032524", "to": "99410325246"}}','2026-07-12 15:27:15.933174');
INSERT INTO "audit_log" VALUES(42,1,'admin','UPDATE','Student',1,'{"phone": {"from": "9941032524", "to": "99410325246"}}','2026-07-12 15:27:15.950194');
INSERT INTO "audit_log" VALUES(43,1,'admin','UPDATE','Student',1,'{"phone": {"from": "99410325246", "to": "9941032524"}}','2026-07-12 15:27:39.999327');
INSERT INTO "audit_log" VALUES(44,1,'admin','UPDATE','Student',1,'{"phone": {"from": "99410325246", "to": "9941032524"}}','2026-07-12 15:27:40.009721');
INSERT INTO "audit_log" VALUES(45,1,'admin','UPDATE','Student',1,'{"phone": {"from": "9941032524", "to": "99410325242"}}','2026-07-12 16:21:35.439678');
INSERT INTO "audit_log" VALUES(46,1,'admin','UPDATE','Student',1,'{"phone": {"from": "9941032524", "to": "99410325242"}}','2026-07-12 16:21:35.443628');
INSERT INTO "audit_log" VALUES(47,1,'admin','UPDATE','Student',1,'{"phone": {"from": "99410325242", "to": "9941032524"}}','2026-07-12 16:34:31.905159');
INSERT INTO "audit_log" VALUES(48,1,'admin','UPDATE','Student',1,'{"phone": {"from": "99410325242", "to": "9941032524"}}','2026-07-12 16:34:31.938270');
INSERT INTO "audit_log" VALUES(49,1,'admin','UPDATE','Student',1,'{"phone": {"from": "9941032524", "to": "99410325245"}}','2026-07-12 16:38:18.890516');
INSERT INTO "audit_log" VALUES(50,1,'admin','UPDATE','Student',1,'{"phone": {"from": "9941032524", "to": "99410325245"}}','2026-07-12 16:38:18.906538');
INSERT INTO "audit_log" VALUES(51,1,'admin','UPDATE','Student',1,'{"phone": {"from": "99410325245", "to": "9941032524"}}','2026-07-12 16:38:49.423369');
INSERT INTO "audit_log" VALUES(52,1,'admin','UPDATE','Student',1,'{"phone": {"from": "99410325245", "to": "9941032524"}}','2026-07-12 16:38:49.427382');
INSERT INTO "audit_log" VALUES(53,1,'admin','UPDATE','Student',1,'{"phone": {"from": "9941032524", "to": "99410325244"}}','2026-07-12 16:40:55.931603');
INSERT INTO "audit_log" VALUES(54,1,'admin','UPDATE','Student',1,'{"phone": {"from": "9941032524", "to": "99410325244"}}','2026-07-12 16:40:55.953642');
INSERT INTO "audit_log" VALUES(55,1,'admin','UPDATE','Student',1,'{"phone": {"from": "99410325244", "to": "9941032524"}}','2026-07-12 16:41:09.895753');
INSERT INTO "audit_log" VALUES(56,1,'admin','UPDATE','Course',2,'{"name": {"from": "Full-stack Modern Web Development", "to": "Full-stack Modern Web Developmentt"}, "syllabus": {"from": "Week 1-2: HTML5 Semantic Elements & CSS Grid\r\nWeek 3-4: Bootstrap Layouts & Custom Themes\r\nWeek 5-6: JavaScript DOM & Async Fetch Requests\r\nWeek 7-8: Flask Web Framework Routes\r\nWeek 9-10: Database Integration (SQLAlchemy)\r\nWeek 11-12: Full Stack Deployment & Responsive QA", "to": "Week 1-2: HTML5 Semantic Elements & CSS Grid\nWeek 3-4: Bootstrap Layouts & Custom Themes\nWeek 5-6: JavaScript DOM & Async Fetch Requests\nWeek 7-8: Flask Web Framework Routes\nWeek 9-10: Database Integration (SQLAlchemy)\nWeek 11-12: Full Stack Deployment & Responsive QA"}}','2026-07-12 16:42:32.210333');
INSERT INTO "audit_log" VALUES(57,1,'admin','UPDATE','Course',2,'{"name": {"from": "Full-stack Modern Web Development", "to": "Full-stack Modern Web Developmentt"}}','2026-07-12 16:42:32.228907');
INSERT INTO "audit_log" VALUES(58,1,'admin','UPDATE','Course',2,'{"name": {"from": "Full-stack Modern Web Developmentt", "to": "Full-stack Modern Web Development"}}','2026-07-12 16:42:49.479478');
INSERT INTO "audit_log" VALUES(59,1,'admin','UPDATE','Course',2,'{"name": {"from": "Full-stack Modern Web Developmentt", "to": "Full-stack Modern Web Development"}, "syllabus": {"from": "Week 1-2: HTML5 Semantic Elements & CSS Grid\nWeek 3-4: Bootstrap Layouts & Custom Themes\nWeek 5-6: JavaScript DOM & Async Fetch Requests\nWeek 7-8: Flask Web Framework Routes\nWeek 9-10: Database Integration (SQLAlchemy)\nWeek 11-12: Full Stack Deployment & Responsive QA", "to": "Week 1-2: HTML5 Semantic Elements & CSS Grid\r\nWeek 3-4: Bootstrap Layouts & Custom Themes\r\nWeek 5-6: JavaScript DOM & Async Fetch Requests\r\nWeek 7-8: Flask Web Framework Routes\r\nWeek 9-10: Database Integration (SQLAlchemy)\r\nWeek 11-12: Full Stack Deployment & Responsive QA"}}','2026-07-12 16:42:49.514045');
INSERT INTO "audit_log" VALUES(60,1,'admin','UPDATE','Student',10,'{"email": {"from": "megalai@gmail.com", "to": "megalai@gmail.comm"}}','2026-07-12 18:46:04.031263');
INSERT INTO "audit_log" VALUES(61,1,'admin','UPDATE','Student',10,'{"email": {"from": "megalai@gmail.com", "to": "megalai@gmail.comm"}}','2026-07-12 18:46:04.036154');
CREATE TABLE course (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	code VARCHAR(20) NOT NULL, 
	description TEXT, 
	duration_weeks INTEGER NOT NULL, 
	fees FLOAT NOT NULL, 
	syllabus TEXT, duration_unit VARCHAR(10) DEFAULT 'weeks', gst_applicable BOOLEAN DEFAULT 0, 
	PRIMARY KEY (id), 
	UNIQUE (code)
);
INSERT INTO "course" VALUES(1,'UpdatedCourse','UC999','',12,5000.0,'','weeks',0);
INSERT INTO "course" VALUES(2,'Full-stack Modern Web Development','WEB-301','Create stunning, fully responsive interfaces using modern HTML5, CSS3, Bootstrap 5, interactive JavaScript, and Flask backends.',3,650.0,'Week 1-2: HTML5 Semantic Elements & CSS Grid
Week 3-4: Bootstrap Layouts & Custom Themes
Week 5-6: JavaScript DOM & Async Fetch Requests
Week 7-8: Flask Web Framework Routes
Week 9-10: Database Integration (SQLAlchemy)
Week 11-12: Full Stack Deployment & Responsive QA','months',1);
INSERT INTO "course" VALUES(3,'Structured SQL & Database Design','DB-202','Master schemas, table relations, indexes, transactions, and performance tuning inside SQLite and PostgreSQL.',6,8000.0,'Week 1: Relational Schema & Entity Diagrams
Week 2: Basic SQL Queries (Select, Where, Join)
Week 3: Subqueries, Group By & Aggregations
Week 4: Table Indexes & Query Optimizations
Week 5: Database Constraints & Transactions
Week 6: Designing Production Grade Architectures','weeks',1);
INSERT INTO "course" VALUES(4,'Data Science & Pandas Fundamentals','DS-404','Introduction to data analysis, scientific plots, Pandas, NumPy, and simple linear regression models in Python.',10,25000.0,'Week 1: Python for Data Analysis Overview
Week 2: NumPy Arrays & Numeric Computations
Week 3: Pandas DataFrames & Loading CSV/SQL
Week 4: Data Cleaning & Handling Missing Values
Week 5: Matplotlib & Seaborn Data Plots
Week 6: Exploratory Data Analysis Pipelines
Week 7: Grouping, Joining & Splitting Datasets
Week 8: Introduction to Scikit-Learn
Week 9: Predictive Modeling & Evaluations
Week 10: Final Analytical Dashboard Presentation','weeks',1);
INSERT INTO "course" VALUES(5,'Drawing Class','YAD001','Comprehensive course covering drawing fundamentals, sketching techniques, shading, coloring, perspective, and creative artwork for beginners.',12,1000.0,'Week 1: Introduction to Drawing Tools & Basic Shapes
Week 2: Lines, Curves & Object Sketching
Week 3: Shading Techniques & Light Effects
Week 4: Still Life Drawing & Composition
Week 5: Nature & Landscape Drawing
Week 6 to 8: Human Face & Cartoon Character Drawing
Week 9: Color Theory & Creative Coloring Techniques
Week 10 to 12: Final Artwork & Portfolio Project','weeks',0);
INSERT INTO "course" VALUES(6,'SPOKEN ENGLISH','YASE002','Comprehensive course covering English speaking, grammar, vocabulary, pronunciation, listening, reading, writing, and real-life communication skills for beginners to intermediate learners.',12,2500.0,'Week 1: Introduction to Spoken English & Basic Greetings
Week 2: Parts of Speech & Sentence Formation
Week 3: Tenses – Present, Past & Future
Week 4: Vocabulary Building & Daily Use Words
Week 5: Pronunciation & Phonics Basics
Week 6: Listening Skills & Everyday Conversations
Week 7: Reading Comprehension & Fluency Practice
Week 8: Writing Simple Sentences, Emails & Messages
Week 9: Public Speaking & Self-Introduction
Week 10: Group Discussions & Role Play Activities
Week 11: Interview Skills & Professional Communication
Week 12: Final Speaking Assessment & Communication Project','weeks',0);
INSERT INTO "course" VALUES(7,'SUBJECT TUITION','YAT003','Comprehensive tuition program designed to strengthen academic concepts, improve problem-solving skills, enhance exam preparation, and build confidence through personalized guidance and regular assessments.',4,1000.0,'1. Student Assessment & Learning Plan
2. Problem Solving & Practice Exercises
3. Reading, Writing & Note-Making Techniques
4. Core Subject Concepts & Fundamentals
5. School Homework & Assignment Support
6. Time Management & Exam Strategies
7. Weekly Revision & Doubt Clearing Session
8. Model Test – I & Performance Analysis
9. Model Test – II & Individual Feedback
10. Complete Syllabus Revision & Important Questions
11. Final Assessment & Exam Preparation','weeks',0);
INSERT INTO "course" VALUES(8,'DANCE CLASS','YADA004','Comprehensive dance course designed to develop rhythm, coordination, flexibility, confidence, stage presence, and performance skills for beginners and intermediate learners.',20,1000.0,'1. Introduction to Dance, Warm-Up & Basic Body Movements
2. Rhythm, Timing & Footwork Techniques
3. Basic Dance Steps & Hand Movements
 4. Coordination, Balance & Body Control
 5. Choreography – Part I
6. Expressions, Facial Movements & Stage Presence
 7.  Choreography – Part II
 8. Dance Fitness, Flexibility & Endurance Training
9. Performance Skills & Formation Practice
10. Group Dance Choreography & Synchronization
11. Complete Routine Practice & Mock Performance
12. Final Stage Performance & Certificate Evaluation','weeks',0);
INSERT INTO "course" VALUES(9,'MUSIC CLASS','YAM005','Comprehensive music course covering the fundamentals of music, rhythm, notation, instrument techniques, vocal practice, and performance skills for beginners and intermediate learners.',20,2000.0,'Week 1: Introduction to Music, Rhythm & Basic Notes
Week 2: Finger Exercises / Voice Warm-Up Techniques
Week 3: Swaras, Scales & Basic Music Theory
Week 4: Simple Songs & Melody Practice
Week 5: Timing, Beat & Rhythm Exercises
Week 6: Intermediate Playing / Vocal Techniques
Week 7: Music Reading & Ear Training
Week 8: Expression, Dynamics & Performance Skills
Week 9: Advanced Songs & Practice Sessions
Week 10: Solo Performance & Confidence Building
Week 11: Complete Song Performance & Stage Preparation
Week 12: Final Performance, Assessment & Certificate Evaluation','weeks',0);
INSERT INTO "course" VALUES(10,'TestCourse','TC101','',12,5000.0,'','weeks',0);
CREATE TABLE enquiry (
	id INTEGER NOT NULL, 
	student_name VARCHAR(100) NOT NULL, 
	email VARCHAR(100), 
	phone VARCHAR(20) NOT NULL, 
	course_id INTEGER NOT NULL, 
	source VARCHAR(50), 
	status VARCHAR(20), 
	notes TEXT, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(course_id) REFERENCES course (id) ON DELETE CASCADE
);
INSERT INTO "enquiry" VALUES(1,'Bruce Wayne','bruce@waynecorp.com','555-8888',1,'Social Media','New','Interested in Python scripting for automation. Prefers evening batches.','2026-06-22 04:40:17.854166');
INSERT INTO "enquiry" VALUES(2,'Clark Kent','clark@dailyplanet.com','555-9999',2,'Referral','Contacted','Spoke about HTML/CSS course. Says he will visit lab on Wednesday to finalize enrollment.','2026-06-22 04:40:17.854171');
INSERT INTO "enquiry" VALUES(3,'Barry Allen','barry@star.labs','555-7777',3,'Website','Converted','Enquired about relational database optimization. Immediately enrolled (mapped to Charlie Cooper).','2026-06-22 04:40:17.854173');
INSERT INTO "enquiry" VALUES(4,'Selina Kyle','selina@cat.org','555-4444',2,'Walk-in','Lost','Enquired on full-stack but courses was too expensive for budget. Might follow up later.','2026-06-22 04:40:17.854175');
INSERT INTO "enquiry" VALUES(5,'TestEnq','','9876543210',1,'Walk-in','New','','2026-07-05 19:03:35.069287');
CREATE TABLE exam (
	id INTEGER NOT NULL, 
	course_id INTEGER NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	exam_date DATE NOT NULL, 
	max_marks FLOAT NOT NULL, 
	passing_marks FLOAT NOT NULL, 
	description TEXT, 
	created_at DATETIME, exam_type VARCHAR(10) DEFAULT manual, num_questions INTEGER DEFAULT 0, duration_minutes INTEGER DEFAULT 0, is_published BOOLEAN DEFAULT 0, 
	PRIMARY KEY (id), 
	FOREIGN KEY(course_id) REFERENCES course (id) ON DELETE CASCADE
);
INSERT INTO "exam" VALUES(2,1,'python','2026-06-29',100.0,40.0,'','2026-06-29 06:49:54.636965','manual',0,0,0);
INSERT INTO "exam" VALUES(3,6,'english','2026-06-29',100.0,40.0,'','2026-06-29 06:51:09.598622','manual',0,0,0);
CREATE TABLE exam_assignment (
	id INTEGER NOT NULL, 
	exam_id INTEGER NOT NULL, 
	student_id INTEGER NOT NULL, 
	assigned_by INTEGER NOT NULL, 
	assigned_at DATETIME, 
	due_date DATE, 
	status VARCHAR(20), 
	PRIMARY KEY (id), 
	FOREIGN KEY(exam_id) REFERENCES exam (id) ON DELETE CASCADE, 
	FOREIGN KEY(student_id) REFERENCES student (id) ON DELETE CASCADE, 
	FOREIGN KEY(assigned_by) REFERENCES user (id)
);
CREATE TABLE exam_score (
	id INTEGER NOT NULL, 
	exam_id INTEGER NOT NULL, 
	student_id INTEGER NOT NULL, 
	marks_obtained FLOAT NOT NULL, 
	remarks VARCHAR(200), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_exam_student UNIQUE (exam_id, student_id), 
	FOREIGN KEY(exam_id) REFERENCES exam (id) ON DELETE CASCADE, 
	FOREIGN KEY(student_id) REFERENCES student (id) ON DELETE CASCADE
);
CREATE TABLE expense (
	id INTEGER NOT NULL, 
	category_id INTEGER NOT NULL, 
	amount FLOAT NOT NULL, 
	description TEXT NOT NULL, 
	expense_date DATE NOT NULL, 
	created_by INTEGER, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(category_id) REFERENCES expense_category (id) ON DELETE CASCADE, 
	FOREIGN KEY(created_by) REFERENCES user (id)
);
INSERT INTO "expense" VALUES(1,1,10000.0,'rent paid','2026-06-12',1,'2026-06-27 09:37:52.749634');
INSERT INTO "expense" VALUES(2,7,5000.0,'car service','2026-06-12',1,'2026-06-27 09:38:35.449462');
INSERT INTO "expense" VALUES(3,4,500.0,'instagram boost','2026-06-10',1,'2026-06-27 09:39:28.041817');
INSERT INTO "expense" VALUES(4,6,500.0,'hdmi converter','2026-06-10',1,'2026-06-27 09:40:06.001735');
INSERT INTO "expense" VALUES(5,7,100.0,'food for vinayagam','2026-06-10',1,'2026-06-27 09:40:46.009370');
INSERT INTO "expense" VALUES(6,7,5000.0,'car service','2026-06-09',1,'2026-06-27 09:41:43.720200');
INSERT INTO "expense" VALUES(7,8,1700.0,'refund to web dev student','2026-06-16',1,'2026-06-27 09:43:45.044636');
INSERT INTO "expense" VALUES(8,9,1630.0,'paid to gst auditor ','2026-06-17',1,'2026-06-27 09:46:24.617690');
CREATE TABLE expense_category (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	description TEXT, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);
INSERT INTO "expense_category" VALUES(1,'Rent',NULL);
INSERT INTO "expense_category" VALUES(2,'Salary',NULL);
INSERT INTO "expense_category" VALUES(3,'Electricity',NULL);
INSERT INTO "expense_category" VALUES(4,'Internet',NULL);
INSERT INTO "expense_category" VALUES(5,'Marketing',NULL);
INSERT INTO "expense_category" VALUES(6,'Maintenance',NULL);
INSERT INTO "expense_category" VALUES(7,'Others',NULL);
INSERT INTO "expense_category" VALUES(8,'Refund',NULL);
INSERT INTO "expense_category" VALUES(9,'GST Auditor',NULL);
INSERT INTO "expense_category" VALUES(10,'GST expenses',NULL);
CREATE TABLE fee_record (
	id INTEGER NOT NULL, 
	student_id INTEGER NOT NULL, 
	amount_paid FLOAT NOT NULL, 
	payment_date DATE NOT NULL, 
	payment_method VARCHAR(50), 
	remarks VARCHAR(200), 
	PRIMARY KEY (id), 
	FOREIGN KEY(student_id) REFERENCES student (id) ON DELETE CASCADE
);
INSERT INTO "fee_record" VALUES(2,2,1000.0,'2026-06-26','Savings Account','');
INSERT INTO "fee_record" VALUES(3,3,1000.0,'2026-06-26','Cash','');
INSERT INTO "fee_record" VALUES(4,4,1000.0,'2026-06-26','Savings Account','');
INSERT INTO "fee_record" VALUES(5,5,1000.0,'2026-06-26','Savings Account','');
INSERT INTO "fee_record" VALUES(6,6,1000.0,'2026-06-26','Savings Account','');
INSERT INTO "fee_record" VALUES(7,7,1000.0,'2026-06-26','Savings Account','');
INSERT INTO "fee_record" VALUES(8,8,1000.0,'2026-06-25','Cash','');
INSERT INTO "fee_record" VALUES(9,9,1500.0,'2026-06-26','Cash','');
INSERT INTO "fee_record" VALUES(10,10,2000.0,'2026-06-26','Savings Account','');
INSERT INTO "fee_record" VALUES(11,11,1000.0,'2026-06-26','Cash','');
INSERT INTO "fee_record" VALUES(12,12,1000.0,'2026-06-26','Savings Account','');
INSERT INTO "fee_record" VALUES(13,16,1000.0,'2026-06-26','Savings Account','');
INSERT INTO "fee_record" VALUES(14,13,1000.0,'2026-06-26','Savings Account','');
INSERT INTO "fee_record" VALUES(15,14,1000.0,'2026-06-26','Savings Account','');
INSERT INTO "fee_record" VALUES(16,15,1000.0,'2026-06-26','Cash','');
CREATE TABLE form_submission (
	id INTEGER NOT NULL, 
	form_type VARCHAR(20) NOT NULL, 
	data TEXT NOT NULL, 
	submitted_at DATETIME, 
	processed BOOLEAN, 
	PRIMARY KEY (id)
);
INSERT INTO "form_submission" VALUES(1,'admission','{"name": "Test", "email": "t@t.com", "course": "Web", "phone": "123"}','2026-06-14 14:41:11.838551',0);
INSERT INTO "form_submission" VALUES(2,'admission','{"name": "Test", "email": "test@test.com"}','2026-06-14 14:46:23.037573',0);
CREATE TABLE leave_request (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE NOT NULL, 
	reason TEXT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user (id) ON DELETE CASCADE
);
INSERT INTO "leave_request" VALUES(1,1,'2026-07-10','2026-07-12','Test leave','Pending','2026-07-05 19:03:46.179274');
CREATE TABLE mcq_answer (
	id INTEGER NOT NULL, 
	mcq_attempt_id INTEGER NOT NULL, 
	mcq_question_id INTEGER NOT NULL, 
	selected_option VARCHAR(1), 
	is_correct BOOLEAN, 
	PRIMARY KEY (id), 
	FOREIGN KEY(mcq_attempt_id) REFERENCES mcq_attempt (id) ON DELETE CASCADE, 
	FOREIGN KEY(mcq_question_id) REFERENCES mcq_question (id) ON DELETE CASCADE
);
CREATE TABLE mcq_attempt (
	id INTEGER NOT NULL, 
	exam_id INTEGER NOT NULL, 
	student_id INTEGER NOT NULL, 
	start_time DATETIME, 
	end_time DATETIME, 
	score FLOAT, 
	total_marks FLOAT, 
	percentage FLOAT, 
	grade VARCHAR(2), 
	status VARCHAR(20), 
	PRIMARY KEY (id), 
	FOREIGN KEY(exam_id) REFERENCES exam (id) ON DELETE CASCADE, 
	FOREIGN KEY(student_id) REFERENCES student (id) ON DELETE CASCADE
);
CREATE TABLE mcq_question (
	id INTEGER NOT NULL, 
	exam_id INTEGER NOT NULL, 
	question_number INTEGER NOT NULL, 
	question_text TEXT NOT NULL, 
	option_a VARCHAR(500) NOT NULL, 
	option_b VARCHAR(500) NOT NULL, 
	option_c VARCHAR(500) NOT NULL, 
	option_d VARCHAR(500) NOT NULL, 
	correct_option VARCHAR(1) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(exam_id) REFERENCES exam (id) ON DELETE CASCADE
);
CREATE TABLE payroll_record (
	id INTEGER NOT NULL, 
	tutor_id INTEGER NOT NULL, 
	month INTEGER NOT NULL, 
	year INTEGER NOT NULL, 
	base_amount FLOAT, 
	commission_amount FLOAT, 
	bonus_amount FLOAT, 
	tds_amount FLOAT, 
	other_deductions FLOAT, 
	net_amount FLOAT, 
	status VARCHAR(20), 
	expense_id INTEGER, 
	paid_date DATE, 
	notes TEXT, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_payroll_tutor_period UNIQUE (tutor_id, month, year), 
	FOREIGN KEY(tutor_id) REFERENCES tutor (id) ON DELETE CASCADE, 
	FOREIGN KEY(expense_id) REFERENCES expense (id)
);
CREATE TABLE student (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	email VARCHAR(100) NOT NULL, 
	phone VARCHAR(20) NOT NULL, 
	enrollment_date DATE, 
	status VARCHAR(20), 
	qr_code_uuid VARCHAR(36), 
	PRIMARY KEY (id), 
	UNIQUE (email), 
	UNIQUE (qr_code_uuid)
);
INSERT INTO "student" VALUES(1,'J.P. Pranavi','pranavi@gmail.com','9941032524','2026-07-06','Active','298f0b1f-3cdf-4ea3-98a1-c452f7f1a544');
INSERT INTO "student" VALUES(2,'Sai narbhavi','sai@gmail.com','9486206825','2026-06-26','Active','9e9e0e20-89a1-464b-ad67-69cb5b443c35');
INSERT INTO "student" VALUES(3,'KAVIN','kavin@gmail.com','9626635343','2026-06-26','Active','655f6b7d-be45-41a8-a880-c781e85e5d28');
INSERT INTO "student" VALUES(4,'JANANI','janani@gmail.com','8220886754','2026-06-26','Active','71ca9356-e8a7-439f-9737-6c6995987bc9');
INSERT INTO "student" VALUES(5,'Lithya Sree','lithya@gmail.com','8946033863','2026-06-26','Active','b2b98dea-92ea-485a-b958-9aef4f1d0d07');
INSERT INTO "student" VALUES(6,'Riya','riya@gmail.com','9500586671','2026-06-26','Active','40761fb1-375e-459b-91b9-4a0c59648cb4');
INSERT INTO "student" VALUES(7,'Janath','janath@gmail.com','9952533545','2026-06-26','Active','a53917e2-82bf-45a2-a47a-2483acf915e9');
INSERT INTO "student" VALUES(8,'Ishaani darji','ishaani@gmail.com','7675024978','2026-06-26','Active','bf873200-0cad-4b70-af54-ebb9bbd05a26');
INSERT INTO "student" VALUES(9,'Arikaran ','ari@gmail.com','8925467106','2026-06-26','Active','6ccbb050-8c4b-492e-9b8c-5a5511154130');
INSERT INTO "student" VALUES(10,'Manimegalai','megalai@gmail.comm','8668176177','2026-06-26','Active','116864b4-1339-44bb-9b74-db9df07e742f');
INSERT INTO "student" VALUES(11,'Sachin','sachin@gmail.com','6379692471','2026-06-26','Active','b50893d0-597f-4e26-bfbc-a7f932a67f45');
INSERT INTO "student" VALUES(12,'Harini','harini@gmail.com','9894450684','2026-06-26','Active','f8637ec2-1e89-4af4-ad45-a7234c76b74b');
INSERT INTO "student" VALUES(13,'Naresh','naresh@gmail.com','9843752402','2026-06-26','Active','4d195a0d-186f-40ca-8185-8f437befd7a1');
INSERT INTO "student" VALUES(14,'Roshna','roshna@gmail.com','9843752402','2026-06-26','Active','e062222b-028e-4f15-b945-98e52ab1347c');
INSERT INTO "student" VALUES(15,'Humshitha','humshitha@gmail.com','8907494039','2026-06-26','Active','8134e2b4-e2e4-4fe3-a079-5b9628ee2d3f');
INSERT INTO "student" VALUES(16,'Afreeth Ahamed','afreeth@gmail.com','9867543210','2026-06-26','Active','c3c6d27e-5f85-480b-9fc2-43a4b43976a6');
INSERT INTO "student" VALUES(17,'Rakshan','rakshan@gmail.com','7890123454','2026-06-26','Active','b53e023c-8646-423c-8e2d-62e45f60e125');
INSERT INTO "student" VALUES(18,'Vinmathi','vinmathi@gmail.com','9878906782','2026-06-26','Active','5ec2074a-06de-44cc-a7ff-8c619f7b01ba');
INSERT INTO "student" VALUES(19,'Vikrant','vikrant@gmail.com','9655190879','2026-06-26','Active','3bdb7280-2dae-4368-bcbe-31a1b4a4a231');
INSERT INTO "student" VALUES(20,'Lithvika','lithvika@gmail.com','9884978979','2026-06-26','Active','7fa8ad68-1595-47a1-a71a-466ea25a2e00');
INSERT INTO "student" VALUES(21,'Kaaruvagi','kaaruvagi@gmail.com','9597285215','2026-06-26','Active','0eda6baf-45f6-4e02-9d08-4aae5dc1b5ee');
INSERT INTO "student" VALUES(23,'TestStudent','test@test.com','9876543210','2026-07-05','Active','0b32f7b7-0efc-4391-96a3-6821b1b530a5');
CREATE TABLE student_courses (
	student_id INTEGER NOT NULL, 
	course_id INTEGER NOT NULL, 
	PRIMARY KEY (student_id, course_id), 
	FOREIGN KEY(student_id) REFERENCES student (id) ON DELETE CASCADE, 
	FOREIGN KEY(course_id) REFERENCES course (id) ON DELETE CASCADE
);
INSERT INTO "student_courses" VALUES(2,5);
INSERT INTO "student_courses" VALUES(3,5);
INSERT INTO "student_courses" VALUES(4,5);
INSERT INTO "student_courses" VALUES(5,5);
INSERT INTO "student_courses" VALUES(6,5);
INSERT INTO "student_courses" VALUES(7,5);
INSERT INTO "student_courses" VALUES(9,6);
INSERT INTO "student_courses" VALUES(11,6);
INSERT INTO "student_courses" VALUES(12,6);
INSERT INTO "student_courses" VALUES(13,7);
INSERT INTO "student_courses" VALUES(14,7);
INSERT INTO "student_courses" VALUES(15,7);
INSERT INTO "student_courses" VALUES(16,7);
INSERT INTO "student_courses" VALUES(17,7);
INSERT INTO "student_courses" VALUES(18,7);
INSERT INTO "student_courses" VALUES(19,8);
INSERT INTO "student_courses" VALUES(20,8);
INSERT INTO "student_courses" VALUES(21,8);
INSERT INTO "student_courses" VALUES(8,5);
INSERT INTO "student_courses" VALUES(8,8);
INSERT INTO "student_courses" VALUES(1,8);
INSERT INTO "student_courses" VALUES(1,5);
INSERT INTO "student_courses" VALUES(10,6);
CREATE TABLE system_setting (
	id INTEGER NOT NULL, 
	"key" VARCHAR(50) NOT NULL, 
	value TEXT, 
	PRIMARY KEY (id), 
	UNIQUE ("key")
);
CREATE TABLE tutor (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	email VARCHAR(100) NOT NULL, 
	phone VARCHAR(20) NOT NULL, 
	specialization VARCHAR(100), 
	status VARCHAR(20), 
	qr_code_uuid VARCHAR(36), 
	PRIMARY KEY (id), 
	UNIQUE (email), 
	UNIQUE (qr_code_uuid)
);
INSERT INTO "tutor" VALUES(1,'ISHWARYA KUMAR','ishwaryakumar417@gmail.com','9344550103','Tamil','Active','efc8c66e-2d83-4bc5-b9fb-18069562ffa7');
INSERT INTO "tutor" VALUES(2,'UMA MAHESHWARI','uma@gmail.com','9876501234','English','Active','e64d3fa5-d724-46db-84d4-8529a0a9ca08');
INSERT INTO "tutor" VALUES(3,'SUDHARSHAN','sudharshan@gmail.com','9677401203','Computer Science (Python)','Active','18e477e7-d30b-4130-846b-3987bd296bd0');
INSERT INTO "tutor" VALUES(4,'VELMURUGAN','veklmurugan@gmail.com','9626989067','Full Stack Web','Active','541d233f-037b-4aa1-b134-f512e3977e7c');
CREATE TABLE tutor_courses (
	tutor_id INTEGER NOT NULL, 
	course_id INTEGER NOT NULL, 
	PRIMARY KEY (tutor_id, course_id), 
	FOREIGN KEY(tutor_id) REFERENCES tutor (id) ON DELETE CASCADE, 
	FOREIGN KEY(course_id) REFERENCES course (id) ON DELETE CASCADE
);
INSERT INTO "tutor_courses" VALUES(1,5);
INSERT INTO "tutor_courses" VALUES(2,6);
INSERT INTO "tutor_courses" VALUES(3,7);
INSERT INTO "tutor_courses" VALUES(4,8);
CREATE TABLE tutor_payroll_settings (
	id INTEGER NOT NULL, 
	tutor_id INTEGER NOT NULL, 
	base_salary FLOAT, 
	commission_percentage FLOAT, 
	tds_percentage FLOAT, 
	bonus FLOAT, 
	other_deductions FLOAT, 
	bank_name VARCHAR(100), 
	account_number VARCHAR(50), 
	ifsc_code VARCHAR(20), 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (tutor_id), 
	FOREIGN KEY(tutor_id) REFERENCES tutor (id) ON DELETE CASCADE
);
CREATE TABLE user (
	id INTEGER NOT NULL, 
	username VARCHAR(50) NOT NULL, 
	password_hash VARCHAR(200) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	email VARCHAR(100), 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (username)
);
INSERT INTO "user" VALUES(1,'admin','scrypt:32768:8:1$My5dpzy5e51D4ev2$3c8c3732bb81234c4d4117d27dd07031101dd65274d896aee4d32e93a1ce5aec535e24f1f638a497405c4ec6da977faa5808e469af6cae2150e674fe7026ac93','Admin','System Administrator','admin@institute.edu','2026-06-22 04:40:17.632646');
INSERT INTO "user" VALUES(2,'staff','scrypt:32768:8:1$Up9vMO1cau0wIyQj$110b005dbd6151d5654872d38c87e1b68753c9f2f4094b86a6ba8b649509634b3933941e425e76f40ea00d87e09379e5b1b63120736e866beada9b6376b57cb3','Staff','Operations Staff','staff@institute.edu','2026-06-22 04:40:17.632653');
INSERT INTO "user" VALUES(3,'guhauser','scrypt:32768:8:1$fnFmvnu89OQro5My$67970666c71bf007bee5330fc565934816503b2401003b9f261c77cc54b65b58a0b0830849db1333ffea42c5c560079e095074d82e1abc6d9c3a75d2b68cb678','Staff','guhauser','admin@library.com','2026-06-22 06:17:32.361219');
CREATE INDEX idx_expense_date ON expense(expense_date);
CREATE INDEX idx_expense_category ON expense(category_id);
CREATE INDEX idx_fee_date ON fee_record(payment_date);
CREATE INDEX idx_fee_student ON fee_record(student_id);
CREATE INDEX idx_attendance_person_date ON attendance(person_type, person_id, date);
CREATE INDEX idx_attendance_date ON attendance(date);
CREATE INDEX idx_enquiry_status ON enquiry(status);
CREATE INDEX idx_enquiry_course ON enquiry(course_id);
CREATE INDEX idx_leave_user_status ON leave_request(user_id, status);
CREATE INDEX idx_leave_status ON leave_request(status);
CREATE INDEX idx_payroll_period ON payroll_record (month, year);
CREATE INDEX idx_payroll_status ON payroll_record (status);
CREATE INDEX idx_examscore_exam ON exam_score (exam_id);
CREATE INDEX idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id);
COMMIT;
