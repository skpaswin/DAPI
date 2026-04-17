from flask import Flask, render_template, request, redirect, session, jsonify
import json, os, logging
from datetime import date, datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import requests, re
import google.generativeai as genai
import firebase_db as fdb

# ─── Logging ────────────────────────────────────────────────────────────────
log_dir = os.environ.get("LOG_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"))
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "app.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ─── Flask App ───────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dapi_secret_key_dev_only")
app.config["UPLOAD_FOLDER"] = os.environ.get(
    "UPLOAD_FOLDER",
    os.path.join("static", "uploads", "certificates")
)
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# ─── Bootstrap Admin ─────────────────────────────────────────────────────────
def init_app():
    admin_email = "aswinsuganth@gmail.com"
    admin_pass_hash = generate_password_hash("skp_aswin")
    try:
        fdb.ensure_admin(admin_email, admin_pass_hash)
        logger.info("Firebase initialised and admin verified.")
    except Exception as e:
        logger.error(f"Firebase init error: {e}")

init_app()


# ─── Helpers ─────────────────────────────────────────────────────────────────
def safe_int(x, default=0):
    try:
        if x is None: return default
        x = str(x).strip()
        if x == "": return default
        return int(float(x))
    except:
        return default


def safe_float(x, default=None):
    try:
        if x is None: return default
        x = str(x).strip()
        if x == "": return default
        return float(x)
    except:
        return default


def parse_ymd(s: str):
    return datetime.strptime(s, "%Y-%m-%d").date()


def college_working_days(start_date: date, end_date: date) -> int:
    if end_date < start_date:
        return 0
    delta = (end_date - start_date).days + 1
    return sum(1 for i in range(delta) if (start_date + timedelta(days=i)).weekday() != 6)


def calc_attendance(student_row):
    try:
        start = parse_ymd(student_row["semester_start"])
    except:
        start = date.today()
    total_days = college_working_days(start, date.today())
    present = int(student_row.get("present_days") or 0)
    val = float(present) / float(total_days) * 100.0 if total_days > 0 else 0.0
    pct = 0.0 if total_days <= 0 else float(f"{val:.2f}")
    pct = max(0.0, min(100.0, pct))
    return total_days, present, pct


def calc_cgpa(student_row):
    sems = []
    for k in ["sem1","sem2","sem3","sem4","sem5","sem6","sem7","sem8"]:
        v = student_row.get(k)
        if v is not None:
            try: sems.append(float(v))
            except: pass
    if not sems:
        return None
    return float(f"{sum(sems)/len(sems):.2f}")


def validate_email_role(email: str, role: str) -> bool:
    email = (email or "").strip().lower()
    if role == "admin":
        return email == "aswinsuganth@gmail.com"
    if role == "student":
        return email.endswith(".student@gmail.com")
    if role == "staff":
        return email.endswith(".staff@gmail.com")
    return False


def get_score_breakdown(student_row):
    if not isinstance(student_row, dict):
        student_row = dict(student_row)

    cgpa = calc_cgpa(student_row) or 0.0
    exam_points = (cgpa / 10.0) * 3.0

    hsc_val = safe_float(student_row.get("hsc_cutoff", 0), 0.0)
    hsc_points = (min(200.0, hsc_val) / 200.0) * 1.0

    assign_score = safe_float(student_row.get("assignments_score", 0), 0.0)
    assignment_points = (assign_score / 100.0) * 3.0

    _, _, att_pct = calc_attendance(student_row)
    attendance_points = (att_pct / 100.0) * 2.0

    part_score = safe_float(student_row.get("participation_score", 0), 0.0)
    participation_points = (part_score / 100.0) * 1.0

    arrears = max(0, int(student_row.get("arrear_count", 0) or 0))
    penalty = min(4.0, arrears * 1.0)

    total = max(0.0, min(10.0,
        exam_points + hsc_points + assignment_points + attendance_points + participation_points - penalty
    ))

    return {
        "exam_points":          round(float(exam_points), 2),
        "hsc_points":           round(float(hsc_points), 2),
        "assignment_points":    round(float(assignment_points), 2),
        "attendance_points":    round(float(attendance_points), 2),
        "participation_points": round(float(participation_points), 2),
        "penalty":              round(float(penalty), 2),
        "total":                round(float(total), 2),
    }


def calc_placement_score(student_row):
    return get_score_breakdown(student_row)["total"]


def refresh_score(student_email: str, student_row=None):
    if student_row is None:
        student_row = fdb.get_student(student_email)
    if not student_row:
        return
    score = calc_placement_score(student_row)
    fdb.update_student_score(student_email, score)


def fetch_coding_stats(leetcode_url, github_url):
    lc_solved = 0
    gh_repos = 0
    if github_url and "github.com/" in github_url:
        try:
            username = github_url.split("github.com/")[-1].strip("/")
            resp = requests.get(f"https://api.github.com/users/{username}", timeout=5)
            if resp.status_code == 200:
                gh_repos = resp.json().get("public_repos", 0)
        except: pass
    if leetcode_url and "leetcode.com/" in leetcode_url:
        try:
            username = leetcode_url.split("u/")[-1].strip("/") if "u/" in leetcode_url else leetcode_url.split("leetcode.com/")[-1].strip("/")
            resp = requests.get(f"https://leetcode-stats-api.herokuapp.com/{username}", timeout=5)
            if resp.status_code == 200:
                lc_solved = resp.json().get("totalSolved", 0)
        except: pass
    return lc_solved, gh_repos


