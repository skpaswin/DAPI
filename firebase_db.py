"""
firebase_db.py — Firestore data layer for DAPI
================================================
Replaces all SQLite operations. Collections:
  users/{email}           → user auth data
  students/{email}        → all student fields
  skills/{auto_id}        → skill records
  achievements/{auto_id}  → achievement records
  certifications/{auto_id}→ certification records
"""

import firebase_admin
from firebase_admin import credentials, firestore
import os, json, logging

logger = logging.getLogger(__name__)

_db = None


def get_db():
    """Return the Firestore client, initialising Firebase on first call."""
    global _db
    if _db is None:
        if not firebase_admin._apps:
            cred_json = os.environ.get("FIREBASE_CREDENTIALS_JSON")
            if cred_json:
                cred_dict = json.loads(cred_json)
                cred = credentials.Certificate(cred_dict)
            else:
                # Fallback: local file (for development)
                cred_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "firebase-credentials.json"
                )
                cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
        _db = firestore.client()
    return _db


# ─── Helpers ────────────────────────────────────────────────────────────────

def _doc_to_dict(doc):
    """Convert a Firestore DocumentSnapshot to a plain dict with 'id' field."""
    if doc is None or not doc.exists:
        return None
    d = doc.to_dict()
    d["id"] = doc.id
    return d


def _snap_list(query_result):
    """Convert a Firestore query result to a list of dicts."""
    return [_doc_to_dict(doc) for doc in query_result]


# ─── USERS ──────────────────────────────────────────────────────────────────

def get_user(email, role=None):
    """Return user dict by email (optionally filtered by role), or None."""
    db = get_db()
    doc = db.collection("users").document(email).get()
    user = _doc_to_dict(doc)
    if user is None:
        return None
    if role and user.get("role") != role:
        return None
    return user


def get_all_staff():
    """Return list of all staff user dicts."""
    db = get_db()
    return _snap_list(
        db.collection("users").where("role", "==", "staff").stream()
    )


def insert_user(email, role, password_hash):
    """
    Create a new user document.
    Raises ValueError if the email already exists.
    """
    db = get_db()
    ref = db.collection("users").document(email)
    if ref.get().exists:
        raise ValueError(f"User {email} already exists")
    ref.set({
        "email": email,
        "role": role,
        "password_hash": password_hash,
        "is_blocked": False,
    })


def delete_user(email):
    """Delete a user document by email."""
    db = get_db()
    db.collection("users").document(email).delete()


def toggle_user_block(email):
    """
    Toggle is_blocked for a user (admin cannot be blocked).
    Returns the new is_blocked boolean, or None if user not found.
    """
    db = get_db()
    ref = db.collection("users").document(email)
    doc = ref.get()
    if not doc.exists:
        return None
    user = doc.to_dict()
    if user.get("role") == "admin":
        return None
    new_status = not bool(user.get("is_blocked", False))
    ref.update({"is_blocked": new_status})
    return new_status


def ensure_admin(email, password_hash):
    """Create the admin user document if it does not exist yet."""
    db = get_db()
    ref = db.collection("users").document(email)
    if not ref.get().exists:
        ref.set({
            "email": email,
            "role": "admin",
            "password_hash": password_hash,
            "is_blocked": False,
        })


# ─── STUDENTS ───────────────────────────────────────────────────────────────

def get_student(email):
    """Return student dict by login email, or None."""
    db = get_db()
    doc = db.collection("students").document(email).get()
    return _doc_to_dict(doc)


def get_student_by_roll(roll):
    """Return student dict by roll number, or None."""
    db = get_db()
    results = list(
        db.collection("students").where("roll", "==", roll).limit(1).stream()
    )
    return _doc_to_dict(results[0]) if results else None


def get_student_by_id(doc_id):
    """Return student dict by Firestore document ID (= email), or None."""
    return get_student(doc_id)


def get_all_students(query=None):
    """
    Return all student dicts, optionally filtered by a search string.
    Attaches user is_blocked status from the users collection.
    """
    db = get_db()
    students = _snap_list(db.collection("students").stream())

    if query:
        q = query.lower()
        students = [
            s for s in students
            if q in (s.get("roll") or "").lower()
            or q in (s.get("name") or "").lower()
            or q in (s.get("student_id") or "").lower()
            or q in (s.get("user_email") or "").lower()
            or q in (s.get("department") or "").lower()
        ]

    # Attach is_blocked from users collection
    for s in students:
        email = s.get("user_email", s["id"])
        user_doc = db.collection("users").document(email).get()
        if user_doc.exists:
            s["is_blocked"] = user_doc.to_dict().get("is_blocked", False)
        else:
            s["is_blocked"] = False
        # user_id == email for URL routing
        s["user_id"] = email

    return students


def get_students_by_dept(query=None):
    """
    Return dict of {DEPT_NAME: [student_dict, ...]} sorted alpha.
    Includes is_blocked status per student.
    """
    students = get_all_students(query=query)
    departments = {}
    for s in students:
        dept = (s.get("department") or "UNASSIGNED").strip().upper()
        departments.setdefault(dept, []).append(s)
    return dict(sorted(departments.items()))


