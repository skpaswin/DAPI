import sqlite3

db_path = r"c:\Users\skpas\OneDrive\Desktop\DAPI\database.db"
conn = sqlite3.connect(db_path)

conn.execute("UPDATE students SET department = UPPER(TRIM(department)) WHERE department IS NOT NULL")
conn.commit()

rows = conn.execute("SELECT DISTINCT department FROM students ORDER BY department").fetchall()
print("Departments now in DB:")
for r in rows:
    print(" ", r[0])

conn.close()
print("Done.")