def generate_ai_feedback(student_row, score_breakdown):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not isinstance(student_row, dict):
        try: student_row = dict(student_row)
        except: pass

    cgpa = calc_cgpa(student_row) or 0.0
    _, _, att_pct = calc_attendance(student_row)
    arrears = int(student_row.get("arrear_count", 0) or 0)
    lc_solved = int(student_row.get("leetcode_solved", 0) or 0)
    gh_repos = int(student_row.get("github_repos", 0) or 0)
    total_score = score_breakdown.get("total", 0)

    if total_score < 5.0:
        status = "YOU NEED TO IMPROVE YOUR STUDIES"
    elif total_score < 8.0:
        status = "YOU NEED TO IMPROVE YOUR SKILLS"
    else:
        status = "YOUR DAPI SCORE IS ENOUGH. WELDONE!"

    context = f"""
    Student Name: {student_row.get('name','')}
    CGPA: {cgpa}/10
    Attendance: {att_pct}%
    Arrears: {arrears}
    LeetCode Solved: {lc_solved}
    GitHub Repos: {gh_repos}
    Placement Score: {total_score}/10
    Determined status: {status}
    """

    if api_key:
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = f"""
            You are an expert career and academic advisor for a student at a technical university.
            Based on the following student metrics, provide a concise (2-3 sentences), encouraging feedback.
            Your response MUST start with this status line: "{status}"
            Metrics:
            {context}
            Focus on their weakest areas to explain why they got this status and how to improve.
            """
            response = model.generate_content(prompt)
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            logger.error(f"Gemini API error: {e}")

    tips = []
    if arrears > 0: tips.append(f"Clear your {arrears} arrears.")
    if att_pct < 75: tips.append("Improve attendance.")
    if cgpa < 7.0: tips.append("Boost CGPA.")
    if lc_solved < 50: tips.append("Practice on LeetCode.")
    if gh_repos < 3: tips.append("Build projects on GitHub.")

    feedback_msg = f"{status}. "
    if tips:
        feedback_msg += "Advice: " + " ".join(tips[:2])
    elif total_score >= 8.0:
        feedback_msg += "Keep maintaining your high standards!"
    return feedback_msg


def validate_profile_urls(lc, gh, li):
    errors = []
    if lc:
        lc = lc.strip()
        if not re.match(r"^https?://(www\.)?leetcode\.com/(u/)?[\w-]+/?$", lc):
            errors.append("Invalid url please provide your profile link")
    if gh:
        gh = gh.strip()
        if not re.match(r"^https?://(www\.)?github\.com/[\w-]+/?$", gh):
            if "Invalid url please provide your profile link" not in errors:
                errors.append("Invalid url please provide your profile link")
    if li:
        li = li.strip()
        if not re.match(r"^https?://(www\.)?linkedin\.com/in/[\w-]+/?$", li):
            if "Invalid url please provide your profile link" not in errors:
                errors.append("Invalid url please provide your profile link")
    return errors


def require_role(role):
    return session.get("role") == role


