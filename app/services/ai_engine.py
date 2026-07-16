import os
import json
import random
import requests

class AIEngine:
    def __init__(self):
        pass
        
    def _get_api_key(self, name):
        from app.models import SystemSetting
        try:
            setting = SystemSetting.query.filter_by(key=name).first()
            if setting and setting.value:
                return setting.value
        except Exception as e:
            print(f"Error loading {name}: {e}")
        return os.environ.get(name)

    def _call_gemini(self, prompt):
        key = self._get_api_key("GEMINI_API_KEY")
        if not key:
            return None
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}"
            headers = {"Content-Type": "application/json"}
            data = {"contents": [{"parts": [{"text": prompt}]}]}
            response = requests.post(url, headers=headers, json=data, timeout=5)
            if response.status_code == 200:
                result = response.json()
                return result['candidates'][0]['content']['parts'][0]['text']
        except Exception as e:
            print(f"Gemini API Error: {e}")
        return None

    def _call_openai(self, prompt):
        key = self._get_api_key("OPENAI_API_KEY")
        if not key:
            return None
        try:
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}"
            }
            data = {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7
            }
            response = requests.post(url, headers=headers, json=data, timeout=5)
            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content']
        except Exception as e:
            print(f"OpenAI API Error: {e}")
        return None

    def generate_enquiry_followup(self, student_name, course_name, source, notes):
        prompt = (
            f"You are the Lead Admissions Counselor at a premium computer institute.\n"
            f"Write a highly professional, welcoming, and persuasive follow-up email/message draft for a prospective student.\n"
            f"Prospective Student Name: {student_name}\n"
            f"Interested Course: {course_name}\n"
            f"Enquiry Source: {source}\n"
            f"Enquiry Notes/Background: {notes}\n"
            f"Make the tone warm and inspiring. Highlight that the institute offers hands-on projects, industry-expert tutors, and career support. "
            f"Encourage them to book a free demo session this week. Keep it under 250 words and include placeholders for contact info."
        )
        ai_response = self._call_gemini(prompt) or self._call_openai(prompt)
        if ai_response:
            return ai_response.strip()
        subjects_highlights = {
            "python": "hands-on Python programming, syntax mastery, data structures, and automation scripts.",
            "web": "HTML5, CSS3, modern Bootstrap styling, JavaScript interactivity, and full responsive web page creations.",
            "database": "relational database designs, SQLite, complex SQL queries, and optimizing indexes.",
            "data science": "data visualization, statistical analysis, Python Pandas, NumPy, and basic machine learning workflows.",
            "default": "practical programming paradigms, industry-aligned syllabus projects, and live mentor coding sessions."
        }
        lower_course = course_name.lower()
        highlight = subjects_highlights["default"]
        for key, val in subjects_highlights.items():
            if key in lower_course:
                highlight = val
                break
        greeting = f"Dear {student_name},"
        body = (
            f"Thank you for reaching out to us regarding your interest in our **{course_name}** program! "
            f"We noticed you discovered us via {source}. It's wonderful to connect with you.\n\n"
            f"Our {course_name} course is specifically structured to take you from a beginner level to industry readiness. "
            f"In this program, you will work on deep, hands-on assignments covering {highlight} "
            f"All our batches are led by senior industry developers who guide you step-by-step through a robust curriculum.\n\n"
            f"Based on your interest in our course, we would love to invite you for an exclusive **Free Interactive Demo Session & Campus Tour**. "
            f"This will give you a chance to see our labs, review the syllabus in detail, and chat with our senior tutors.\n\n"
            f"Would you be available for a quick 15-minute call or campus visit this week? "
            f"Please let us know your preferred time so we can reserve a slot for you."
        )
        signoff = (
            f"Best regards,\n\n"
            f"Admissions & Career Advisory Team\n"
            f"Premium Computer Institute"
        )
        return f"{greeting}\n\n{body}\n\n{signoff}"

    def generate_institute_insights(self, stats):
        prompt = (
            f"Analyze the following computer institute dashboard metrics and generate 3 actionable, premium business insights. "
            f"Return the response in a clean JSON format with keys: 'summary' (a brief overview paragraph of institute health) "
            f"and 'insights' (an array of 3 distinct, comprehensive recommendations with 'title', 'description', and 'badge' as 'High', 'Medium', or 'Info').\n"
            f"Metrics:\n"
            f"- Total Active Students: {stats['active_students']}\n"
            f"- Total Tutors: {stats['tutors']}\n"
            f"- Total Active Courses: {stats['courses']}\n"
            f"- Total Enquiries: {stats['enquiries']} (New: {stats['enquiries_new']}, Contacted: {stats['enquiries_contacted']}, Converted: {stats['enquiries_converted']})\n"
            f"- Average Student Attendance: {stats['avg_student_attendance']}%\n"
            f"- Total Collections This Month: ₹{stats['monthly_fees_collected']}\n"
            f"- Unresolved Enquiries: {stats['unresolved_enquiries']}\n"
            f"- Low Attendance Students (<75%): {stats['low_attendance_count']}\n"
        )
        ai_response = self._call_gemini(prompt) or self._call_openai(prompt)
        if ai_response:
            try:
                cleaned = ai_response.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                parsed = json.loads(cleaned.strip())
                if 'summary' in parsed and 'insights' in parsed:
                    return parsed
            except Exception as e:
                print(f"Error parsing AI Insight JSON: {e}. Raw response: {ai_response}")
        low_att_alert = ""
        low_att_desc = "All student attendances are healthy above 75%!"
        low_att_badge = "Info"
        if stats['low_attendance_count'] > 0:
            low_att_alert = f"Address Attendance Slippage for {stats['low_attendance_count']} Students"
            low_att_desc = f"We have identified {stats['low_attendance_count']} student(s) with attendance falling below the 75% threshold."
            low_att_badge = "High"
        else:
            low_att_alert = "Maintain High Engagement Rates"
            low_att_desc = "Student attendance is averaging a robust level!"
            low_att_badge = "Info"
        conversion_rate = 0
        if stats['enquiries'] > 0:
            conversion_rate = int((stats['enquiries_converted'] / stats['enquiries']) * 100)
        enquiry_insight = "Optimize Enquiry Conversion Pipeline"
        if conversion_rate < 30:
            enq_desc = f"Your enquiry-to-enrollment conversion rate is currently around {conversion_rate}%. There are {stats['unresolved_enquiries']} unresolved/new enquiries."
            enq_badge = "High"
        else:
            enq_desc = f"Excellent conversions! You are converting {conversion_rate}% of prospective leads."
            enq_badge = "Medium"
        revenue_insight = "Scale Course Batch Schedules"
        if stats['active_students'] > 15:
            rev_desc = f"With {stats['active_students']} active students and collections at ₹{stats['monthly_fees_collected']}, your capacity is building."
            rev_badge = "Medium"
        else:
            rev_desc = "Drive Enrollment Campaigns."
            rev_badge = "High"
        return {
            "summary": (
                f"The institute is operating steadily with {stats['active_students']} active student(s) and {stats['tutors']} tutor(s) "
                f"across {stats['courses']} core programs. The current average student attendance stands at {stats['avg_student_attendance']}%. "
                f"Enquiry pipelines show {stats['unresolved_enquiries']} active leads awaiting follow-ups. Financial collections reached "
                f"₹{stats['monthly_fees_collected']} this month."
            ),
            "insights": [
                {"title": low_att_alert, "description": low_att_desc, "badge": low_att_badge},
                {"title": enquiry_insight, "description": enq_desc, "badge": enq_badge},
                {"title": revenue_insight, "description": rev_desc, "badge": rev_badge}
            ]
        }

    def validate_student_data(self, students_data):
        if not students_data:
            return {"valid": False, "errors": ["No data provided"], "enriched_data": []}
        data_summary = f"Validating {len(students_data)} student records.\n"
        for idx, student in enumerate(students_data[:5]):
            data_summary += f"Record {idx+1}: Name={student.get('name', '')}, Email={student.get('email', '')}, Phone={student.get('phone', '')}\n"
        prompt = (
            f"You are a data validation assistant for an educational institute.\n"
            f"Analyze the following student data and identify:\n"
            f"1. Invalid email addresses\n"
            f"2. Missing required fields (name, email, phone)\n"
            f"3. Duplicate entries\n"
            f"4. Phone number format issues\n"
            f"5. Any data quality issues\n\n"
            f"{data_summary}\n\n"
            f"Return a JSON response with keys:\n"
            f"- 'valid': boolean (true if all records are valid)\n"
            f"- 'errors': array of error messages\n"
            f"- 'warnings': array of warning messages\n"
            f"- 'suggestions': array of suggestions for data improvement\n"
        )
        ai_response = self._call_gemini(prompt) or self._call_openai(prompt)
        if ai_response:
            try:
                cleaned = ai_response.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                parsed = json.loads(cleaned.strip())
                parsed["enriched_data"] = students_data
                return parsed
            except Exception as e:
                print(f"Error parsing AI validation JSON: {e}")
        errors = []
        warnings = []
        enriched_data = []
        seen_emails = set()
        for idx, student in enumerate(students_data):
            if not student.get('name') or not student.get('name').strip():
                errors.append(f"Record {idx+1}: Missing name")
            if not student.get('email') or not student.get('email').strip():
                errors.append(f"Record {idx+1}: Missing email")
            elif '@' not in student.get('email', ''):
                errors.append(f"Record {idx+1}: Invalid email format")
            elif student.get('email') in seen_emails:
                errors.append(f"Record {idx+1}: Duplicate email")
            else:
                seen_emails.add(student.get('email'))
            if not student.get('phone') or not student.get('phone').strip():
                warnings.append(f"Record {idx+1}: Missing phone number")
            enriched_student = student.copy()
            if not enriched_student.get('status'):
                enriched_student['status'] = 'Active'
            enriched_data.append(enriched_student)
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "suggestions": ["Ensure all emails are unique", "Use standard phone number format"],
            "enriched_data": enriched_data
        }

    def validate_tutor_data(self, tutors_data):
        if not tutors_data:
            return {"valid": False, "errors": ["No data provided"], "enriched_data": []}
        data_summary = f"Validating {len(tutors_data)} tutor records.\n"
        for idx, tutor in enumerate(tutors_data[:5]):
            data_summary += f"Record {idx+1}: Name={tutor.get('name', '')}, Email={tutor.get('email', '')}, Phone={tutor.get('phone', '')}, Specialization={tutor.get('specialization', '')}\n"
        prompt = (
            f"You are a data validation assistant for an educational institute.\n"
            f"Analyze the following tutor data and identify:\n"
            f"1. Invalid email addresses\n"
            f"2. Missing required fields (name, email, phone)\n"
            f"3. Duplicate entries\n"
            f"4. Phone number format issues\n"
            f"5. Any data quality issues\n\n"
            f"{data_summary}\n\n"
            f"Return a JSON response with keys:\n"
            f"- 'valid': boolean (true if all records are valid)\n"
            f"- 'errors': array of error messages\n"
            f"- 'warnings': array of warning messages\n"
            f"- 'suggestions': array of suggestions for data improvement\n"
        )
        ai_response = self._call_gemini(prompt) or self._call_openai(prompt)
        if ai_response:
            try:
                cleaned = ai_response.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                parsed = json.loads(cleaned.strip())
                parsed["enriched_data"] = tutors_data
                return parsed
            except Exception as e:
                print(f"Error parsing AI validation JSON: {e}")
        errors = []
        warnings = []
        enriched_data = []
        seen_emails = set()
        for idx, tutor in enumerate(tutors_data):
            if not tutor.get('name') or not tutor.get('name').strip():
                errors.append(f"Record {idx+1}: Missing name")
            if not tutor.get('email') or not tutor.get('email').strip():
                errors.append(f"Record {idx+1}: Missing email")
            elif '@' not in tutor.get('email', ''):
                errors.append(f"Record {idx+1}: Invalid email format")
            elif tutor.get('email') in seen_emails:
                errors.append(f"Record {idx+1}: Duplicate email")
            else:
                seen_emails.add(tutor.get('email'))
            if not tutor.get('phone') or not tutor.get('phone').strip():
                warnings.append(f"Record {idx+1}: Missing phone number")
            if not tutor.get('specialization') or not tutor.get('specialization').strip():
                warnings.append(f"Record {idx+1}: Missing specialization (recommended)")
            enriched_tutor = tutor.copy()
            if not enriched_tutor.get('status'):
                enriched_tutor['status'] = 'Active'
            enriched_data.append(enriched_tutor)
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "suggestions": ["Ensure all emails are unique", "Add specialization for better course assignment"],
            "enriched_data": enriched_data
        }

    def suggest_course_mapping(self, person_data, available_courses):
        if not available_courses:
            return []
        course_list = "\n".join([f"- {c.code}: {c.name}" for c in available_courses])
        prompt = (
            f"You are an academic advisor at a computer institute.\n"
            f"Based on the following person profile, suggest which courses they should be enrolled in.\n"
            f"Person: {person_data.get('name', '')}\n"
            f"Specialization: {person_data.get('specialization', 'Not specified')}\n"
            f"Available Courses:\n{course_list}\n\n"
            f"Return a JSON response with key 'suggested_courses' containing an array of course codes "
            f"that would be most relevant for this person. Suggest 2-3 courses maximum."
        )
        ai_response = self._call_gemini(prompt) or self._call_openai(prompt)
        if ai_response:
            try:
                cleaned = ai_response.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                parsed = json.loads(cleaned.strip())
                if 'suggested_courses' in parsed:
                    suggested_ids = []
                    for course in available_courses:
                        if course.code in parsed['suggested_courses']:
                            suggested_ids.append(course.id)
                    return suggested_ids
            except Exception as e:
                print(f"Error parsing AI course suggestion JSON: {e}")
        return [c.id for c in available_courses[:2]]

    def generate_predictive_analytics(self, stats):
        prompt = (
            f"You are a business intelligence analyst for a computer institute.\n"
            f"Analyze the following current metrics and generate predictive insights:\n"
            f"- Active Students: {stats['active_students']}\n"
            f"- Total Tutors: {stats['tutors']}\n"
            f"- Active Courses: {stats['courses']}\n"
            f"- Total Enquiries: {stats['enquiries']} (New: {stats['enquiries_new']}, Contacted: {stats['enquiries_contacted']}, Converted: {stats['enquiries_converted']})\n"
            f"- Average Student Attendance: {stats['avg_student_attendance']}%\n"
            f"- Monthly Fees Collected: ₹{stats['monthly_fees_collected']}\n"
            f"- Unresolved Enquiries: {stats['unresolved_enquiries']}\n"
            f"- Low Attendance Students: {stats['low_attendance_count']}\n\n"
            f"Generate a JSON response with the following keys:\n"
            f"- 'enrollment_forecast': Predicted student enrollment for next 3 months (array of 3 numbers)\n"
            f"- 'revenue_forecast': Predicted revenue for next 3 months (array of 3 numbers)\n"
            f"- 'growth_rate': Expected monthly growth rate percentage\n"
            f"- 'risk_factors': Array of potential risks to monitor\n"
            f"- 'opportunities': Array of growth opportunities\n"
            f"- 'course_recommendations': Array of recommended course actions\n"
        )
        ai_response = self._call_gemini(prompt) or self._call_openai(prompt)
        if ai_response:
            try:
                cleaned = ai_response.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                parsed = json.loads(cleaned.strip())
                return parsed
            except Exception as e:
                print(f"Error parsing AI predictive analytics JSON: {e}")
        current_students = stats['active_students']
        current_revenue = stats['monthly_fees_collected']
        conversion_rate = stats['enquiries_converted'] / stats['enquiries'] if stats['enquiries'] > 0 else 0.3
        growth_factor = 1.05 if conversion_rate > 0.3 else 1.02
        enrollment_forecast = [
            int(current_students * growth_factor),
            int(current_students * growth_factor * 1.03),
            int(current_students * growth_factor * 1.05)
        ]
        revenue_forecast = [
            float(current_revenue * growth_factor),
            float(current_revenue * growth_factor * 1.03),
            float(current_revenue * growth_factor * 1.05)
        ]
        risk_factors = []
        if stats['avg_student_attendance'] < 80:
            risk_factors.append("Declining attendance may impact course completion rates")
        if stats['unresolved_enquiries'] > 10:
            risk_factors.append("High enquiry backlog may lead to lost conversions")
        if stats['low_attendance_count'] > stats['active_students'] * 0.2:
            risk_factors.append("Significant number of at-risk students with poor attendance")
        opportunities = []
        if stats['enquiries_new'] > stats['enquiries_converted']:
            opportunities.append("High enquiry volume presents conversion opportunity")
        if stats['monthly_fees_collected'] > 0:
            opportunities.append("Strong cash flow enables course expansion")
        if stats['tutors'] < stats['courses']:
            opportunities.append("Opportunity to hire specialized tutors for new courses")
        return {
            "enrollment_forecast": enrollment_forecast,
            "revenue_forecast": revenue_forecast,
            "growth_rate": round((growth_factor - 1) * 100, 1),
            "risk_factors": risk_factors or ["No significant risks identified"],
            "opportunities": opportunities or ["Focus on marketing to drive growth"],
            "course_recommendations": ["Analyze course completion rates", "Review curriculum relevance", "Consider adding industry-demand courses"]
        }

    def analyze_fee_collection_patterns(self, fee_records, student_balances):
        if not fee_records:
            return {"collection_efficiency": 0, "average_payment_time": 0, "default_risk_students": [], "recommendations": ["Start tracking fee payments for insights"]}
        total_expected = sum(b['total_fee'] for b in student_balances)
        total_collected = sum(b['total_paid'] for b in student_balances)
        collection_efficiency = (total_collected / total_expected * 100) if total_expected > 0 else 0
        default_risk_students = []
        for balance in student_balances:
            if balance['balance'] > 0 and balance['total_fee'] > 0:
                default_ratio = balance['balance'] / balance['total_fee']
                if default_ratio > 0.5:
                    default_risk_students.append({
                        "student": balance['student'].name,
                        "pending_amount": balance['balance'],
                        "risk_level": "High" if default_ratio > 0.7 else "Medium"
                    })
        prompt = (
            f"You are a financial analyst for an educational institute.\n"
            f"Analyze the following fee collection data:\n"
            f"- Collection Efficiency: {collection_efficiency:.1f}%\n"
            f"- Total Expected: ₹{total_expected:,.2f}\n"
            f"- Total Collected: ₹{total_collected:,.2f}\n"
            f"- Students at Default Risk: {len(default_risk_students)}\n\n"
            f"Generate a JSON response with:\n"
            f"- 'collection_health_score': 1-100 score\n"
            f"- 'payment_method_insights': Analysis of payment methods\n"
            f"- 'recommendations': Array of actionable recommendations\n"
            f"- 'forecast': Predicted collections for next month\n"
        )
        ai_response = self._call_gemini(prompt) or self._call_openai(prompt)
        if ai_response:
            try:
                cleaned = ai_response.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                parsed = json.loads(cleaned.strip())
                parsed['default_risk_students'] = default_risk_students
                return parsed
            except Exception as e:
                print(f"Error parsing AI fee analysis JSON: {e}")
        collection_health_score = min(100, max(0, collection_efficiency))
        recommendations = []
        if collection_efficiency < 70:
            recommendations.append("Implement automated payment reminders")
            recommendations.append("Offer early payment discounts")
        if len(default_risk_students) > 5:
            recommendations.append("Prioritize follow-up with high-risk students")
            recommendations.append("Consider flexible payment plans")
        if collection_efficiency > 90:
            recommendations.append("Maintain current collection practices")
            recommendations.append("Consider premium course packages")
        return {
            "collection_health_score": collection_health_score,
            "payment_method_insights": "Analyze payment method distribution for optimization",
            "recommendations": recommendations or ["Continue monitoring collection patterns"],
            "forecast": total_collected * 1.05,
            "default_risk_students": default_risk_students
        }

    def analyze_attendance_patterns(self, attendance_data):
        if not attendance_data:
            return {"overall_attendance_rate": 0, "at_risk_students": [], "patterns": [], "interventions": ["Start tracking attendance for insights"]}
        present_count = sum(1 for a in attendance_data if a.status == 'Present')
        overall_rate = (present_count / len(attendance_data) * 100) if attendance_data else 0
        prompt = (
            f"You are an academic advisor analyzing student attendance patterns.\n"
            f"Overall Attendance Rate: {overall_rate:.1f}%\n"
            f"Total Records: {len(attendance_data)}\n\n"
            f"Generate a JSON response with:\n"
            f"- 'attendance_trend': 'improving', 'declining', or 'stable'\n"
            f"- 'risk_students': Number of students needing intervention\n"
            f"- 'patterns': Array of observed attendance patterns\n"
            f"- 'interventions': Array of specific intervention strategies\n"
            f"- 'schedule_recommendations': Suggestions for schedule optimization\n"
        )
        ai_response = self._call_gemini(prompt) or self._call_openai(prompt)
        if ai_response:
            try:
                cleaned = ai_response.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                parsed = json.loads(cleaned.strip())
                parsed['overall_attendance_rate'] = overall_rate
                return parsed
            except Exception as e:
                print(f"Error parsing AI attendance analysis JSON: {e}")
        trend = "stable" if 75 <= overall_rate <= 85 else ("improving" if overall_rate > 85 else "declining")
        interventions = []
        if overall_rate < 75:
            interventions.append("Send attendance reminder notifications")
            interventions.append("Schedule individual counseling sessions")
            interventions.append("Review course difficulty and pacing")
        elif overall_rate > 90:
            interventions.append("Recognize and reward high attendance")
            interventions.append("Use successful students as mentors")
        else:
            interventions.append("Maintain current engagement strategies")
            interventions.append("Monitor for early warning signs")
        return {
            "overall_attendance_rate": overall_rate,
            "attendance_trend": trend,
            "risk_students": max(0, int(len(attendance_data) * 0.1)) if overall_rate < 75 else 0,
            "patterns": ["Regular attendance tracking needed"],
            "interventions": interventions,
            "schedule_recommendations": ["Analyze peak attendance times for optimal scheduling"]
        }

    def optimize_course_syllabus(self, course_data, student_feedback=None):
        prompt = (
            f"You are a curriculum development expert for a computer institute.\n"
            f"Course: {course_data.get('name', 'Unknown')}\n"
            f"Current Syllabus: {course_data.get('syllabus', 'Not provided')}\n"
            f"Duration: {course_data.get('duration_weeks', 0)} {course_data.get('duration_unit', 'weeks')}\n"
            f"Fees: ₹{course_data.get('fees', 0)}\n\n"
            f"Generate a JSON response with:\n"
            f"- 'syllabus_gaps': Array of topics that should be added\n"
            f"- 'outdated_content': Array of topics to remove or update\n"
            f"- 'structure_recommendations': Suggestions for better organization\n"
            f"- 'industry_alignment': How well the course aligns with current industry demands\n"
            f"- 'difficulty_adjustment': Suggestions for difficulty level tuning\n"
        )
        ai_response = self._call_gemini(prompt) or self._call_openai(prompt)
        if ai_response:
            try:
                cleaned = ai_response.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                parsed = json.loads(cleaned.strip())
                return parsed
            except Exception as e:
                print(f"Error parsing AI syllabus optimization JSON: {e}")
        return {
            "syllabus_gaps": ["Add practical project work", "Include industry case studies", "Add current technology trends"],
            "outdated_content": ["Review for outdated programming practices", "Update with latest framework versions"],
            "structure_recommendations": ["Balance theory and practical sessions", "Add milestone assessments", "Include capstone project"],
            "industry_alignment": "Regular review with industry advisors recommended",
            "difficulty_adjustment": "Implement progressive difficulty curve"
        }

    def generate_student_performance_insights(self, student_data, attendance_data, fee_data):
        attendance_rate = 0
        if attendance_data:
            present = sum(1 for a in attendance_data if a.status == 'Present')
            attendance_rate = (present / len(attendance_data) * 100) if attendance_data else 0
        fee_compliance = 0
        if fee_data and student_data.get('total_fee', 0) > 0:
            fee_compliance = (student_data.get('total_paid', 0) / student_data['total_fee'] * 100)
        prompt = (
            f"You are an academic counselor analyzing student performance.\n"
            f"Student: {student_data.get('name', 'Unknown')}\n"
            f"Attendance Rate: {attendance_rate:.1f}%\n"
            f"Fee Compliance: {fee_compliance:.1f}%\n"
            f"Enrolled Courses: {len(student_data.get('courses', []))}\n\n"
            f"Generate a JSON response with:\n"
            f"- 'performance_level': 'excellent', 'good', 'average', or 'at-risk'\n"
            f"- 'strengths': Array of student strengths\n"
            f"- 'areas_for_improvement': Array of areas needing attention\n"
            f"- 'recommendations': Array of personalized recommendations\n"
            f"- 'success_probability': Predicted probability of course completion (0-100)\n"
        )
        ai_response = self._call_gemini(prompt) or self._call_openai(prompt)
        if ai_response:
            try:
                cleaned = ai_response.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                parsed = json.loads(cleaned.strip())
                return parsed
            except Exception as e:
                print(f"Error parsing AI student performance JSON: {e}")
        if attendance_rate >= 90 and fee_compliance >= 90:
            performance_level = "excellent"
            success_probability = 95
        elif attendance_rate >= 75 and fee_compliance >= 75:
            performance_level = "good"
            success_probability = 80
        elif attendance_rate >= 60 and fee_compliance >= 60:
            performance_level = "average"
            success_probability = 65
        else:
            performance_level = "at-risk"
            success_probability = 40
        return {
            "performance_level": performance_level,
            "strengths": ["Regular attendance" if attendance_rate >= 75 else "Needs improvement"],
            "areas_for_improvement": ["Fee compliance" if fee_compliance < 75 else "Maintain current performance"],
            "recommendations": ["Continue regular attendance", "Stay current with fee payments"],
            "success_probability": success_probability
        }

    def generate_expense_optimization_insights(self, expense_data, category_data):
        if not expense_data:
            return {"total_expenses": 0, "optimization_potential": 0, "recommendations": ["Start tracking expenses for insights"]}
        total_expenses = sum(e.amount for e in expense_data)
        category_breakdown = {}
        for expense in expense_data:
            category_name = expense.category.name if expense.category else "Uncategorized"
            category_breakdown[category_name] = category_breakdown.get(category_name, 0) + expense.amount
        prompt = (
            f"You are a financial analyst optimizing institute expenses.\n"
            f"Total Monthly Expenses: ₹{total_expenses:,.2f}\n"
            f"Category Breakdown: {category_breakdown}\n\n"
            f"Generate a JSON response with:\n"
            f"- 'optimization_potential': Estimated monthly savings (₹)\n"
            f"- 'high_cost_categories': Categories with optimization potential\n"
            f"- 'recommendations': Array of specific cost-saving recommendations\n"
            f"- 'budget_alerts': Any categories exceeding reasonable thresholds\n"
        )
        ai_response = self._call_gemini(prompt) or self._call_openai(prompt)
        if ai_response:
            try:
                cleaned = ai_response.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                parsed = json.loads(cleaned.strip())
                parsed['total_expenses'] = total_expenses
                parsed['category_breakdown'] = category_breakdown
                return parsed
            except Exception as e:
                print(f"Error parsing AI expense optimization JSON: {e}")
        optimization_potential = total_expenses * 0.1
        recommendations = []
        if 'Salary' in category_breakdown and category_breakdown['Salary'] > total_expenses * 0.5:
            recommendations.append("Review staff utilization and consider part-time options")
        if 'Rent' in category_breakdown:
            recommendations.append("Evaluate space utilization and consider shared arrangements")
        if 'Marketing' in category_breakdown and category_breakdown['Marketing'] > total_expenses * 0.15:
            recommendations.append("Analyze marketing ROI and focus on high-impact channels")
        return {
            "total_expenses": total_expenses,
            "optimization_potential": optimization_potential,
            "category_breakdown": category_breakdown,
            "high_cost_categories": [cat for cat, amount in category_breakdown.items() if amount > total_expenses * 0.2],
            "recommendations": recommendations or ["Regular expense review recommended"],
            "budget_alerts": []
        }

    def generate_mcq_questions(self, course_name, course_description, num_questions=10, duration_mins=30, total_marks=100):
        prompt = (
            f"You are an exam generator for a computer institute. "
            f"Generate {num_questions} multiple-choice questions for the course '{course_name}'. "
            f"Course description: {course_description or 'General course'}\n\n"
            f"Each question must have exactly 4 options (A, B, C, D) with one correct answer. "
            f"The exam duration is {duration_mins} minutes and total marks is {total_marks}.\n\n"
            f"Respond with ONLY a valid JSON array. No markdown, no code blocks, no extra text. "
            f"Format:\n"
            f'[{{"question": "question text", '
            f'"options": {{"A": "option a", "B": "option b", "C": "option c", "D": "option d"}}, '
            f'"correct": "A"}},...]\n\n'
            f"Make questions relevant to the course. Vary difficulty. "
            f"Each question carries {total_marks / num_questions:.1f} marks."
        )
        raw = self._call_gemini(prompt) or self._call_openai(prompt)
        if not raw:
            return None
        import re, json
        cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip())
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            try:
                start = cleaned.index('[')
                end = cleaned.rindex(']') + 1
                data = json.loads(cleaned[start:end])
            except (ValueError, json.JSONDecodeError):
                return None
        if not isinstance(data, list):
            return None
        marks_per_q = total_marks / num_questions
        result = []
        for i, q in enumerate(data):
            opts = q.get('options', {})
            result.append({
                'question_number': i + 1,
                'question_text': q.get('question', ''),
                'option_a': opts.get('A', ''),
                'option_b': opts.get('B', ''),
                'option_c': opts.get('C', ''),
                'option_d': opts.get('D', ''),
                'correct_option': q.get('correct', 'A').upper(),
            })
        return result

    def generate_todays_tasks(self, data):
        stale = data.get('stale_enquiries', 0)
        fee_due = data.get('fee_due_count', 0)
        low_att = data.get('low_attendance_count', 0)
        pending_leaves = data.get('pending_leaves', 0)
        today_exams = data.get('today_exams', [])
        new_enqs = data.get('new_enquiries_today', 0)
        prompt = (
            f"You are an experienced operations advisor for a computer institute. Generate a concise 'Today's Task List' "
            f"for the counsellor/admin. Prioritize urgent items first. Use a friendly, actionable tone. "
            f"Return the response as a JSON object with a single key 'tasks' containing an array of task objects. "
            f"Each task object must have: 'priority' ('high','medium','low'), 'icon' (Bootstrap icon name without 'bi-' prefix, e.g. 'funnel','currency-rupee','calendar-check','person','journal-text','people'), "
            f"'title' (short actionable sentence), 'detail' (one-liner context), and 'action_label' (button text like 'View Pipeline' or 'Check Now'). "
            f"Keep to max 6 tasks. Here is today's data:\n"
            f"- Stale enquiries needing follow-up (no contact in 3+ days): {stale}\n"
            f"- Students with possible fee due: {fee_due}\n"
            f"- Students with low attendance (<75%): {low_att}\n"
            f"- Pending leave requests: {pending_leaves}\n"
            f"- Exams scheduled today: {', '.join(today_exams) if today_exams else 'None'}\n"
            f"- New enquiries received today: {new_enqs}\n"
            f"Rank high priority for anything involving money, pending approvals, or stale leads. "
            f"Medium for attendance or new enquiries. Low for routine info."
        )
        ai_response = self._call_gemini(prompt) or self._call_openai(prompt)
        if ai_response:
            try:
                cleaned = ai_response.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                parsed = json.loads(cleaned.strip())
                if 'tasks' in parsed:
                    return parsed['tasks']
            except Exception as e:
                print(f"Error parsing AI tasks JSON: {e}")
        tasks = []
        if stale > 0:
            tasks.append({'priority': 'high', 'icon': 'funnel', 'title': f'Follow up on {stale} stale enquiry(ies)', 'detail': 'No contact in 3+ days', 'action_label': 'View Pipeline'})
        if fee_due > 0:
            tasks.append({'priority': 'high', 'icon': 'currency-rupee', 'title': f'Contact {fee_due} student(s) about fee due', 'detail': 'No recent payment recorded', 'action_label': 'View Fees'})
        if pending_leaves > 0:
            tasks.append({'priority': 'high', 'icon': 'calendar-check', 'title': f'Review {pending_leaves} pending leave request(s)', 'detail': 'Awaiting your approval', 'action_label': 'View Leaves'})
        if low_att > 0:
            tasks.append({'priority': 'medium', 'icon': 'person', 'title': f'Check {low_att} student(s) with low attendance', 'detail': 'Below 75% threshold', 'action_label': 'View Attendance'})
        if today_exams:
            tasks.append({'priority': 'medium', 'icon': 'journal-text', 'title': f'Todays exam(s): {", ".join(today_exams)}', 'detail': 'Scheduled for today', 'action_label': 'View Exams'})
        if new_enqs > 0:
            tasks.append({'priority': 'low', 'icon': 'people', 'title': f'{new_enqs} new enquiry(ies) received today', 'detail': 'Log in pipeline', 'action_label': 'View Enquiries'})
        return tasks[:6]

    def chat_query(self, message):
        from datetime import date, timedelta, datetime
        from app.extensions import db
        from app.models import Student, Tutor, Course, Enquiry, FeeRecord, Attendance, LeaveRequest, Exam
        from sqlalchemy import func

        msg_lower = message.lower()

        prompt = (
            f"You are an AI assistant for a computer institute management system. "
            f"The database has tables: Student (name, email, phone, status), "
            f"Tutor (name, email, phone, specialization, status), "
            f"Course (name, code, fees, duration_weeks), "
            f"Enquiry (student_name, email, phone, status, source), "
            f"FeeRecord (student_id, amount_paid, payment_date, payment_method), "
            f"Attendance (person_type, person_id, date, status), "
            f"LeaveRequest (user_id, reason, status, start_date, end_date), "
            f"Exam (title, course_id, exam_date, max_marks).\n\n"
            f"User question: {message}\n\n"
            f"Answer concisely and helpfully. If the question asks for data, "
            f"explain what data would be relevant. Keep it under 3 sentences."
        )
        ai_response = self._call_gemini(prompt) or self._call_openai(prompt)
        if ai_response:
            return ai_response.strip()

        # --- Rule-based fallback ---

        # Help
        if any(w in msg_lower for w in ['help', 'what can you', 'commands', 'what do you']):
            return (
                "I can answer questions about your institute. Try asking:\n"
                "• \"How many students are enrolled?\"\n"
                "• \"Students in Python course\"\n"
                "• \"Fees collected this month\"\n"
                "• \"Who hasn't paid fees?\"\n"
                "• \"Attendance rate\"\n"
                "• \"Low attendance students\"\n"
                "• \"How many courses?\"\n"
                "• \"How many tutors?\"\n"
                "• \"Upcoming exams\"\n"
                "• \"Pending leaves\"\n"
                "• \"Recent enquiries\""
            )

        # Student count
        if any(w in msg_lower for w in ['how many students', 'total students', 'student count', 'number of students']):
            total = Student.query.count()
            active = Student.query.filter_by(status='Active').count()
            return f"There are {total} students total, {active} currently active."

        # Students by course
        if any(w in msg_lower for w in ['students in', 'students enrolled in', 'enrolled in', 'student in']):
            for course in Course.query.all():
                if course.name.lower() in msg_lower or course.code.lower() in msg_lower:
                    count = course.students.count()
                    return f"There are {count} student{'s' if count != 1 else ''} enrolled in {course.name} ({course.code})."
            return "I couldn't identify which course you're asking about. Available courses: " + ", ".join(f"{c.name} ({c.code})" for c in Course.query.all())

        # Fees collected
        if any(w in msg_lower for w in ['fees collected', 'fee collected', 'total fees', 'how much fee', 'collection']):
            today = date.today()
            fmonth = date(today.year, today.month, 1)
            total = db.session.query(func.sum(FeeRecord.amount_paid)).filter(
                FeeRecord.payment_date >= fmonth
            ).scalar() or 0
            return f"Fee collections this month: \u20b9{total:,.2f}."

        # Defaulters
        if any(w in msg_lower for w in ['not paid', 'haven\'t paid', 'hasn\'t paid', 'defaulters', 'outstanding', 'balance', 'due', 'pending fee', 'unpaid']):
            from app.models import student_courses
            students = Student.query.filter_by(status='Active').all()
            defaulters = []
            for s in students:
                paid = db.session.query(func.sum(FeeRecord.amount_paid)).filter_by(student_id=s.id).scalar() or 0
                course_fees = db.session.query(func.sum(Course.fees)).join(
                    student_courses, Course.id == student_courses.c.course_id
                ).filter(student_courses.c.student_id == s.id).scalar() or 0
                if paid < course_fees:
                    defaulters.append(f"{s.name} (\u20b9{course_fees - paid:,.0f} due)")
            if defaulters:
                return f"Students with outstanding fees: {'; '.join(defaulters[:10])}."
            return "All active students are up-to-date on fees."

        # Today's attendance
        if any(w in msg_lower for w in ['today attendance', 'attendance today', 'who is present', 'who came today']):
            today = date.today()
            records = Attendance.query.filter_by(date=today, person_type='student').all()
            present = [r for r in records if r.status == 'Present']
            absent = [r for r in records if r.status == 'Absent']
            if records:
                return f"Today's attendance: {len(present)} present, {len(absent)} absent out of {len(records)} students."
            return "No attendance has been marked for today yet."

        # Attendance rate
        if any(w in msg_lower for w in ['attendance rate', 'attendance percentage', 'overall attendance', 'average attendance', 'what is attendance']):
            fourteen_days_ago = date.today() - timedelta(days=14)
            total = Attendance.query.filter(
                Attendance.date >= fourteen_days_ago, Attendance.person_type == 'student'
            ).count()
            present = Attendance.query.filter(
                Attendance.date >= fourteen_days_ago, Attendance.person_type == 'student',
                Attendance.status == 'Present'
            ).count()
            rate = int(present / total * 100) if total > 0 else 0
            return f"Overall student attendance over the last 14 days is {rate}% ({present} present out of {total} records)."

        # Low attendance
        if any(w in msg_lower for w in ['low attendance', 'poor attendance', 'at risk', 'below']):
            students = Student.query.filter_by(status='Active').all()
            low = []
            for s in students:
                total = Attendance.query.filter_by(person_type='student', person_id=s.id).count()
                if total >= 3:
                    present = Attendance.query.filter_by(person_type='student', person_id=s.id, status='Present').count()
                    pct = present * 100 / total
                    if pct < 75:
                        low.append(f"{s.name} ({pct:.0f}%)")
            if low:
                return f"Students with low attendance (<75%): {'; '.join(low[:10])}."
            return "No students are below the 75% attendance threshold."

        # Course count
        if any(w in msg_lower for w in ['how many courses', 'total courses', 'number of courses', 'course count']):
            count = Course.query.count()
            return f"There are {count} course{'s' if count != 1 else ''} in the curriculum."

        # Tutor count
        if any(w in msg_lower for w in ['how many tutors', 'total tutors', 'number of tutors', 'tutor count', 'how many staff', 'total staff']):
            total = Tutor.query.count()
            active = Tutor.query.filter_by(status='Active').count()
            return f"There are {total} tutors total, {active} currently active."

        # Upcoming exams
        if any(w in msg_lower for w in ['upcoming exam', 'next exam', 'exam schedule', 'when is exam', 'upcoming test']):
            today = date.today()
            exams = Exam.query.filter(Exam.exam_date >= today).order_by(Exam.exam_date).limit(5).all()
            if exams:
                lines = [f"{e.title} on {e.exam_date.strftime('%d %b %Y')}" for e in exams]
                return "Upcoming exams:\n" + "\n".join(lines)
            return "No upcoming exams scheduled."

        # Pending leaves
        if any(w in msg_lower for w in ['pending leave', 'leave pending', 'pending request', 'leave request']):
            count = LeaveRequest.query.filter_by(status='Pending').count()
            return f"There {'is' if count == 1 else 'are'} {count} pending leave request{'s' if count != 1 else ''}."

        # Recent enquiries
        if any(w in msg_lower for w in ['recent enquiry', 'recent enquiries', 'new enquiry', 'new enquiries', 'recent lead', 'latest enquiry', 'latest enquiries']):
            enqs = Enquiry.query.order_by(Enquiry.id.desc()).limit(5).all()
            if enqs:
                lines = [f"{e.student_name} ({e.status}) - {e.source}" for e in enqs]
                return "Recent enquiries:\n" + "\n".join(lines)
            return "No enquiries recorded yet."

        # General greeting
        words = set(msg_lower.split())
        if words & {'hello', 'hi', 'hey', 'greetings'} and len(words) <= 4:
            return "Hello! I'm your AI institute assistant. Ask me anything about students, fees, attendance, courses, or exams. Type 'help' to see what I can do."

        # Fallback
        return (
            "I'm not sure how to answer that. I can help with questions about students, "
            "courses, fees, attendance, exams, and leaves. Try 'help' for examples."
        )
