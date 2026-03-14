from flask import Flask, render_template, request, redirect, session, jsonify
import sqlite3, json, os, logging
from datetime import date, datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

from werkzeug.utils import secure_filename

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
    try:
        conn.execute("ALTER TABLE students ADD COLUMN hsc_cutoff REAL")
    except: pass
    try:
        conn.execute("ALTER TABLE students ADD COLUMN school_name TEXT")
    except: pass
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
    if role == "student":
        return email.endswith(".student@gmail.com")
    if role == "staff":
        return email.endswith(".staff@gmail.com")
    return False


def get_score_breakdown(conn, student_email: str, student_row):
    # CGPA up to 50
    cg = calc_cgpa(student_row) or 0.0
    cg_part = (cg / 10.0) * 50.0

    # Skills up to 30 (total levels)
    skill_total = conn.execute(
        "SELECT COALESCE(SUM(levels_completed),0) AS s FROM skills WHERE student_email=?",
        (student_email,)
    ).fetchone()["s"]
    skill_part = min(30.0, (skill_total / 100.0) * 30.0)

    # Achievements up to 10
    ach_count = conn.execute(
        "SELECT COUNT(*) AS c FROM achievements WHERE student_email=?",
        (student_email,)
    ).fetchone()["c"]
    ach_part = min(10.0, ach_count * 2.5)

    # Certifications up to 10
    cert_count = conn.execute(
        "SELECT COUNT(*) AS c FROM certifications WHERE student_email=? AND status='Verified'",
        (student_email,)
    ).fetchone()["c"]
    cert_part = min(10.0, cert_count * 2.0)

    # Arrears penalty
    arrears = max(0, int(student_row["arrear_count"] or 0))
    penalty = min(40.0, arrears * 10.0)

    total = max(0.0, min(100.0, cg_part + skill_part + ach_part + cert_part - penalty))
    
    return {
        "cgpa_points": round(cg_part, 2),
        "skill_points": round(skill_part, 2),
        "ach_points": round(ach_part, 2),
        "cert_points": round(cert_part, 2),
        "penalty": round(penalty, 2),
        "total": round(total, 2)
    }

def calc_placement_score(conn, student_email: str, student_row):
    breakdown = get_score_breakdown(conn, student_email, student_row)
    return breakdown["total"]


def refresh_score(conn, student_email: str):
    student = conn.execute("SELECT * FROM students WHERE user_email=?", (student_email,)).fetchone()
    if not student:
        return
    score = calc_placement_score(conn, student_email, student)
    conn.execute("UPDATE students SET placement_score=? WHERE user_email=?", (score, student_email))
    conn.commit()


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

        if user is None or not check_password_hash(user["password_hash"], password):
            return render_template("login.html", error="Invalid email or password")

        session["role"] = role
        session["email"] = email

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

        semester_start = request.form.get("semester_start","").strip()
        present_days = safe_int(request.form.get("present_days"), 0)
        arrears = safe_int(request.form.get("arrear_count"), 0)
        
        dte_umis_reg_no = request.form.get("dte_umis_reg_no","").strip()
        application_no = request.form.get("application_no","").strip()
        admission_no = request.form.get("admission_no","").strip()
        
        hsc_cutoff = safe_float(request.form.get("hsc_cutoff"), 0.0)
        school_name = request.form.get("school_name", "").strip()
        custom_dept = request.form.get("custom_department", "").strip()
        
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
                 hsc_cutoff, school_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                  hsc_cutoff, school_name))
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

        # PROFILE UPDATE
        if form_type == "profile":
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

            if not all([name, contact_email, phone, parent_phone, address, department, mentor_name]):
                error = "Fill all required fields"
            else:
                conn.execute("""
                    UPDATE students SET
                      name=?, contact_email=?, phone=?, parent_phone=?, address=?,
                      department=?, mentor_name=?, scholar_type=?, warden_name=?, room_no=?,
                      batch=?, enrollment_no=?, register_no=?, dte_umis_reg_no=?, 
                      application_no=?, admission_no=?, father_name=?, mother_name=?,
                      gender=?, dob=?, community=?, religion=?, nationality=?,
                      mother_tongue=?, blood_group=?, aadhar_no=?, parent_occupation=?,
                      parent_income=?
                    WHERE user_email=?
                """, (name, contact_email, phone, parent_phone, address,
                      department, mentor_name, scholar_type,
                      (warden_name if scholar_type=="Hosteller" else ""),
                      (room_no if scholar_type=="Hosteller" else ""),
                      batch, enroll_no, reg_no, umis_no, app_no, adm_no,
                      father, mother, gender, dob, community, religion,
                      nationality, mother_tongue, blood_group, aadhar_no,
                      p_occ, p_inc, email))
                conn.commit()
                message = "Profile updated ✅"

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

            try:
                parse_ymd(semester_start)
            except:
                error = "Semester Start must be YYYY-MM-DD"

            if error is None:
                conn.execute("""
                    UPDATE students SET
                      semester_start=?, present_days=?, arrear_count=?,
                      sem1=?, sem2=?, sem3=?, sem4=?, sem5=?, sem6=?, sem7=?, sem8=?,
                      physics_marks=?, chemistry_marks=?, maths_marks=?, cs_marks=?, biology_marks=?
                    WHERE user_email=?
                """, (semester_start, present_days, arrears, *sems, 
                      p_marks, c_marks, m_marks, cs_marks, b_marks, email))
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
        certs=certs
    )


@app.route("/achievements")
def achievements_page():
    if not require_role("student"):
        return redirect("/")
    return redirect("/student?tab=achievements")


@app.route("/certifications")
def certifications_page():
    if not require_role("student"):
        return redirect("/")
    return redirect("/student?tab=certifications")


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

    # group by department
    dept_map: dict = {}
    for s in students:
        dept = s["department"] or "Unknown"
        if dept not in dept_map:
            dept_map[dept] = []
        dept_map[dept].append(s)

    return render_template("staff_dashboard.html", dept_map=dept_map, query=q)


@app.route("/staff/student/<int:sid>", methods=["GET","POST"])
def staff_student_portal(sid):
    if not require_role("staff"):
        return redirect("/")

    tab = (request.form.get("tab") or request.args.get("tab") or "profile").strip()

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
            present_days = max(0, safe_int(request.form.get("present_days"), 0))
            arrears = max(0, safe_int(request.form.get("arrear_count"), 0))
            sems = [safe_float(request.form.get(f"sem{i}")) for i in range(1,9)]

            p_marks = safe_float(request.form.get("physics_marks"), 0.0)
            c_marks = safe_float(request.form.get("chemistry_marks"), 0.0)
            m_marks = safe_float(request.form.get("maths_marks"), 0.0)
            cs_marks = safe_float(request.form.get("cs_marks"), 0.0)
            b_marks = safe_float(request.form.get("biology_marks"), 0.0)
            hsc_cutoff = safe_float(request.form.get("hsc_cutoff"), 0.0)
            school_name = request.form.get("school_name", "").strip()

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
        certs=certs
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


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