def insert_student(email, data):
    """
    Create a new student document keyed by email.
    Raises ValueError if already exists.
    """
    db = get_db()
    ref = db.collection("students").document(email)
    if ref.get().exists:
        raise ValueError(f"Student {email} already exists")
    data["user_email"] = email
    ref.set(data)


def update_student(email, data):
    """Update fields on a student document."""
    db = get_db()
    db.collection("students").document(email).update(data)


def update_student_score(email, score):
    """Convenience: update only placement_score."""
    db = get_db()
    db.collection("students").document(email).update({"placement_score": score})


def delete_student_all(email):
    """
    Delete student document AND all related skills/achievements/certifications.
    Also deletes the user document.
    """
    db = get_db()
    # Delete related sub-collections
    for coll in ("skills", "achievements", "certifications"):
        docs = db.collection(coll).where("student_email", "==", email).stream()
        for doc in docs:
            doc.reference.delete()
    db.collection("students").document(email).delete()
    db.collection("users").document(email).delete()
    logger.info(f"Deleted all Firestore records for student: {email}")


# ─── SKILLS ─────────────────────────────────────────────────────────────────

def get_skills(student_email):
    """Return list of skill dicts for a student."""
    db = get_db()
    return _snap_list(
        db.collection("skills")
          .where("student_email", "==", student_email)
          .stream()
    )


def insert_skill(student_email, skill_name, levels_completed):
    """Add a skill record."""
    db = get_db()
    db.collection("skills").add({
        "student_email": student_email,
        "skill_name": skill_name,
        "levels_completed": int(levels_completed),
    })


def update_skill(skill_id, student_email, skill_name, levels_completed):
    """Update a skill by Firestore document ID."""
    db = get_db()
    ref = db.collection("skills").document(skill_id)
    doc = ref.get()
    if doc.exists and doc.to_dict().get("student_email") == student_email:
        ref.update({"skill_name": skill_name, "levels_completed": int(levels_completed)})


def delete_skill(skill_id, student_email):
    """Delete a skill by Firestore document ID (verifies ownership)."""
    db = get_db()
    ref = db.collection("skills").document(skill_id)
    doc = ref.get()
    if doc.exists and doc.to_dict().get("student_email") == student_email:
        ref.delete()


# ─── ACHIEVEMENTS ────────────────────────────────────────────────────────────

def get_achievements(student_email):
    """Return list of achievement dicts for a student."""
    db = get_db()
    return _snap_list(
        db.collection("achievements")
          .where("student_email", "==", student_email)
          .stream()
    )


def insert_achievement(student_email, title, level, date_str, description=""):
    """Add an achievement record."""
    db = get_db()
    db.collection("achievements").add({
        "student_email": student_email,
        "title": title,
        "level": level,
        "date_str": date_str or "",
        "description": description or "",
    })


def update_achievement(ach_id, student_email, title, level, date_str):
    """Update an achievement by Firestore document ID."""
    db = get_db()
    ref = db.collection("achievements").document(ach_id)
    doc = ref.get()
    if doc.exists and doc.to_dict().get("student_email") == student_email:
        ref.update({"title": title, "level": level, "date_str": date_str or ""})


def delete_achievement(ach_id, student_email):
    """Delete an achievement by Firestore document ID (verifies ownership)."""
    db = get_db()
    ref = db.collection("achievements").document(ach_id)
    doc = ref.get()
    if doc.exists and doc.to_dict().get("student_email") == student_email:
        ref.delete()


# ─── CERTIFICATIONS ──────────────────────────────────────────────────────────

def get_certifications(student_email):
    """Return list of certification dicts for a student."""
    db = get_db()
    return _snap_list(
        db.collection("certifications")
          .where("student_email", "==", student_email)
          .stream()
    )


def insert_certification(student_email, name, provider, issue_date,
                         credential_url="", file_path=None, status="Pending"):
    """Add a certification record."""
    db = get_db()
    db.collection("certifications").add({
        "student_email": student_email,
        "name": name,
        "provider": provider or "",
        "issue_date": issue_date or "",
        "credential_url": credential_url or "",
        "file_path": file_path,
        "status": status,
    })


def update_certification(cert_id, student_email, name, provider, issue_date):
    """Update a certification's metadata by Firestore document ID."""
    db = get_db()
    ref = db.collection("certifications").document(cert_id)
    doc = ref.get()
    if doc.exists and doc.to_dict().get("student_email") == student_email:
        ref.update({"name": name, "provider": provider, "issue_date": issue_date or ""})


def update_certification_status(cert_id, status):
    """Update only the status field of a certification."""
    db = get_db()
    db.collection("certifications").document(cert_id).update({"status": status})


def delete_certification(cert_id, student_email):
    """Delete a certification by Firestore document ID (verifies ownership)."""
    db = get_db()
    ref = db.collection("certifications").document(cert_id)
    doc = ref.get()
    if doc.exists and doc.to_dict().get("student_email") == student_email:
        ref.delete()
