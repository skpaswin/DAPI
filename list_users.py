import sqlite3
import os

db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db")
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
users = conn.execute("SELECT email, role FROM users").fetchall()
for u in users:
    print(f"Email: {u['email']}, Role: {u['role']}")
conn.close()
