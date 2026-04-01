import app
import sqlite3
import os

try:
    conn = sqlite3.connect('dapi.db')
    conn.row_factory = sqlite3.Row
    
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(students)")
    cols = [row['name'] for row in cur.fetchall()]
    assert 'assignments_score' in cols, "assignments_score column missing"
    assert 'participation_score' in cols, "participation_score column missing"
    print("Columns exist!")
    
    student_row = {
        'sem1': 8.5, 'sem2': 8.5, 'sem3': 8.5, 'sem4': 8.5,
        'sem5': 8.5, 'sem6': 8.5, 'sem7': 8.5, 'sem8': 8.5,
        'assignments_score': 85.0,
        'participation_score': 90.0,
        'semester_start': '2023-08-01',
        'present_days': 100, 
        'arrear_count': 0
    }
    
    app.college_working_days = lambda start, end: 120
    
    breakdown = app.get_score_breakdown(conn, "test@test.com", student_row)
    print("Breakdown Map:", breakdown)
    
    print("Tests passed successfully!")
    
except Exception as e:
    import traceback
    traceback.print_exc()
finally:
    if 'conn' in locals():
        conn.close()