# ═══════════════════════════════════════════════════════════════════════════════
# AUTH ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    if session.get("role"):
        return redirect("/student" if session["role"] == "student" else "/staff")
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        role  = request.form.get("role", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        if not role or not email or not password:
            return render_template("login.html", error="Please fill all fields")

        user = fdb.get_user(email, role)

        if user and user.get("is_blocked"):
            return render_template("login.html", error="Your account has been deactivated. Please contact the administrator.")

        if user is None or not check_password_hash(user["password_hash"], password):
            return render_template("login.html", error="Invalid email or password")

        session["role"]  = role
        session["email"] = email

        if role == "admin":
            return redirect("/admin")
        return redirect("/student" if role == "student" else "/staff")

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ─── Register Student ─────────────────────────────────────────────────────────
@app.route("/register/student", methods=["GET", "POST"])
def register_student():
    if not require_role("staff"):
        return redirect("/")

    message = None
    error = None

    if request.method == "POST":
        login_email = request.form.get("login_email", "").strip().lower()
        login_pass  = request.form.get("login_pass", "").strip()

        student_id    = request.form.get("student_id", "").strip()
        enrollment_no = request.form.get("enrollment_no", "").strip()
        roll          = request.form.get("roll", "").strip()
        register_no   = request.form.get("register_no", "").strip()
        name          = request.form.get("name", "").strip()
        batch         = request.form.get("batch", "").strip()
        gender        = request.form.get("gender", "").strip()
        blood_group   = request.form.get("blood_group", "").strip()
        dob           = request.form.get("dob", "").strip()
        aadhar_no     = request.form.get("aadhar_no", "").strip()
        contact_email = request.form.get("contact_email", "").strip().lower()

        phone            = request.form.get("phone", "").strip()
        father_name      = request.form.get("father_name", "").strip()
        mother_name      = request.form.get("mother_name", "").strip()
        parent_phone     = request.form.get("parent_phone", "").strip()
        parent_occupation= request.form.get("parent_occupation", "").strip()
        parent_income    = safe_float(request.form.get("parent_income"), 0.0)
        mother_tongue    = request.form.get("mother_tongue", "").strip()
        community        = request.form.get("community", "").strip()
        religion         = request.form.get("religion", "").strip()
        nationality      = request.form.get("nationality", "INDIAN").strip()
        address          = request.form.get("address", "").strip()

        department  = request.form.get("department", "").strip()
        mentor_name = request.form.get("mentor_name", "").strip()

        scholar_type = request.form.get("scholar_type", "Day Scholar").strip()
        warden_name  = request.form.get("warden_name", "").strip()
        room_no      = request.form.get("room_no", "").strip()

        tenth    = request.form.get("tenth", "").strip()
        twelfth  = request.form.get("twelfth", "").strip()
        physics_marks   = safe_float(request.form.get("physics_marks"), 0.0)
        chemistry_marks = safe_float(request.form.get("chemistry_marks"), 0.0)
        maths_marks     = safe_float(request.form.get("maths_marks"), 0.0)
        cs_marks        = safe_float(request.form.get("cs_marks"), 0.0)
        biology_marks   = safe_float(request.form.get("biology_marks"), 0.0)

        third_subject = chemistry_marks
        if cs_marks > 0:
            third_subject = cs_marks
        elif biology_marks > 0:
            third_subject = biology_marks

        hsc_cutoff_str = request.form.get("hsc_cutoff", "").strip()
        if not hsc_cutoff_str and (physics_marks > 0 or third_subject > 0 or maths_marks > 0):
            hsc_cutoff = round(maths_marks + (physics_marks / 2.0) + (third_subject / 2.0), 2)
        else:
            hsc_cutoff = safe_float(hsc_cutoff_str, 0.0)

        semester_start     = request.form.get("semester_start", "").strip()
        present_days       = safe_int(request.form.get("present_days"), 0)
        arrears            = safe_int(request.form.get("arrear_count"), 0)
        dte_umis_reg_no    = request.form.get("dte_umis_reg_no", "").strip()
        application_no     = request.form.get("application_no", "").strip()
        admission_no       = request.form.get("admission_no", "").strip()
        school_name        = request.form.get("school_name", "").strip()
        custom_dept        = request.form.get("custom_department", "").strip()
        assignments_score  = safe_float(request.form.get("assignments_score"), 0.0)
        participation_score= safe_float(request.form.get("participation_score"), 0.0)
        leetcode_url       = request.form.get("leetcode_url", "").strip()
        github_url         = request.form.get("github_url", "").strip()
        linkedin_url       = request.form.get("linkedin_url", "").strip()

        if department == "OTHER" and custom_dept:
            department = custom_dept
        department = department.upper()

        if not all([login_email, login_pass, student_id, roll, name, contact_email,
                    phone, parent_phone, address, department, mentor_name,
                    tenth, twelfth, semester_start, batch, gender, dob]):
            error = "Please fill all required fields"
            return render_template("register_student.html", message=message, error=error)

        if not validate_email_role(login_email, "student"):
            error = 'Student email must be like "name".student@gmail.com'
            return render_template("register_student.html", message=message, error=error)

        try:
            parse_ymd(semester_start)
        except:
            error = "Semester Start must be YYYY-MM-DD"
            return render_template("register_student.html", message=message, error=error)

        if scholar_type == "Hosteller" and (not warden_name or not room_no):
            error = "If Hosteller: warden name + room no required"
            return render_template("register_student.html", message=message, error=error)

        sems = {f"sem{i}": safe_float(request.form.get(f"sem{i}")) for i in range(1, 9)}

        ach_titles = request.form.getlist("ach_title[]")
        ach_levels = request.form.getlist("ach_level[]")
        ach_dates  = request.form.getlist("ach_dates[]")
        ach_descs  = request.form.getlist("ach_desc[]")

        skill_names  = request.form.getlist("skill_name[]")
        skill_levels = request.form.getlist("skill_levels[]")

        cert_names       = request.form.getlist("cert_name[]")
        cert_providers   = request.form.getlist("cert_provider[]")
        cert_issue_dates = request.form.getlist("cert_issue_date[]")

        try:
            lc_solved, gh_repos = fetch_coding_stats(leetcode_url, github_url)

            fdb.insert_user(login_email, "student", generate_password_hash(login_pass))

            student_data = {
                "student_id": student_id, "roll": roll, "name": name,
                "contact_email": contact_email, "phone": phone,
                "parent_phone": parent_phone, "address": address,
                "department": department, "mentor_name": mentor_name,
                "scholar_type": scholar_type,
                "warden_name": warden_name if scholar_type == "Hosteller" else "",
                "room_no": room_no if scholar_type == "Hosteller" else "",
                "tenth": tenth, "twelfth": twelfth,
                "semester_start": semester_start,
                "semester_end": "2026-05-30",
                "present_days": max(0, present_days),
                "arrear_count": max(0, arrears),
                **sems,
                "placement_score": 0.0,
                "batch": batch, "enrollment_no": enrollment_no,
                "register_no": register_no,
                "dte_umis_reg_no": dte_umis_reg_no,
                "application_no": application_no,
                "admission_no": admission_no,
                "gender": gender, "blood_group": blood_group, "dob": dob,
                "aadhar_no": aadhar_no, "father_name": father_name,
                "mother_name": mother_name,
                "parent_occupation": parent_occupation,
                "parent_income": parent_income,
                "mother_tongue": mother_tongue,
                "community": community, "religion": religion,
                "nationality": nationality,
                "physics_marks": physics_marks,
                "chemistry_marks": chemistry_marks,
                "maths_marks": maths_marks,
                "cs_marks": cs_marks, "biology_marks": biology_marks,
                "hsc_cutoff": hsc_cutoff, "school_name": school_name,
                "leetcode_url": leetcode_url, "github_url": github_url,
                "linkedin_url": linkedin_url,
                "leetcode_solved": lc_solved, "github_repos": gh_repos,
                "assignments_score": assignments_score,
                "participation_score": participation_score,
            }
            fdb.insert_student(login_email, student_data)

            for idx, title in enumerate(ach_titles):
                title = (title or "").strip()
                if not title: continue
                level    = ach_levels[idx] if idx < len(ach_levels) else ""
                date_str = ach_dates[idx] if idx < len(ach_dates) else ""
                desc     = ach_descs[idx] if idx < len(ach_descs) else ""
                fdb.insert_achievement(login_email, title, str(level), date_str, desc)

            for idx, sname in enumerate(skill_names):
                sname = (sname or "").strip()
                if not sname: continue
                levels = safe_int(skill_levels[idx] if idx < len(skill_levels) else None, 0)
                fdb.insert_skill(login_email, sname, levels)

            for idx, cname in enumerate(cert_names):
                cname = (cname or "").strip()
                if not cname: continue
                provider   = cert_providers[idx] if idx < len(cert_providers) else ""
                issue_date = cert_issue_dates[idx] if idx < len(cert_issue_dates) else ""
                fdb.insert_certification(login_email, cname, provider, issue_date)

            refresh_score(login_email)
            message = "Student Registered Successfully ✅"

        except ValueError:
            error = "Email or Roll already exists"
        except Exception as e:
            error = f"Error: {e}"

    return render_template("register_student.html", message=message, error=error)


# ─── Register Staff ───────────────────────────────────────────────────────────
@app.route("/register/staff", methods=["GET", "POST"])
def register_staff():
    if not require_role("admin"):
        return redirect("/")

    message = None
    error = None

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        if not email or not password:
            return render_template("register_staff.html", message=None, error="Fill all fields")

        if not validate_email_role(email, "staff"):
            return render_template("register_staff.html", message=None,
                                   error='Staff email must be like "name".staff@gmail.com')

        try:
            fdb.insert_user(email, "staff", generate_password_hash(password))
            message = "Staff Registered ✅ Now login!"
        except ValueError:
            error = "Staff email already exists"
        except Exception as e:
            error = f"Error: {e}"

    return render_template("register_staff.html", message=message, error=error)


# ═══════════════════════════════════════════════════════════════════════════════
# STUDENT PORTAL
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/student", methods=["GET", "POST"])
def student_portal():
    if not require_role("student"):
        return redirect("/")

    tab = (request.args.get("tab") or "profile").strip()
    if tab in ["achievements", "certifications"]:
        tab = "awards"

    email   = session.get("email")
    student = fdb.get_student(email)

    if not student:
        return redirect("/register/student")

    message = None
    error   = None

    # Populate missing defaults for legacy records
    if student.get("batch") is None:
        defaults = {
            "batch": "2023", "enrollment_no": "2023UIT1076",
            "register_no": "7376232IT117", "gender": "MALE",
            "nationality": "INDIAN", "physics_marks": 89.0,
            "chemistry_marks": 93.0, "maths_marks": 87.0,
            "cs_marks": 94.0, "fees_due": 0.0, "ps_rank": 0,
        }
        fdb.update_student(email, defaults)
        student = fdb.get_student(email)

    if request.method == "POST":
        form_type = request.form.get("form_type", "").strip()

        # ── Profile update ────────────────────────────────────────────────
        if form_type == "profile":
            name          = request.form.get("name", "").strip()
            contact_email = request.form.get("contact_email", "").strip().lower()
            phone         = request.form.get("phone", "").strip()
            parent_phone  = request.form.get("parent_phone", "").strip()
            address       = request.form.get("address", "").strip()
            department    = request.form.get("department", "").strip()
            mentor_name   = request.form.get("mentor_name", "").strip()
            scholar_type  = request.form.get("scholar_type", "Day Scholar").strip()
            warden_name   = request.form.get("warden_name", "").strip()
            room_no       = request.form.get("room_no", "").strip()
            batch         = request.form.get("batch", "").strip()
            enroll_no     = request.form.get("enrollment_no", "").strip()
            reg_no        = request.form.get("register_no", "").strip()
            umis_no       = request.form.get("dte_umis_reg_no", "").strip()
            app_no        = request.form.get("application_no", "").strip()
            adm_no        = request.form.get("admission_no", "").strip()
            father        = request.form.get("father_name", "").strip()
            mother        = request.form.get("mother_name", "").strip()
            gender        = request.form.get("gender", "").strip()
            dob           = request.form.get("dob", "").strip()
            community     = request.form.get("community", "").strip()
            religion      = request.form.get("religion", "").strip()
            nationality   = request.form.get("nationality", "").strip()
            mother_tongue = request.form.get("mother_tongue", "").strip()
            blood_group   = request.form.get("blood_group", "").strip()
            aadhar_no     = request.form.get("aadhar_no", "").strip()
            p_occ         = request.form.get("parent_occupation", "").strip()
            p_inc         = safe_float(request.form.get("parent_income"), 0.0)
            leetcode_url  = request.form.get("leetcode_url", "").strip()
            github_url    = request.form.get("github_url", "").strip()
            linkedin_url  = request.form.get("linkedin_url", "").strip()

            fields_to_check = [name, contact_email, phone, parent_phone, address, department, mentor_name]
            if not all(fields_to_check):
                error = "Fill all required fields"
            else:
                url_errors = validate_profile_urls(leetcode_url, github_url, linkedin_url)
                if url_errors:
                    error = " | ".join(url_errors)
                else:
                    lc_solved, gh_repos = fetch_coding_stats(leetcode_url, github_url)
                    fdb.update_student(email, {
                        "name": name, "contact_email": contact_email,
                        "phone": phone, "parent_phone": parent_phone,
                        "address": address, "department": department,
                        "mentor_name": mentor_name, "scholar_type": scholar_type,
                        "warden_name": warden_name if scholar_type == "Hosteller" else "",
                        "room_no": room_no if scholar_type == "Hosteller" else "",
                        "batch": batch, "enrollment_no": enroll_no,
                        "register_no": reg_no, "dte_umis_reg_no": umis_no,
                        "application_no": app_no, "admission_no": adm_no,
                        "father_name": father, "mother_name": mother,
                        "gender": gender, "dob": dob, "community": community,
                        "religion": religion, "nationality": nationality,
                        "mother_tongue": mother_tongue, "blood_group": blood_group,
                        "aadhar_no": aadhar_no, "parent_occupation": p_occ,
                        "parent_income": p_inc,
                        "leetcode_url": leetcode_url, "github_url": github_url,
                        "linkedin_url": linkedin_url,
                        "leetcode_solved": lc_solved, "github_repos": gh_repos,
                    })
                    message = "Profile & Professional Links updated ✅"

        # ── Academics update ──────────────────────────────────────────────
        elif form_type == "academics":
            semester_start      = request.form.get("semester_start", "").strip()
            present_days        = max(0, safe_int(request.form.get("present_days"), 0))
            arrears             = max(0, safe_int(request.form.get("arrear_count"), 0))
            assignments_score   = safe_float(request.form.get("assignments_score"), 0.0)
            participation_score = safe_float(request.form.get("participation_score"), 0.0)
            sems = {f"sem{i}": safe_float(request.form.get(f"sem{i}")) for i in range(1, 9)}
            p_marks  = safe_float(request.form.get("physics_marks"), 0.0)
            c_marks  = safe_float(request.form.get("chemistry_marks"), 0.0)
            m_marks  = safe_float(request.form.get("maths_marks"), 0.0)
            cs_marks = safe_float(request.form.get("cs_marks"), 0.0)
            b_marks  = safe_float(request.form.get("biology_marks"), 0.0)

            try: parse_ymd(semester_start)
            except: error = "Semester Start must be YYYY-MM-DD"

            if error is None:
                fdb.update_student(email, {
                    "semester_start": semester_start,
                    "present_days": present_days, "arrear_count": arrears,
                    "physics_marks": p_marks, "chemistry_marks": c_marks,
                    "maths_marks": m_marks, "cs_marks": cs_marks, "biology_marks": b_marks,
                    "assignments_score": assignments_score,
                    "participation_score": participation_score,
                    **sems,
                })
                refresh_score(email)
                message = "Academic records calibrated! ✅"

        # ── Skills ────────────────────────────────────────────────────────
        elif form_type == "skill_add":
            skill_name = request.form.get("skill_name", "").strip()
            levels     = max(0, min(10, safe_int(request.form.get("levels_completed"), 0)))
            if not skill_name:
                error = "Skill name required"
            else:
                fdb.insert_skill(email, skill_name, levels)
                refresh_score(email)
                message = "Skill added ✅"

        elif form_type == "skill_delete":
            sid = request.form.get("id", "").strip()
            fdb.delete_skill(sid, email)
            refresh_score(email)
            message = "Skill deleted ✅"

        # ── Achievements ──────────────────────────────────────────────────
        elif form_type == "ach_add":
            title = request.form.get("title", "").strip()
            if not title:
                error = "Achievement title required"
            else:
                fdb.insert_achievement(
                    email, title,
                    request.form.get("level", "").strip(),
                    request.form.get("date_str", "").strip(),
                    request.form.get("description", "").strip()
                )
                refresh_score(email)
                message = "Achievement added ✅"

        elif form_type == "ach_delete":
            aid = request.form.get("id", "").strip()
            fdb.delete_achievement(aid, email)
            refresh_score(email)
            message = "Achievement deleted ✅"

        # ── Certifications ────────────────────────────────────────────────
        elif form_type == "cert_add":
            cert_name      = request.form.get("name", "").strip()
            provider       = request.form.get("provider", "").strip()
            issue_date     = request.form.get("issue_date", "").strip()
            credential_url = request.form.get("credential_url", "").strip()
            file           = request.files.get("cert_file")
            file_path      = None

            if not cert_name:
                error = "Certification name required"
            else:
                if file and file.filename != "":
                    filename = secure_filename(f"{email}_{datetime.now().timestamp()}_{file.filename}")
                    file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
                    file_path = f"uploads/certificates/{filename}"
                fdb.insert_certification(email, cert_name, provider, issue_date,
                                         credential_url, file_path, "Pending")
                refresh_score(email)
                message = "Certification added (Pending Verification) ✅"

        elif form_type == "cert_delete":
            cid = request.form.get("id", "").strip()
            fdb.delete_certification(cid, email)
            refresh_score(email)
            message = "Certification deleted ✅"

    # ── Reload after any POST ─────────────────────────────────────────────
    student = fdb.get_student(email)
    total_days, present, attendance_pct = calc_attendance(student)
    cgpa    = calc_cgpa(student)
    sgpas   = [student.get(f"sem{i}") for i in range(1, 9)]

    skills       = fdb.get_skills(email)
    achievements = fdb.get_achievements(email)
    certs        = fdb.get_certifications(email)
    breakdown    = get_score_breakdown(student)

    try:
        ai_message = generate_ai_feedback(student, breakdown)
        if not ai_message:
            ai_message = "Your academic journey is unique. Stay focused on your goals!"
    except Exception as e:
        logger.error(f"AI Feedback failed: {e}")
        ai_message = "Keep pushing your limits and refine your technical skills every day."

    return render_template(
        "student_portal.html",
        tab=tab, student=student,
        message=message, error=error,
        total_days=total_days, present=present,
        attendance_pct=attendance_pct, cgpa=cgpa,
        score=student.get("placement_score", 0),
        sgpas=sgpas, skills=skills,
        achievements=achievements, certs=certs,
        breakdown=breakdown, ai_message=ai_message
    )


@app.route("/achievements")
def achievements_page():
    if not require_role("student"): return redirect("/")
    return redirect("/student?tab=awards")


@app.route("/certifications")
def certifications_page():
    if not require_role("student"): return redirect("/")
    return redirect("/student?tab=awards")


# ═══════════════════════════════════════════════════════════════════════════════
# STAFF PORTAL
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/staff", methods=["GET", "POST"])
def staff_dashboard():
    if not require_role("staff"):
        return redirect("/")

    q = (request.form.get("query", "") if request.method == "POST"
         else request.args.get("query", "")).strip()

    all_students = fdb.get_all_students(query=q if q else None)

    dept_map = {}
    for s in all_students:
        dept = (s.get("department") or "Unknown").strip().upper()
        _, _, att_pct = calc_attendance(s)
        s["attendance_pct"] = att_pct
        dept_map.setdefault(dept, []).append(s)

    return render_template("staff_dashboard.html", dept_map=dept_map, query=q)


@app.route("/staff/student/<sid>", methods=["GET", "POST"])
def staff_student_portal(sid):
    """sid is the student's Firestore document ID (= user_email)."""
    if not require_role("staff"):
        return redirect("/")

    tab = (request.form.get("tab") or request.args.get("tab") or "profile").strip()
    if tab in ["achievements", "certifications"]:
        tab = "awards"

    student = fdb.get_student(sid)
    if not student:
        return "Student not found", 404

    student_email = student.get("user_email", sid)
    message = None
    error   = None

    if request.method == "POST":
        form_type = request.form.get("form_type", "").strip()

        # ── Full edit ─────────────────────────────────────────────────────
        if form_type == "edit":
            name          = request.form.get("name", "").strip()
            contact_email = request.form.get("contact_email", "").strip().lower()
            phone         = request.form.get("phone", "").strip()
            parent_phone  = request.form.get("parent_phone", "").strip()
            address       = request.form.get("address", "").strip()
            batch         = request.form.get("batch", "").strip()
            dob           = request.form.get("dob", "").strip()
            gender        = request.form.get("gender", "").strip()
            community     = request.form.get("community", "").strip()
            religion      = request.form.get("religion", "").strip()
            nationality   = request.form.get("nationality", "INDIAN").strip()
            mother_tongue = request.form.get("mother_tongue", "").strip()
            blood_group   = request.form.get("blood_group", "").strip()
            enrollment_no = request.form.get("enrollment_no", "").strip()
            register_no   = request.form.get("register_no", "").strip()
            roll          = request.form.get("roll", "").strip()
            dte_umis      = request.form.get("dte_umis_reg_no", "").strip()
            app_no        = request.form.get("application_no", "").strip()
            adm_no        = request.form.get("admission_no", "").strip()
            father_name   = request.form.get("father_name", "").strip()
            mother_name   = request.form.get("mother_name", "").strip()
            aadhar_no     = request.form.get("aadhar_no", "").strip()
            parent_occ    = request.form.get("parent_occupation", "").strip()
            parent_inc    = safe_float(request.form.get("parent_income"), 0.0)
            semester_start      = request.form.get("semester_start", "").strip()
            present_days        = max(0, safe_int(request.form.get("present_days"), 0))
            arrears             = max(0, safe_int(request.form.get("arrear_count"), 0))
            sems = {f"sem{i}": safe_float(request.form.get(f"sem{i}")) for i in range(1, 9)}
            p_marks  = safe_float(request.form.get("physics_marks"), 0.0)
            c_marks  = safe_float(request.form.get("chemistry_marks"), 0.0)
            m_marks  = safe_float(request.form.get("maths_marks"), 0.0)
            cs_marks = safe_float(request.form.get("cs_marks"), 0.0)
            b_marks  = safe_float(request.form.get("biology_marks"), 0.0)
            third_sub = c_marks
            if cs_marks > 0: third_sub = cs_marks
            elif b_marks > 0: third_sub = b_marks
            computed_cutoff = round(m_marks + (p_marks / 2.0) + (third_sub / 2.0), 2)
            hsc_cutoff = computed_cutoff if computed_cutoff > 0 else safe_float(request.form.get("hsc_cutoff", ""), 0.0)
            school_name         = request.form.get("school_name", "").strip()
            assignments_score   = safe_float(request.form.get("assignments_score"), 0.0)
            participation_score = safe_float(request.form.get("participation_score"), 0.0)
            department  = request.form.get("department", student.get("department", "")).strip().upper()
            mentor_name = request.form.get("mentor_name", student.get("mentor_name", "")).strip()
            scholar_type= request.form.get("scholar_type", student.get("scholar_type", "Day Scholar")).strip()
            warden_name = request.form.get("warden_name", "").strip()
            room_no     = request.form.get("room_no", "").strip()

            if not all([name, contact_email, phone, parent_phone, address, semester_start]):
                error = "Fill all required fields"
            else:
                try: parse_ymd(semester_start)
                except: error = "Semester Start must be YYYY-MM-DD"

            if scholar_type == "Hosteller" and (not warden_name or not room_no):
                error = "If Hosteller: warden name + room no required"

            if error is None:
                fdb.update_student(student_email, {
                    "name": name, "contact_email": contact_email,
                    "phone": phone, "parent_phone": parent_phone, "address": address,
                    "department": department, "mentor_name": mentor_name,
                    "scholar_type": scholar_type,
                    "warden_name": warden_name if scholar_type == "Hosteller" else "",
                    "room_no": room_no if scholar_type == "Hosteller" else "",
                    "batch": batch, "dob": dob, "gender": gender,
                    "community": community, "religion": religion,
                    "nationality": nationality, "mother_tongue": mother_tongue,
                    "blood_group": blood_group, "enrollment_no": enrollment_no,
                    "register_no": register_no, "roll": roll,
                    "dte_umis_reg_no": dte_umis, "application_no": app_no,
                    "admission_no": adm_no, "father_name": father_name,
                    "mother_name": mother_name, "aadhar_no": aadhar_no,
                    "parent_occupation": parent_occ, "parent_income": parent_inc,
                    "semester_start": semester_start,
                    "present_days": present_days, "arrear_count": arrears,
                    "physics_marks": p_marks, "chemistry_marks": c_marks,
                    "maths_marks": m_marks, "cs_marks": cs_marks, "biology_marks": b_marks,
                    "hsc_cutoff": hsc_cutoff, "school_name": school_name,
                    "assignments_score": assignments_score,
                    "participation_score": participation_score,
                    **sems,
                })
                refresh_score(student_email)
                message = "Student records synchronized! ✅"

        elif form_type == "skill_add":
            skill_name = request.form.get("skill_name", "").strip()
            levels = max(0, min(10, safe_int(request.form.get("levels_completed"), 0)))
            if not skill_name:
                error = "Skill name required"
            else:
                fdb.insert_skill(student_email, skill_name, levels)
                refresh_score(student_email)
                message = "Skill added ✅"

        elif form_type == "skill_edit":
            skill_id   = request.form.get("id", "").strip()
            skill_name = request.form.get("skill_name", "").strip()
            levels     = max(0, min(10, safe_int(request.form.get("levels_completed"), 0)))
            if not skill_name:
                error = "Skill name required"
            else:
                fdb.update_skill(skill_id, student_email, skill_name, levels)
                refresh_score(student_email)
                message = "Skill updated ✅"

        elif form_type == "skill_delete":
            skill_id = request.form.get("id", "").strip()
            fdb.delete_skill(skill_id, student_email)
            refresh_score(student_email)
            message = "Skill deleted ✅"

        elif form_type == "achievement_add":
            title    = request.form.get("title", "").strip()
            level    = request.form.get("level", "").strip()
            date_str = request.form.get("date_str", "").strip()
            if not title:
                error = "Achievement title required"
            else:
                if date_str:
                    try: parse_ymd(date_str)
                    except: error = "Achievement date must be YYYY-MM-DD"
                if error is None:
                    fdb.insert_achievement(student_email, title, level, date_str)
                    refresh_score(student_email)
                    message = "Achievement added ✅"

        elif form_type == "achievement_edit":
            ach_id   = request.form.get("id", "").strip()
            title    = request.form.get("title", "").strip()
            level    = request.form.get("level", "").strip()
            date_str = request.form.get("date_str", "").strip()
            if not title:
                error = "Achievement title required"
            else:
                if date_str:
                    try: parse_ymd(date_str)
                    except: error = "Achievement date must be YYYY-MM-DD"
                if error is None:
                    fdb.update_achievement(ach_id, student_email, title, level, date_str)
                    refresh_score(student_email)
                    message = "Achievement updated ✅"

        elif form_type == "achievement_delete":
            ach_id = request.form.get("id", "").strip()
            fdb.delete_achievement(ach_id, student_email)
            refresh_score(student_email)
            message = "Achievement deleted ✅"

        elif form_type == "cert_add":
            cert_name      = request.form.get("name", "").strip()
            provider       = request.form.get("provider", "").strip()
            issue_date     = request.form.get("issue_date", "").strip()
            credential_url = request.form.get("credential_url", "").strip()
            file           = request.files.get("cert_file")
            file_path      = None
            if not cert_name:
                error = "Certification name required"
            else:
                if file and file.filename != "":
                    filename = secure_filename(f"{student_email}_{datetime.now().timestamp()}_{file.filename}")
                    file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
                    file_path = f"uploads/certificates/{filename}"
                fdb.insert_certification(student_email, cert_name, provider, issue_date,
                                         credential_url, file_path, "Verified")
                refresh_score(student_email)
                message = "Certification added & verified ✅"

        elif form_type == "cert_edit":
            cert_id    = request.form.get("id", "").strip()
            cert_name  = request.form.get("name", "").strip()
            provider   = request.form.get("provider", "").strip()
            issue_date = request.form.get("issue_date", "").strip()
            if not cert_name:
                error = "Certification name required"
            else:
                if issue_date:
                    try: parse_ymd(issue_date)
                    except: error = "Certification date must be YYYY-MM-DD"
                if error is None:
                    fdb.update_certification(cert_id, student_email, cert_name, provider, issue_date)
                    refresh_score(student_email)
                    message = "Certification updated ✅"

        elif form_type == "cert_delete":
            cert_id = request.form.get("id", "").strip()
            fdb.delete_certification(cert_id, student_email)
            refresh_score(student_email)
            message = "Certification deleted ✅"

        elif form_type == "cert_verify":
            cert_id = request.form.get("id", "").strip()
            status  = request.form.get("status", "Verified")
            fdb.update_certification_status(cert_id, status)
            refresh_score(student_email)
            message = f"Certification {status} ✅"

    # ── Reload ────────────────────────────────────────────────────────────
    student = fdb.get_student(student_email)
    total_days, present, attendance_pct = calc_attendance(student)
    cgpa  = calc_cgpa(student)
    sgpas = [student.get(f"sem{i}") for i in range(1, 9)]

    skills       = fdb.get_skills(student_email)
    achievements = fdb.get_achievements(student_email)
    certs        = fdb.get_certifications(student_email)
    breakdown    = get_score_breakdown(student)

    try:
        ai_message = generate_ai_feedback(student, breakdown)
    except:
        ai_message = "Consistent academic effort."

    return render_template(
        "staff_student_portal.html",
        tab=tab, student=student,
        message=message, error=error,
        total_days=total_days, present=present,
        attendance_pct=attendance_pct, cgpa=cgpa,
        score=student.get("placement_score", 0),
        breakdown=breakdown, sgpas=sgpas,
        skills=skills, achievements=achievements,
        certs=certs, ai_message=ai_message
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN PORTAL
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/admin", methods=["GET", "POST"])
def admin_dashboard():
    if not require_role("admin"):
        return redirect("/")

    q = (request.form.get("query", "") if request.method == "POST"
         else request.args.get("query", "")).strip()

    staff_list   = fdb.get_all_staff()
    departments  = fdb.get_students_by_dept(query=q if q else None)
    staff_count  = len(staff_list)
    student_count= sum(len(v) for v in departments.values())

    # Filter staff by query if provided
    if q:
        ql = q.lower()
        staff_list = [s for s in staff_list if ql in s.get("email", "").lower()]

    return render_template(
        "admin_dashboard.html",
        staff_list=staff_list,
        departments=departments,
        staff_count=staff_count,
        student_count=student_count,
        query=q,
    )


@app.route("/admin/student/delete/<sid>", methods=["POST"])
def admin_delete_student(sid):
    """sid = student Firestore doc ID (email)."""
    if not require_role("admin"):
        return redirect("/")
    fdb.delete_student_all(sid)
    logger.info(f"Admin deleted student: {sid}")
    return redirect("/admin")


@app.route("/admin/staff/delete/<sid>", methods=["POST"])
def admin_delete_staff(sid):
    """sid = staff user email."""
    if not require_role("admin"):
        return redirect("/")
    user = fdb.get_user(sid, role="staff")
    if user:
        fdb.delete_user(sid)
        logger.info(f"Admin deleted staff account: {sid}")
    return redirect("/admin")


@app.route("/admin/user/toggle_block/<uid>", methods=["POST"])
def admin_toggle_block(uid):
    """uid = user email."""
    if not require_role("admin"):
        return redirect("/")
    result = fdb.toggle_user_block(uid)
    status_text = "blocked" if result else "unblocked"
    logger.info(f"Admin {status_text} user: {uid}")
    return redirect("/admin")


# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK & ERROR HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/health")
def health_check():
    try:
        fdb.get_db()  # Will raise if Firebase isn't reachable
        return jsonify({"status": "healthy", "database": "firestore",
                        "timestamp": datetime.now().isoformat()}), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({"status": "unhealthy", "error": str(e),
                        "timestamp": datetime.now().isoformat()}), 503


@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal Server Error: {error}", exc_info=True)
    return render_template("error.html", error="Internal Server Error"), 500


@app.errorhandler(404)
def not_found(error):
    logger.warning(f"404 Not Found: {request.path}")
    return render_template("error.html", error="Page Not Found"), 404


@app.before_request
def log_request():
    if not request.path.startswith("/health"):
        logger.info(f"{request.method} {request.path}")


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
