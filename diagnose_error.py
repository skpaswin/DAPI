import sqlite3
import os
from app import get_score_breakdown, get_db

def test():
    if os.path.exists("test_diag.db"):
        os.remove("test_diag.db")
    
    conn = sqlite3.connect("test_diag.db")
    conn.row_factory = sqlite3.Row
    
    # Create a simplified students table that matches what get_score_breakdown needs
    conn.execute("""
        CREATE TABLE students (
            user_email TEXT, 
            leetcode_solved INTEGER, 
            github_repos INTEGER, 
            linkedin_url TEXT, 
            arrear_count INTEGER,
            sem1 REAL, sem2 REAL, sem3 REAL, sem4 REAL, sem5 REAL, sem6 REAL, sem7 REAL, sem8 REAL
        )
    """)
    
    # Create other tables needed by get_score_breakdown
    conn.execute("CREATE TABLE skills (student_email TEXT, levels_completed INTEGER)")
    conn.execute("CREATE TABLE achievements (student_email TEXT)")
    conn.execute("CREATE TABLE certifications (student_email TEXT, status TEXT)")
    
    # Insert mock data
    conn.execute("""
        INSERT INTO students (user_email, leetcode_solved, github_repos, linkedin_url, arrear_count, sem1) 
        VALUES ('test@gmail.com', 10, 5, 'http://li.com', 0, 8.5)
    """)
    conn.commit()
    
    row = conn.execute("SELECT * FROM students WHERE user_email='test@gmail.com'").fetchone()
    
    print(f"Row type: {type(row)}")
    try:
        breakdown = get_score_breakdown(conn, 'test@gmail.com', row)
        print("Success!")
        print(breakdown)
    except Exception as e:
        print(f"Failed with: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()
        if os.path.exists("test_diag.db"):
            os.remove("test_diag.db")

if __name__ == "__main__":
    test()
