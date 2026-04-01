import sqlite3
from werkzeug.security import generate_password_hash

conn = sqlite3.connect('database.db')
cursor = conn.cursor()
pwd = generate_password_hash('password123')
cursor.execute("UPDATE users SET password_hash = ? WHERE email = 'test.student@gmail.com'", (pwd,))
if cursor.rowcount == 0:
    print("User test.student@gmail.com not found, creating dummy student.")
    cursor.execute("INSERT INTO users (email, role, password_hash) VALUES ('test.student@gmail.com', 'student', ?)", (pwd,))
    cursor.execute("INSERT INTO students (user_email, student_id, roll, name, contact_email, phone, parent_phone, address, department, mentor_name, tenth, twelfth) VALUES ('test.student@gmail.com', 'S101', 'R101', 'Test Student', 'test@example.com', '1234567890', '0987654321', 'Address', 'CS', 'Mentor1', '90', '90')")
conn.commit()
conn.close()
print("Done")
