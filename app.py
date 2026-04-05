from flask import Flask, render_template, request, redirect, session, jsonify
import sqlite3, json, os, logging
from datetime import date, datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

from werkzeug.utils import secure_filename
import requests, re
import google.generativeai as genai

# Configure logging for 24/7 operation
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "app.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dapi_secret_key_dev_only")
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads', 'certificates')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


# Database configuration
db_path = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db"))

# ------------- DB Functions ----------------
def get_db():
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        role TEXT NOT NULL,
        password_hash TEXT NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_email TEXT UNIQUE NOT NULL,

        student_id TEXT NOT NULL,
        roll TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        contact_email TEXT NOT NULL,

        phone TEXT NOT NULL,
        parent_phone TEXT NOT NULL,
        address TEXT NOT NULL,

        department TEXT NOT NULL,
        mentor_name TEXT NOT NULL,

        scholar_type TEXT NOT NULL DEFAULT 'Day Scholar',
        warden_name TEXT NOT NULL DEFAULT '',
        room_no TEXT NOT NULL DEFAULT '',

        tenth TEXT NOT NULL,
        twelfth TEXT NOT NULL,

        semester_start TEXT NOT NULL DEFAULT '2026-01-01',
        semester_end TEXT NOT NULL DEFAULT '2026-05-30',
        present_days INTEGER NOT NULL DEFAULT 0,
        arrear_count INTEGER NOT NULL DEFAULT 0,

        sem1 REAL, sem2 REAL, sem3 REAL, sem4 REAL,
        sem5 REAL, sem6 REAL, sem7 REAL, sem8 REAL,

        placement_score REAL NOT NULL DEFAULT 0,

        -- New Fields from Portal Redesign
        batch TEXT,
        enrollment_no TEXT,
        register_no TEXT,
        dte_umis_reg_no TEXT,
        application_no TEXT,
        admission_no TEXT,
        father_name TEXT,
        mother_name TEXT,
        gender TEXT,
        dob TEXT,
        community TEXT,
        religion TEXT,
        nationality TEXT,
        mother_tongue TEXT,
        blood_group TEXT,
        aadhar_no TEXT,
        parent_occupation TEXT,
        parent_income REAL,
        physics_marks REAL,
        chemistry_marks REAL,
        maths_marks REAL,
        cs_marks REAL,
        biology_marks REAL,
        fees_due REAL,
        ps_rank INTEGER,
        
        -- New Academic Fields
        hsc_cutoff REAL,
        school_name TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_email TEXT NOT NULL,
        skill_name TEXT NOT NULL,
        levels_completed INTEGER NOT NULL DEFAULT 0
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS achievements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_email TEXT NOT NULL,
        title TEXT NOT NULL,
        level TEXT,
        date_str TEXT,
        description TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS certifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_email TEXT NOT NULL,
        name TEXT NOT NULL,
        provider TEXT,
        issue_date TEXT,
        credential_url TEXT,
        file_path TEXT,
        status TEXT DEFAULT 'Pending'
    )
    """)

    conn.commit()
    
    # Migration: Add new columns if they don't exist
    for col in [
        ("hsc_cutoff", "REAL"),
        ("school_name", "TEXT"),
        ("semester_end", "TEXT DEFAULT '2026-05-30'"),
        ("leetcode_url", "TEXT"),
        ("github_url", "TEXT"),
        ("linkedin_url", "TEXT"),
        ("leetcode_solved", "INTEGER DEFAULT 0"),
        ("github_repos", "INTEGER DEFAULT 0"),
        ("assignments_score", "REAL DEFAULT 0.0"),
        ("participation_score", "REAL DEFAULT 0.0")
    ]:
        try:
            conn.execute(f"ALTER TABLE students ADD COLUMN {col[0]} {col[1]}")
        except:
            pass
            
    # Migration for users table
    try:
        conn.execute("ALTER TABLE users ADD COLUMN is_blocked INTEGER DEFAULT 0")
    except:
        pass
        
    # Ensure admin user exists
    admin_email = "aswinsuganth@gmail.com"
    admin_pass_hash = generate_password_hash("skp_aswin")
    
    admin_exists = conn.execute("SELECT 1 FROM users WHERE email=? AND role='admin'", (admin_email,)).fetchone()
    if not admin_exists:
        conn.execute("INSERT INTO users (email, role, password_hash) VALUES (?, 'admin', ?)", 
                     (admin_email, admin_pass_hash))
    
    conn.commit()
    conn.close()


init_db()


# ------------- helpers -------------
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

    total_days: int = college_working_days(start, date.today())
    present: int = int(student_row["present_days"] or 0)

    val: float = float(present) / float(total_days) * 100.0 if total_days > 0 else 0.0
    pct = 0.0 if total_days <= 0 else float(f"{val:.2f}")
    pct = max(0.0, min(100.0, pct))
    return total_days, present, pct


def calc_cgpa(student_row):
    sems: list[float] = []
    for k in ["sem1","sem2","sem3","sem4","sem5","sem6","sem7","sem8"]:
        v = student_row[k]
        if v is not None:
            try: sems.append(float(v))
            except: pass
    if not sems:
        return None
    
    avg: float = float(sum(sems))/len(sems)
    return float(f"{avg:.2f}")


def validate_email_role(email: str, role: str) -> bool:
    email = (email or "").strip().lower()
    if role == "admin":
        return email == "aswinsuganth@gmail.com"
    if role == "student":
        return email.endswith(".student@gmail.com")
    if role == "staff":
        return email.endswith(".staff@gmail.com")
    return False


def get_score_breakdown(conn, student_email: str, student_row):
    student_row = dict(student_row)
    
    # 1. Exams (40% mapped from CGPA)
    cgpa = calc_cgpa(student_row) or 0.0
    exam_points = (cgpa / 10.0) * 40.0
    
    # 2. Assignments (30% mapped from assignments_score)
    assign_score = safe_float(student_row.get("assignments_score", 0), 0.0)
    assignment_points = (assign_score / 100.0) * 30.0
    
    # 3. Attendance (20% mapped from attendance percentage)
    _, _, att_pct = calc_attendance(student_row)
    attendance_points = (att_pct / 100.0) * 20.0
    
    # 4. Participation (10% mapped from participation_score)
    part_score = safe_float(student_row.get("participation_score", 0), 0.0)
    participation_points = (part_score / 100.0) * 10.0
    
    # Arrears penalty (optional deduction outside the 100% scale)
    arrears = max(0, int(student_row.get("arrear_count", 0) or 0))
    penalty = min(40.0, arrears * 10.0)

    total = max(0.0, min(100.0, exam_points + assignment_points + attendance_points + participation_points - penalty))
    
    return {
        "exam_points": round(float(exam_points), 2),
        "assignment_points": round(float(assignment_points), 2),
        "attendance_points": round(float(attendance_points), 2),
        "participation_points": round(float(participation_points), 2),
        "penalty": round(float(penalty), 2),
        "total": round(float(total), 2)
    }

def calc_placement_score(conn, student_email: str, student_row):
    breakdown = get_score_breakdown(conn, student_email, student_row)
    return breakdown["total"]

def fetch_coding_stats(leetcode_url, github_url):
    lc_solved = 0
    gh_repos = 0
    
    # Try GitHub API (Public data)
    if github_url and "github.com/" in github_url:
        try:
            username = github_url.split("github.com/")[-1].strip("/")
            resp = requests.get(f"https://api.github.com/users/{username}", timeout=5)
            if resp.status_code == 200:
                gh_repos = resp.json().get("public_repos", 0)
        except: pass
        
    # Try LeetCode (Best effort scraping)
    if leetcode_url and "leetcode.com/" in leetcode_url:
        try:
            username = leetcode_url.split("u/")[-1].strip("/") if "u/" in leetcode_url else leetcode_url.split("leetcode.com/")[-1].strip("/")
            # Use a public API proxy if direct fails, or just direct
            resp = requests.get(f"https://leetcode-stats-api.herokuapp.com/{username}", timeout=5)
            if resp.status_code == 200:
                lc_solved = resp.json().get("totalSolved", 0)
        except: pass
        
    return lc_solved, gh_repos


def refresh_score(conn, student_email: str):
    student = conn.execute("SELECT * FROM students WHERE user_email=?", (student_email,)).fetchone()
    if not student:
        return
    score = calc_placement_score(conn, student_email, student)
    conn.execute("UPDATE students SET placement_score=? WHERE user_email=?", (score, student_email))
    conn.commit()


def generate_ai_feedback(student_row, score_breakdown):
    """
    Generates personalized AI feedback based on student metrics.
    Falls back to rule-based logic if Gemini API key is missing.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    
    # Ensure student_row is a dict for .get() support
    if not isinstance(student_row, dict):
        try:
            student_row = dict(student_row)
        except:
            pass

    # Extract key metrics
    cgpa = calc_cgpa(student_row) or 0.0
    _, _, att_pct = calc_attendance(student_row)
    arrears = int(student_row.get("arrear_count", 0) or 0)
    lc_solved = int(student_row.get("leetcode_solved", 0) or 0)
    gh_repos = int(student_row.get("github_repos", 0) or 0)
    total_score = score_breakdown.get('total', 0)
    
    # Category based on DAPI score
    if total_score < 50:
        status = "YOU NEED TO IMPROVE YOUR STUDIES"
    elif total_score < 80:
        status = "YOU NEED TO IMPROVE YOUR SKILLS"
    else:
        status = "YOUR DAPI SCORE IS ENOUGH. WELDONE!"

    # Basic context for the prompt
    context = f"""
    Student Name: {student_row['name']}
    CGPA: {cgpa}/10
    Attendance: {att_pct}%
    Arrears: {arrears}
    LeetCode Solved: {lc_solved}
    GitHub Repos: {gh_repos}
    Placement Score: {total_score}/100
    Determined status: {status}
    """

    if api_key:
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-1.5-flash')
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
            # Fall through to rule-based if API fails

    # Rule-based fallback
    tips = []
    if arrears > 0:
        tips.append(f"Clear your {arrears} arrears.")
    if att_pct < 75:
        tips.append("Improve attendance.")
    if cgpa < 7.0:
        tips.append("Boost CGPA.")
    if lc_solved < 50:
        tips.append("Practice on LeetCode.")
    if gh_repos < 3:
        tips.append("Build projects on GitHub.")
        
    feedback_msg = f"{status}. "
    if tips:
        feedback_msg += "Advice: " + " ".join(tips[:2])
    elif total_score >= 80:
        feedback_msg += "Keep maintaining your high standards!"
    
    return feedback_msg



