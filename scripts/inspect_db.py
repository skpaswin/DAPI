import sqlite3
import os

path = r"c:\Users\skpas\OneDrive\Desktop\DAPI\database.db"
print("db exists", os.path.exists(path))

conn = sqlite3.connect(path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

st = cur.execute('SELECT user_email,name FROM students LIMIT 1').fetchone()
print('student', dict(st) if st else None)

if st:
    email = st['user_email']
    ach = cur.execute('SELECT * FROM achievements WHERE student_email=?', (email,)).fetchall()
    cert = cur.execute('SELECT * FROM certifications WHERE student_email=?', (email,)).fetchall()
    print('ach len', len(ach))
    print('cert len', len(cert))
    print('ach sample', [dict(x) for x in ach[:5]])
    print('cert sample', [dict(x) for x in cert[:5]])

conn.close()