def validate_profile_urls(lc, gh, li):
    errors = []
    # LeetCode Validation
    if lc:
        lc = lc.strip()
        if not re.match(r"^https?://(www\.)?leetcode\.com/(u/)?[\w-]+/?$", lc):
            errors.append("Invalid url please provide your profile link")
    
    # GitHub Validation
    if gh:
        gh = gh.strip()
        if not re.match(r"^https?://(www\.)?github\.com/[\w-]+/?$", gh):
            if "Invalid url please provide your profile link" not in errors:
                errors.append("Invalid url please provide your profile link")
            
    # LinkedIn Validation
    if li:
        li = li.strip()
        if not re.match(r"^https?://(www\.)?linkedin\.com/in/[\w-]+/?$", li):
            if "Invalid url please provide your profile link" not in errors:
                errors.append("Invalid url please provide your profile link")
            
    return errors


def require_role(role):
    return session.get("role") == role


# ---------------- AUTH ----------------
@app.route("/")
def index():
    if session.get("role"):
        return redirect("/student" if session["role"] == "student" else "/staff")
    return render_template("index.html")


@app.route("/login", methods=["GET","POST"])
def login():
    error = None
    if request.method == "POST":
        role = request.form.get("role","").strip()
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","").strip()

        if not role or not email or not password:
            return render_template("login.html", error="Please fill all fields")

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email=? AND role=?", (email, role)).fetchone()
        conn.close()

        if user and user["is_blocked"]:
            return render_template("login.html", error="Your account has been deactivated. Please contact the administrator.")

        if user is None or not check_password_hash(user["password_hash"], password):
            return render_template("login.html", error="Invalid email or password")

        session["role"] = role
        session["email"] = email

        if role == "admin":
            return redirect("/admin")
        return redirect("/student" if role == "student" else "/staff")

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/register/student", methods=["GET","POST"])
def register_student():
    if not require_role("staff"):
        return redirect("/")

    message = None
    error = None

    if request.method == "POST":
        login_email = request.form.get("login_email","").strip().lower()
        login_pass = request.form.get("login_pass","").strip()

        student_id = request.form.get("student_id","").strip()
        enrollment_no = request.form.get("enrollment_no","").strip()
        roll = request.form.get("roll","").strip()
        register_no = request.form.get("register_no","").strip()
        name = request.form.get("name","").strip()
        batch = request.form.get("batch","").strip()
        gender = request.form.get("gender","").strip()
        blood_group = request.form.get("blood_group","").strip()
        dob = request.form.get("dob","").strip()
        aadhar_no = request.form.get("aadhar_no","").strip()
        contact_email = request.form.get("contact_email","").strip().lower()

        phone = request.form.get("phone","").strip()
        father_name = request.form.get("father_name", "").strip()
        mother_name = request.form.get("mother_name", "").strip()
        parent_phone = request.form.get("parent_phone","").strip()
        parent_occupation = request.form.get("parent_occupation", "").strip()
        parent_income = safe_float(request.form.get("parent_income"), 0.0)
        mother_tongue = request.form.get("mother_tongue", "").strip()
        community = request.form.get("community", "").strip()
        religion = request.form.get("religion", "").strip()
        nationality = request.form.get("nationality", "INDIAN").strip()
        address = request.form.get("address","").strip()

        department = request.form.get("department","").strip()
        mentor_name = request.form.get("mentor_name","").strip()

        scholar_type = request.form.get("scholar_type","Day Scholar").strip()
        warden_name = request.form.get("warden_name","").strip()
        room_no = request.form.get("room_no","").strip()

        tenth = request.form.get("tenth","").strip()
        twelfth = request.form.get("twelfth","").strip()
        physics_marks = safe_float(request.form.get("physics_marks"), 0.0)
        chemistry_marks = safe_float(request.form.get("chemistry_marks"), 0.0)
        maths_marks = safe_float(request.form.get("maths_marks"), 0.0)
        cs_marks = safe_float(request.form.get("cs_marks"), 0.0)
        biology_marks = safe_float(request.form.get("biology_marks"), 0.0)

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
            
        semester_start = request.form.get("semester_start","").strip()
        present_days = safe_int(request.form.get("present_days"), 0)
        arrears = safe_int(request.form.get("arrear_count"), 0)
        
        dte_umis_reg_no = request.form.get("dte_umis_reg_no","").strip()
        application_no = request.form.get("application_no","").strip()
        admission_no = request.form.get("admission_no","").strip()
        
        school_name = request.form.get("school_name", "").strip()
        custom_dept = request.form.get("custom_department", "").strip()
        assignments_score = safe_float(request.form.get("assignments_score"), 0.0)
        participation_score = safe_float(request.form.get("participation_score"), 0.0)
        
        # New coding profiles
        leetcode_url = request.form.get("leetcode_url", "").strip()
        github_url = request.form.get("github_url", "").strip()
        linkedin_url = request.form.get("linkedin_url", "").strip()
        
        if department == "OTHER" and custom_dept:
            department = custom_dept
        department = department.upper()

        if not all([login_email, login_pass, student_id, roll, name, contact_email, phone, parent_phone,
                    address, department, mentor_name, tenth, twelfth, semester_start, batch, gender, dob]):
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

        sems = [safe_float(request.form.get(f"sem{i}")) for i in range(1,9)]

        ach_titles = request.form.getlist("ach_title[]")
        ach_levels = request.form.getlist("ach_level[]")
        ach_dates = request.form.getlist("ach_dates[]")
        ach_descs = request.form.getlist("ach_desc[]")

        skill_names = request.form.getlist("skill_name[]")
        skill_levels = request.form.getlist("skill_levels[]")

        cert_names = request.form.getlist("cert_name[]")
        cert_providers = request.form.getlist("cert_provider[]")
        cert_issue_dates = request.form.getlist("cert_issue_date[]")

        try:
            lc_solved, gh_repos = fetch_coding_stats(leetcode_url, github_url)
            
            conn = get_db()
            conn.execute(
                "INSERT INTO users(email, role, password_hash) VALUES(?, 'student', ?)",
                (login_email, generate_password_hash(login_pass))
            )
            conn.execute("""
                INSERT INTO students
                (user_email, student_id, roll, name, contact_email,
                 phone, parent_phone, address, department, mentor_name,
                 scholar_type, warden_name, room_no,
                 tenth, twelfth, semester_start, present_days, arrear_count,
                 sem1, sem2, sem3, sem4, sem5, sem6, sem7, sem8,
                 batch, enrollment_no, register_no, dte_umis_reg_no, application_no, admission_no,
                 gender, blood_group, dob, aadhar_no, father_name, mother_name, parent_occupation, parent_income,
                 mother_tongue, community, religion, nationality,
                 physics_marks, chemistry_marks, maths_marks, cs_marks, biology_marks,
                 hsc_cutoff, school_name,
                 leetcode_url, github_url, linkedin_url, leetcode_solved, github_repos, assignments_score, participation_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (login_email, student_id, roll, name, contact_email,
                  phone, parent_phone, address, department, mentor_name,
                  scholar_type, (warden_name if scholar_type=="Hosteller" else ""),
                  (room_no if scholar_type=="Hosteller" else ""),
                  tenth, twelfth, semester_start, max(0,present_days), max(0,arrears),
                  *sems,
                  batch, enrollment_no, register_no, dte_umis_reg_no, application_no, admission_no,
                  gender, blood_group, dob,
                  aadhar_no, father_name, mother_name, parent_occupation, parent_income,
                  mother_tongue, community, religion, nationality,
                  physics_marks, chemistry_marks, maths_marks, cs_marks, biology_marks,
                  hsc_cutoff, school_name,
                  leetcode_url, github_url, linkedin_url, lc_solved, gh_repos, assignments_score, participation_score))
            for idx, title in enumerate(ach_titles):
                title = (title or "").strip()
                if not title:
                    continue
                level = safe_int(ach_levels[idx] if idx < len(ach_levels) else None, 0)
                date_str = (ach_dates[idx] if idx < len(ach_dates) else "") or ""
                desc = (ach_descs[idx] if idx < len(ach_descs) else "") or ""
                conn.execute(
                    "INSERT INTO achievements(student_email, title, level, date_str, description) VALUES(?,?,?,?,?)",
                    (login_email, title, str(level), date_str, desc)
                )

            for idx, name in enumerate(skill_names):
                name = (name or "").strip()
                if not name:
                    continue
                levels = safe_int(skill_levels[idx] if idx < len(skill_levels) else None, 0)
                conn.execute(
                    "INSERT INTO skills(student_email, skill_name, levels_completed) VALUES(?,?,?)",
                    (login_email, name, levels)
                )

            for idx, name in enumerate(cert_names):
                name = (name or "").strip()
                if not name:
                    continue
                provider = (cert_providers[idx] if idx < len(cert_providers) else "") or ""
                issue_date = (cert_issue_dates[idx] if idx < len(cert_issue_dates) else "") or ""
                conn.execute(
                    "INSERT INTO certifications(student_email, name, provider, issue_date) VALUES(?,?,?,?)",
                    (login_email, name, provider, issue_date)
                )
            conn.commit()
            refresh_score(conn, login_email)
            message = "Student Registered Successfully ✅"
        except sqlite3.IntegrityError:
            error = "Email or Roll already exists"
        except Exception as e:
            error = f"Error: {e}"
        finally:
            if 'conn' in locals():
                conn.close()

    return render_template("register_student.html", message=message, error=error)


@app.route("/register/staff", methods=["GET","POST"])
def register_staff():
    if not require_role("admin"):
        return redirect("/")
    
    message = None
    error = None

    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","").strip()

        if not email or not password:
            return render_template("register_staff.html", message=None, error="Fill all fields")

        if not validate_email_role(email, "staff"):
            return render_template("register_staff.html", message=None, error='Staff email must be like "name".staff@gmail.com')

        try:
            conn = get_db()
            conn.execute(
                "INSERT INTO users(email, role, password_hash) VALUES(?, 'staff', ?)",
                (email, generate_password_hash(password))
            )
            conn.commit()
            message = "Staff Registered ✅ Now login!"
        except sqlite3.IntegrityError:
            error = "Staff email already exists"
        except Exception as e:
            error = f"Error: {e}"
        finally:
            if 'conn' in locals():
                conn.close()

    return render_template("register_staff.html", message=message, error=error)


# ---------------- STUDENT (ONE PAGE TABS) ----------------
@app.route("/student", methods=["GET","POST"])
def student_portal():
    if not require_role("student"):
        return redirect("/")

    tab = (request.args.get("tab") or "profile").strip()
    if tab in ["achievements", "certifications"]:
        tab = "awards"
    email = session.get("email")

    conn = get_db()
    student = conn.execute("SELECT * FROM students WHERE user_email=?", (email,)).fetchone()
    if not student:
        conn.close()
        return redirect("/register/student")

    message = None
    error = None

    # Redesign: Populate defaults for test student if data missing
    if student['batch'] is None:
        conn.execute("""
            UPDATE students SET 
                batch='2023', enrollment_no='2023UIT1076', register_no='7376232IT117',
                gender='MALE', nationality='INDIAN', physics_marks=89.0, chemistry_marks=93.0,
                maths_marks=87.0, cs_marks=94.0, fees_due=0.0, ps_rank=0
            WHERE user_email=?
        """, (email,))
        conn.commit()
        student = conn.execute("SELECT * FROM students WHERE user_email=?", (email,)).fetchone()

    if request.method == "POST":
        form_type = request.form.get("form_type","").strip()
        logger.info(f"POST /student with form_type='{form_type}'")

        # PROFILE UPDATE
        if form_type == "profile":
            logger.info("DEBUG: Profile update block TRIGGERED")
            error = "TRIGGER_MARKER"  # Force this into the HTML
            name = request.form.get("name","").strip()
            contact_email = request.form.get("contact_email","").strip().lower()
            phone = request.form.get("phone","").strip()
            parent_phone = request.form.get("parent_phone","").strip()
            address = request.form.get("address","").strip()
            department = request.form.get("department","").strip()
            mentor_name = request.form.get("mentor_name","").strip()

            scholar_type = request.form.get("scholar_type","Day Scholar").strip()
            warden_name = request.form.get("warden_name","").strip()
            room_no = request.form.get("room_no","").strip()
            
            # New Fields
            batch = request.form.get("batch","").strip()
            enroll_no = request.form.get("enrollment_no","").strip()
            reg_no = request.form.get("register_no","").strip()
            umis_no = request.form.get("dte_umis_reg_no","").strip()
            app_no = request.form.get("application_no","").strip()
            adm_no = request.form.get("admission_no","").strip()
            father = request.form.get("father_name","").strip()
            mother = request.form.get("mother_name","").strip()
            gender = request.form.get("gender","").strip()
            dob = request.form.get("dob","").strip()
            community = request.form.get("community","").strip()
            religion = request.form.get("religion","").strip()
            nationality = request.form.get("nationality","").strip()
            mother_tongue = request.form.get("mother_tongue","").strip()
            blood_group = request.form.get("blood_group","").strip()
            aadhar_no = request.form.get("aadhar_no","").strip()
            p_occ = request.form.get("parent_occupation","").strip()
            p_inc = safe_float(request.form.get("parent_income"), 0.0)
            
            # New coding profiles
            leetcode_url = request.form.get("leetcode_url", "").strip()
            github_url = request.form.get("github_url", "").strip()
            linkedin_url = request.form.get("linkedin_url", "").strip()
            logger.warning(f"URL DEBUG: lc='{leetcode_url}', gh='{github_url}', li='{linkedin_url}'")

            fields_to_check = [name, contact_email, phone, parent_phone, address, department, mentor_name]
            if not all(fields_to_check):
                missing = [k for k, v in zip(["name", "contact_email", "phone", "parent_phone", "address", "department", "mentor_name"], fields_to_check) if not v]
                error = "Fill all required fields"
                logger.warning(f"Profile update failed for {email}: Missing fields {missing}")
            else:
                url_errors = validate_profile_urls(leetcode_url, github_url, linkedin_url)
                if url_errors:
                    error = " | ".join(url_errors)
                    logger.warning(f"Validation failed for {email}: {error}")
                else:
                    lc_solved, gh_repos = fetch_coding_stats(leetcode_url, github_url)
                    
                    conn.execute("""
                        UPDATE students SET
                          name=?, contact_email=?, phone=?, parent_phone=?, address=?,
                          department=?, mentor_name=?, scholar_type=?, warden_name=?, room_no=?,
                          batch=?, enrollment_no=?, register_no=?, dte_umis_reg_no=?, 
                          application_no=?, admission_no=?, father_name=?, mother_name=?,
                          gender=?, dob=?, community=?, religion=?, nationality=?,
                          mother_tongue=?, blood_group=?, aadhar_no=?, parent_occupation=?,
                          parent_income=?,
                          leetcode_url=?, github_url=?, linkedin_url=?, 
                          leetcode_solved=?, github_repos=?
                        WHERE user_email=?
                    """, (name, contact_email, phone, parent_phone, address,
                          department, mentor_name, scholar_type,
                          (warden_name if scholar_type=="Hosteller" else ""),
                          (room_no if scholar_type=="Hosteller" else ""),
                          batch, enroll_no, reg_no, umis_no, app_no, adm_no,
                          father, mother, gender, dob, community, religion,
                          nationality, mother_tongue, blood_group, aadhar_no,
                          p_occ, p_inc,
                          leetcode_url, github_url, linkedin_url,
                          lc_solved, gh_repos,
                          email))
                    conn.commit()
                    message = "Profile & Professional Links updated ✅"

        # ACADEMICS UPDATE
        elif form_type == "academics":
            semester_start = request.form.get("semester_start","").strip()
            present_days = max(0, safe_int(request.form.get("present_days"), 0))
            arrears = max(0, safe_int(request.form.get("arrear_count"), 0))
            sems = [safe_float(request.form.get(f"sem{i}")) for i in range(1,9)]
            
            # School marks
            p_marks = safe_float(request.form.get("physics_marks"), 0.0)
            c_marks = safe_float(request.form.get("chemistry_marks"), 0.0)
            m_marks = safe_float(request.form.get("maths_marks"), 0.0)
            cs_marks = safe_float(request.form.get("cs_marks"), 0.0)
            b_marks = safe_float(request.form.get("biology_marks"), 0.0)
            
            assignments_score = safe_float(request.form.get("assignments_score"), 0.0)
            participation_score = safe_float(request.form.get("participation_score"), 0.0)

            try:
                parse_ymd(semester_start)
            except:
                error = "Semester Start must be YYYY-MM-DD"

            if error is None:
                conn.execute("""
                    UPDATE students SET
                      semester_start=?, present_days=?, arrear_count=?,
                      sem1=?, sem2=?, sem3=?, sem4=?, sem5=?, sem6=?, sem7=?, sem8=?,
                      physics_marks=?, chemistry_marks=?, maths_marks=?, cs_marks=?, biology_marks=?,
                      assignments_score=?, participation_score=?
                    WHERE user_email=?
                """, (semester_start, present_days, arrears, *sems, 
                      p_marks, c_marks, m_marks, cs_marks, b_marks,
                      assignments_score, participation_score, email))
                conn.commit()
                refresh_score(conn, email)
                message = "Academic records calibrated! ✅"

        # SKILL ADD/DELETE
        elif form_type == "skill_add":
            skill_name = request.form.get("skill_name","").strip()
            levels = max(0, min(10, safe_int(request.form.get("levels_completed"), 0)))
            if not skill_name:
                error = "Skill name required"
            else:
                conn.execute(
                    "INSERT INTO skills(student_email, skill_name, levels_completed) VALUES(?,?,?)",
                    (email, skill_name, levels)
                )
                conn.commit()
                refresh_score(conn, email)
                message = "Skill added ✅"

        elif form_type == "skill_delete":
            sid = safe_int(request.form.get("id"), 0)
            conn.execute("DELETE FROM skills WHERE id=? AND student_email=?", (sid, email))
            conn.commit()
            refresh_score(conn, email)
            message = "Skill deleted ✅"

        # ACH / CERT add/delete
        elif form_type == "ach_add":
            title = request.form.get("title","").strip()
            if not title:
                error = "Achievement title required"
            else:
                conn.execute("""
                    INSERT INTO achievements(student_email, title, level, date_str, description)
                    VALUES(?,?,?,?,?)
                """, (email, title,
                      request.form.get("level","").strip(),
                      request.form.get("date_str","").strip(),
                      request.form.get("description","").strip()))
                conn.commit()
                refresh_score(conn, email)
                message = "Achievement added ✅"

        elif form_type == "ach_delete":
            aid = safe_int(request.form.get("id"), 0)
            conn.execute("DELETE FROM achievements WHERE id=? AND student_email=?", (aid, email))
            conn.commit()
            refresh_score(conn, email)
            message = "Achievement deleted ✅"

        elif form_type == "cert_add":
            name = request.form.get("name","").strip()
            provider = request.form.get("provider","").strip()
            issue_date = request.form.get("issue_date","").strip()
            credential_url = request.form.get("credential_url","").strip()
            
            file = request.files.get("cert_file")
            file_path = None
            
            if not name:
                error = "Certification name required"
            else:
                if file and file.filename != "":
                    filename = secure_filename(f"{email}_{datetime.now().timestamp()}_{file.filename}")
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    file_path = f"uploads/certificates/{filename}"

                conn.execute("""
                    INSERT INTO certifications(student_email, name, provider, issue_date, credential_url, file_path, status)
                    VALUES(?,?,?,?,?,?,?)
                """, (email, name, provider, issue_date, credential_url, file_path, 'Pending'))
                conn.commit()
                refresh_score(conn, email)
                message = "Certification added (Pending Verification) ✅"

        elif form_type == "cert_delete":
            cid = safe_int(request.form.get("id"), 0)
            conn.execute("DELETE FROM certifications WHERE id=? AND student_email=?", (cid, email))
            conn.commit()
            refresh_score(conn, email)
            message = "Certification deleted ✅"

    # reload student after updates
    student = conn.execute("SELECT * FROM students WHERE user_email=?", (email,)).fetchone()

    total_days, present, attendance_pct = calc_attendance(student)
    cgpa = calc_cgpa(student)

    sgpas = [(student[f"sem{i}"] if student[f"sem{i}"] is not None else None) for i in range(1,9)]

    skills = conn.execute(
        "SELECT * FROM skills WHERE student_email=? ORDER BY id DESC",
        (email,)
    ).fetchall()

    achievements = conn.execute(
        "SELECT * FROM achievements WHERE student_email=? ORDER BY id DESC",
        (email,)
    ).fetchall()

    certs = conn.execute(
        "SELECT * FROM certifications WHERE student_email=? ORDER BY id DESC",
        (email,)
    ).fetchall()

    breakdown = get_score_breakdown(conn, email, student)
    
    # Ensure we use a dict for the AI function
    student_dict = dict(student) if not isinstance(student, dict) else student
    
    try:
        ai_message = generate_ai_feedback(student_dict, breakdown)
        if not ai_message:
            ai_message = "Your academic journey is unique. Stay focused on your goals!"
    except Exception as e:
        logger.error(f"AI Feedback failed: {e}")
        ai_message = "Keep pushing your limits and refine your technical skills every day."
    
    # DEFINITIVE DEBUG:
    print(f"\n[DEBUG] FINAL AI MESSAGE: '{ai_message}'\n")
    
    conn.close()

    return render_template(
        "student_portal.html",
        tab=tab,
        student=student,
        message=message,
        error=error,
        total_days=total_days,
        present=present,
        attendance_pct=attendance_pct,
        cgpa=cgpa,
        score=student["placement_score"],
        sgpas=sgpas,
        skills=skills,
        achievements=achievements,
        certs=certs,
        breakdown=breakdown,
        ai_message=ai_message
    )


@app.route("/achievements")
def achievements_page():
    if not require_role("student"):
        return redirect("/")
    return redirect("/student?tab=awards")


@app.route("/certifications")
def certifications_page():
    if not require_role("student"):
        return redirect("/")
    return redirect("/student?tab=awards")


# ---------------- STAFF ----------------
@app.route("/staff", methods=["GET","POST"])
def staff_dashboard():
    if not require_role("staff"):
        return redirect("/")

    q = (request.form.get("query","") if request.method=="POST" else request.args.get("query","")).strip()

    conn = get_db()
    if q:
        like = f"%{q}%"
        students = conn.execute("""
            SELECT * FROM students
            WHERE roll LIKE ? OR name LIKE ? OR student_id LIKE ? OR user_email LIKE ? OR department LIKE ?
            ORDER BY department ASC, id DESC
        """, (like, like, like, like, like)).fetchall()
    else:
        students = conn.execute("SELECT * FROM students ORDER BY department ASC, id DESC").fetchall()
    conn.close()

    # group by department — normalize to uppercase to avoid duplicate tabs from case differences
    dept_map: dict = {}
    for row in students:
        s = dict(row)
        dept = (s["department"] or "Unknown").strip().upper()
        _, _, attendance_pct = calc_attendance(s)
        s["attendance_pct"] = attendance_pct
        
        if dept not in dept_map:
            dept_map[dept] = []
        dept_map[dept].append(s)

    return render_template("staff_dashboard.html", dept_map=dept_map, query=q)


@app.route("/staff/student/<int:sid>", methods=["GET","POST"])
def staff_student_portal(sid):
    if not require_role("staff"):
        return redirect("/")

    tab = (request.form.get("tab") or request.args.get("tab") or "profile").strip()
    if tab in ["achievements", "certifications"]:
        tab = "awards"

    conn = get_db()
    student = conn.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
    if not student:
        conn.close()
        return "Student not found", 404

    message = None
    error = None

    # STAFF EDIT (profile+academics in one form)
    if request.method == "POST":
        form_type = request.form.get("form_type","").strip()

        if form_type == "edit":
            name = request.form.get("name","").strip()
            contact_email = request.form.get("contact_email","").strip().lower()
            phone = request.form.get("phone","").strip()
            parent_phone = request.form.get("parent_phone","").strip()
            address = request.form.get("address","").strip()
            
            # New fields from redesign integration
            batch = request.form.get("batch","").strip()
            dob = request.form.get("dob","").strip()
            gender = request.form.get("gender","").strip()
            community = request.form.get("community","").strip()
            religion = request.form.get("religion","").strip()
            nationality = request.form.get("nationality","INDIAN").strip()
            mother_tongue = request.form.get("mother_tongue","").strip()
            blood_group = request.form.get("blood_group","").strip()
            enrollment_no = request.form.get("enrollment_no","").strip()
            register_no = request.form.get("register_no","").strip()
            dte_umis_reg_no = request.form.get("dte_umis_reg_no","").strip()
            application_no = request.form.get("application_no","").strip()
            admission_no = request.form.get("admission_no","").strip()
            father_name = request.form.get("father_name","").strip()
            mother_name = request.form.get("mother_name","").strip()
            aadhar_no = request.form.get("aadhar_no","").strip()
            parent_occupation = request.form.get("parent_occupation","").strip()
            parent_income = safe_float(request.form.get("parent_income"), 0.0)

            semester_start = request.form.get("semester_start","").strip()
            semester_end = request.form.get("semester_end","").strip()
            present_days = max(0, safe_int(request.form.get("present_days"), 0))
            arrears = max(0, safe_int(request.form.get("arrear_count"), 0))
            sems = [safe_float(request.form.get(f"sem{i}")) for i in range(1,9)]

            p_marks = safe_float(request.form.get("physics_marks"), 0.0)
            c_marks = safe_float(request.form.get("chemistry_marks"), 0.0)
            m_marks = safe_float(request.form.get("maths_marks"), 0.0)
            cs_marks = safe_float(request.form.get("cs_marks"), 0.0)
            b_marks = safe_float(request.form.get("biology_marks"), 0.0)
            
            third_sub = c_marks
            if cs_marks > 0:
                third_sub = cs_marks
            elif b_marks > 0:
                third_sub = b_marks

            hsc_cutoff_str = request.form.get("hsc_cutoff", "").strip()
            if not hsc_cutoff_str and (p_marks > 0 or third_sub > 0 or m_marks > 0):
                hsc_cutoff = round(m_marks + (p_marks / 2.0) + (third_sub / 2.0), 2)
            else:
                hsc_cutoff = safe_float(hsc_cutoff_str, 0.0)
                
            school_name = request.form.get("school_name", "").strip()

            assignments_score = safe_float(request.form.get("assignments_score"), 0.0)
            participation_score = safe_float(request.form.get("participation_score"), 0.0)

            department = request.form.get("department", student["department"]).strip().upper()
            mentor_name = request.form.get("mentor_name", student["mentor_name"]).strip()
            scholar_type = request.form.get("scholar_type", student["scholar_type"]).strip()
            warden_name = request.form.get("warden_name","").strip()
            room_no = request.form.get("room_no","").strip()

            if not all([name, contact_email, phone, parent_phone, address, semester_start]):
                error = "Fill all required fields"
            else:
                try:
                    parse_ymd(semester_start)
                except:
                    error = "Semester Start must be YYYY-MM-DD"

            if scholar_type == "Hosteller" and (not warden_name or not room_no):
                error = "If Hosteller: warden name + room no required"

            if error is None:
                conn.execute("""
                    UPDATE students SET
                      name=?, contact_email=?, phone=?, parent_phone=?, address=?,
                      department=?, mentor_name=?, scholar_type=?, warden_name=?, room_no=?,
                      batch=?, dob=?, gender=?, community=?, religion=?, nationality=?, 
                      mother_tongue=?, blood_group=?, enrollment_no=?, register_no=?, roll=?,
                      dte_umis_reg_no=?, application_no=?, admission_no=?,
                      father_name=?, mother_name=?, aadhar_no=?, parent_occupation=?, parent_income=?,
                      semester_start=?, present_days=?, arrear_count=?,
                      physics_marks=?, chemistry_marks=?, maths_marks=?, cs_marks=?, biology_marks=?,
                      hsc_cutoff=?, school_name=?,
                      assignments_score=?, participation_score=?,
                      sem1=?, sem2=?, sem3=?, sem4=?, sem5=?, sem6=?, sem7=?, sem8=?
                     WHERE id=?
                """, (name, contact_email, phone, parent_phone, address,
                      department, mentor_name, scholar_type,
                      (warden_name if scholar_type=="Hosteller" else ""),
                      (room_no if scholar_type=="Hosteller" else ""),
                      batch, dob, gender, community, religion, nationality,
                      mother_tongue, blood_group, enrollment_no, register_no, request.form.get("roll","").strip(),
                      dte_umis_reg_no, application_no, admission_no,
                      father_name, mother_name, aadhar_no, parent_occupation, parent_income,
                      semester_start, present_days, arrears,
                      p_marks, c_marks, m_marks, cs_marks, b_marks,
                      hsc_cutoff, school_name,
                      assignments_score, participation_score,
                      *sems, sid))
                conn.commit()
                refresh_score(conn, student["user_email"])
                message = "Student records synchronized! ✅"

        # Staff can manage skills too
        elif form_type == "skill_add":
            skill_name = request.form.get("skill_name","").strip()
            levels = max(0, min(10, safe_int(request.form.get("levels_completed"), 0)))
            if not skill_name:
                error = "Skill name required"
            else:
                conn.execute("INSERT INTO skills(student_email, skill_name, levels_completed) VALUES(?,?,?)",
                             (student["user_email"], skill_name, levels))
                conn.commit()
                refresh_score(conn, student["user_email"])
                message = "Skill added ✅"

        elif form_type == "skill_edit":
            sid_skill = safe_int(request.form.get("id"), 0)
            skill_name = request.form.get("skill_name","").strip()
            levels = max(0, min(10, safe_int(request.form.get("levels_completed"), 0)))
            if not skill_name:
                error = "Skill name required"
            else:
                conn.execute("UPDATE skills SET skill_name=?, levels_completed=? WHERE id=? AND student_email=?",
                             (skill_name, levels, sid_skill, student["user_email"]))
                conn.commit()
                refresh_score(conn, student["user_email"])
                message = "Skill updated ✅"

        elif form_type == "skill_delete":
            sid_skill = safe_int(request.form.get("id"), 0)
            conn.execute("DELETE FROM skills WHERE id=? AND student_email=?",
                         (sid_skill, student["user_email"]))
            conn.commit()
            refresh_score(conn, student["user_email"])
            message = "Skill deleted ✅"

        elif form_type == "achievement_add":
            title = request.form.get("title","").strip()
            level = request.form.get("level","").strip()
            date_str = request.form.get("date_str","").strip()
            if not title:
                error = "Achievement title required"
            else:
                if date_str:
                    try:
                        parse_ymd(date_str)
                    except:
                        error = "Achievement date must be YYYY-MM-DD"
                if error is None:
                    conn.execute(
                        "INSERT INTO achievements (student_email, title, level, date_str) VALUES (?,?,?,?)",
                        (student["user_email"], title, level, date_str or None)
                    )
                    conn.commit()
                    refresh_score(conn, student["user_email"])
                    message = "Achievement added ✅"

        elif form_type == "achievement_edit":
            aid = safe_int(request.form.get("id"), 0)
            title = request.form.get("title","").strip()
            level = request.form.get("level","").strip()
            date_str = request.form.get("date_str","").strip()
            if not title:
                error = "Achievement title required"
            else:
                if date_str:
                    try:
                        parse_ymd(date_str)
                    except:
                        error = "Achievement date must be YYYY-MM-DD"
                if error is None:
                    conn.execute(
                        "UPDATE achievements SET title=?, level=?, date_str=? WHERE id=? AND student_email=?",
                        (title, level, date_str or None, aid, student["user_email"])
                    )
                    conn.commit()
                    refresh_score(conn, student["user_email"])
                    message = "Achievement updated ✅"

        elif form_type == "achievement_delete":
            aid = safe_int(request.form.get("id"), 0)
            conn.execute("DELETE FROM achievements WHERE id=? AND student_email=?",
                         (aid, student["user_email"]))
            conn.commit()
            refresh_score(conn, student["user_email"])
            message = "Achievement deleted ✅"

        elif form_type == "cert_add":
            name = request.form.get("name","").strip()
            provider = request.form.get("provider","").strip()
            issue_date = request.form.get("issue_date","").strip()
            credential_url = request.form.get("credential_url","").strip()
            
            file = request.files.get("cert_file")
            file_path = None
            
            if not name:
                error = "Certification name required"
            else:
                if file and file.filename != "":
                    filename = secure_filename(f"{student['user_email']}_{datetime.now().timestamp()}_{file.filename}")
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    file_path = f"uploads/certificates/{filename}"

                conn.execute("""
                    INSERT INTO certifications(student_email, name, provider, issue_date, credential_url, file_path, status)
                    VALUES(?,?,?,?,?,?,?)
                """, (student["user_email"], name, provider, issue_date, credential_url, file_path, 'Verified'))
                conn.commit()
                refresh_score(conn, student["user_email"])
                message = "Certification added & verified ✅"

        elif form_type == "cert_edit":
            cid = safe_int(request.form.get("id"), 0)
            name = request.form.get("name","").strip()
            provider = request.form.get("provider","").strip()
            issue_date = request.form.get("issue_date","").strip()
            if not name:
                error = "Certification name required"
            else:
                if issue_date:
                    try:
                        parse_ymd(issue_date)
                    except:
                        error = "Certification date must be YYYY-MM-DD"
                if error is None:
                    conn.execute(
                        "UPDATE certifications SET name=?, provider=?, issue_date=? WHERE id=? AND student_email=?",
                        (name, provider, issue_date or None, cid, student["user_email"])
                    )
                    conn.commit()
                    refresh_score(conn, student["user_email"])
                    message = "Certification updated ✅"

        elif form_type == "cert_delete":
            cid = safe_int(request.form.get("id"), 0)
            conn.execute("DELETE FROM certifications WHERE id=? AND student_email=?",
                         (cid, student["user_email"]))
            conn.commit()
            refresh_score(conn, student["user_email"])
            message = "Certification deleted ✅"

        elif form_type == "cert_verify":
            cid = safe_int(request.form.get("id"), 0)
            status = request.form.get("status", "Verified")
            conn.execute("UPDATE certifications SET status=? WHERE id=?", (status, cid))
            conn.commit()
            refresh_score(conn, student["user_email"])
            message = f"Certification {status} ✅"

    # reload
    student = conn.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
    total_days, present, attendance_pct = calc_attendance(student)
    cgpa = calc_cgpa(student)
    sgpas = [(student[f"sem{i}"] if student[f"sem{i}"] is not None else None) for i in range(1,9)]

    skills = conn.execute("SELECT * FROM skills WHERE student_email=? ORDER BY id DESC",
                          (student["user_email"],)).fetchall()

    achievements = conn.execute("SELECT * FROM achievements WHERE student_email=? ORDER BY id DESC",
                                (student["user_email"],)).fetchall()

    certs = conn.execute("SELECT * FROM certifications WHERE student_email=? ORDER BY id DESC",
                         (student["user_email"],)).fetchall()

    breakdown = get_score_breakdown(conn, student["user_email"], student)
    # AI Feedback for staff oversight
    s_dict = dict(student) if not isinstance(student, dict) else student
    try:
        ai_message = generate_ai_feedback(s_dict, breakdown)
    except:
        ai_message = "Consistent academic effort."
    conn.close()

    return render_template(
        "staff_student_portal.html",
        tab=tab,
        student=student,
        message=message,
        error=error,
        total_days=total_days,
        present=present,
        attendance_pct=attendance_pct,
        cgpa=cgpa,
        score=student["placement_score"],
        breakdown=breakdown,
        sgpas=sgpas,
        skills=skills,
        achievements=achievements,
        certs=certs,
        ai_message=ai_message
    )


# -------- HEALTH CHECK & MONITORING (24/7) --------
@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint for monitoring and load balancers"""
    try:
        conn = get_db()
        conn.execute("SELECT 1")
        conn.close()
        logger.info("Health check passed")
        return jsonify({"status": "healthy", "database": "connected", "timestamp": datetime.now().isoformat()}), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({"status": "unhealthy", "error": str(e), "timestamp": datetime.now().isoformat()}), 503


@app.errorhandler(500)
def internal_error(error):
    """Log and handle internal server errors gracefully"""
    logger.error(f"Internal Server Error: {error}", exc_info=True)
    return render_template("error.html", error="Internal Server Error"), 500


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    logger.warning(f"404 Not Found: {request.path}")
    return render_template("error.html", error="Page Not Found"), 404


@app.before_request
def log_request():
    """Log incoming requests for monitoring"""
    if not request.path.startswith("/health"):
        logger.info(f"{request.method} {request.path}")


# ---------------- ADMIN ----------------
@app.route("/admin", methods=["GET","POST"])
def admin_dashboard():
    if not require_role("admin"):
        return redirect("/")

    q = (request.form.get("query","") if request.method=="POST" else request.args.get("query","")).strip()
    conn = get_db()
    
    if q:
        like = f"%{q}%"
        # Fetch filtered staff
        staff_list = conn.execute("""
            SELECT id, email, role, is_blocked 
            FROM users 
            WHERE role='staff' AND email LIKE ? 
            ORDER BY id DESC
        """, (like,)).fetchall()
        
        # Fetch filtered students
        students_data = conn.execute("""
            SELECT s.*, u.id as user_id, u.is_blocked 
            FROM students s 
            JOIN users u ON s.user_email = u.email 
            WHERE s.name LIKE ? OR s.roll LIKE ? OR s.user_email LIKE ? OR s.department LIKE ?
            ORDER BY s.department ASC, s.name ASC
        """, (like, like, like, like)).fetchall()
    else:
        # Fetch all staff with block status
        staff_list = conn.execute("SELECT id, email, role, is_blocked FROM users WHERE role='staff' ORDER BY id DESC").fetchall()
        
        # Fetch all students with their user block status
        students_data = conn.execute("""
            SELECT s.*, u.id as user_id, u.is_blocked 
            FROM students s 
            JOIN users u ON s.user_email = u.email 
            ORDER BY s.department ASC, s.name ASC
        """).fetchall()
    
    # Group students by department — normalize to uppercase to avoid duplicate tabs from case differences
    departments = {}
    for s in students_data:
        dept = (s["department"] or "UNASSIGNED").strip().upper()
        if dept not in departments:
            departments[dept] = []
        departments[dept].append(s)
    
    # Filtered Stats
    staff_count = len(staff_list)
    student_count = len(students_data)
    
    conn.close()
    
    return render_template(
        "admin_dashboard.html",
        staff_list=staff_list,
        departments=departments,
        staff_count=staff_count,
        student_count=student_count,
        query=q
    )

@app.route("/admin/student/delete/<int:sid>", methods=["POST"])
def admin_delete_student(sid):
    if not require_role("admin"):
        return redirect("/")
        
    conn = get_db()
    student = conn.execute("SELECT user_email FROM students WHERE id=?", (sid,)).fetchone()
    if student:
        email = student["user_email"]
        # Remove from all related tables
        conn.execute("DELETE FROM users WHERE email=?", (email,))
        conn.execute("DELETE FROM students WHERE id=?", (sid,))
        conn.execute("DELETE FROM skills WHERE student_email=?", (email,))
        conn.execute("DELETE FROM achievements WHERE student_email=?", (email,))
        conn.execute("DELETE FROM certifications WHERE student_email=?", (email,))
        conn.commit()
        logger.info(f"Admin deleted student account and all records: {email}")
    conn.close()
    return redirect("/admin")

@app.route("/admin/staff/delete/<int:uid>", methods=["POST"])
def admin_delete_staff(uid):
    if not require_role("admin"):
        return redirect("/")
        
    conn = get_db()
    # Find the staff email first because they might have other related records (though currently only users table)
    user = conn.execute("SELECT email FROM users WHERE id=? AND role='staff'", (uid,)).fetchone()
    if user:
        conn.execute("DELETE FROM users WHERE id=?", (uid,))
        conn.commit()
        logger.info(f"Admin deleted staff account: {user['email']}")
    conn.close()
    return redirect("/admin")

@app.route("/admin/user/toggle_block/<int:uid>", methods=["POST"])
def admin_toggle_block(uid):
    if not require_role("admin"):
        return redirect("/")
        
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if user:
        if user["role"] == "admin":
            # Cannot block admin
            pass
        else:
            new_status = 1 if not user["is_blocked"] else 0
            conn.execute("UPDATE users SET is_blocked=? WHERE id=?", (new_status, uid))
            conn.commit()
            status_text = "blocked" if new_status else "unblocked"
            logger.info(f"Admin {status_text} user: {user['email']}")
    conn.close()
    return redirect("/admin")


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
