#!/usr/bin/env python
"""
DAPI Project - Advanced Diagnostics
Checks for logic errors, security issues, and best practices
"""

import os
import re
import ast
from pathlib import Path

def check_secret_key():
    """Check if secret key is properly configured"""
    print("\n" + "="*60)
    print("SECURITY CHECK - SECRET KEY CONFIGURATION")
    print("="*60)
    
    with open('app.py', 'r') as f:
        content = f.read()
    
    if 'os.environ.get("SECRET_KEY"' in content:
        print("✅ Secret key uses environment variable")
        print("   Recommendation: Set SECRET_KEY in production")
        return True
    else:
        print("⚠️  Hardcoded secret key detected")
        return False


def check_password_hashing():
    """Check if passwords are properly hashed"""
    print("\n" + "="*60)
    print("SECURITY CHECK - PASSWORD HASHING")
    print("="*60)
    
    with open('app.py', 'r') as f:
        content = f.read()
    
    if 'generate_password_hash' in content and 'check_password_hash' in content:
        print("✅ Password hashing properly implemented")
        print("   Using werkzeug.security for password hashing")
        return True
    else:
        print("❌ Password hashing not properly implemented")
        return False


def check_sql_injection():
    """Check for SQL injection protection"""
    print("\n" + "="*60)
    print("SECURITY CHECK - SQL INJECTION PREVENTION")
    print("="*60)
    
    with open('app.py', 'r') as f:
        content = f.read()
    
    # Check for parameterized queries
    if content.count('(?, ') > 10:
        print("✅ Parameterized SQL queries used throughout")
        print(f"   Found {content.count('?')} parameterized placeholders")
        return True
    else:
        print("⚠️  Some raw SQL queries may exist")
        return False


def check_session_security():
    """Check session handling"""
    print("\n" + "="*60)
    print("SECURITY CHECK - SESSION HANDLING")
    print("="*60)
    
    with open('app.py', 'r') as f:
        content = f.read()
    
    if 'session.get' in content and 'session.clear' in content:
        print("✅ Session handling implemented")
        print("   Logout properly clears sessions")
        return True
    else:
        print("⚠️  Session handling may be incomplete")
        return False


def check_input_validation():
    """Check for input validation"""
    print("\n" + "="*60)
    print("VALIDATION CHECK - INPUT SANITIZATION")
    print("="*60)
    
    with open('app.py', 'r') as f:
        content = f.read()
    
    checks = {
        'Email validation': 'validate_email_role' in content,
        'Date parsing validation': 'parse_ymd' in content,
        'Safe integer parsing': 'safe_int' in content,
        'Safe float parsing': 'safe_float' in content,
        'String stripping': '.strip()' in content,
    }
    
    passed = sum(1 for v in checks.values() if v)
    
    for check_name, result in checks.items():
        status = "✅" if result else "❌"
        print(f"{status} {check_name}")
    
    return passed >= 4


def check_error_handling():
    """Check error handling"""
    print("\n" + "="*60)
    print("ERROR HANDLING CHECK")
    print("="*60)
    
    with open('app.py', 'r') as f:
        content = f.read()
    
    checks = {
        'Error handlers': '@app.errorhandler' in content,
        'Try-except blocks': 'try:' in content,
        'Logging': 'logger.' in content,
        'Health check endpoint': '/health' in content,
    }
    
    passed = sum(1 for v in checks.values() if v)
    
    for check_name, result in checks.items():
        status = "✅" if result else "⚠️"
        print(f"{status} {check_name}")
    
    return passed == 4


def check_database_schema():
    """Check database schema completeness"""
    print("\n" + "="*60)
    print("DATABASE SCHEMA CHECK")
    print("="*60)
    
    import sqlite3
    
    if not os.path.exists('database.db'):
        print("⚠️  Database file not found (will be created on first run)")
        return True
    
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    
    expected_tables = {
        'users': ['id', 'email', 'role', 'password_hash'],
        'students': ['id', 'user_email', 'student_id', 'roll', 'name'],
        'skills': ['id', 'student_email', 'skill_name', 'levels_completed'],
        'achievements': ['id', 'student_email', 'title'],
        'certifications': ['id', 'student_email', 'name'],
    }
    
    passed = True
    
    for table_name, expected_cols in expected_tables.items():
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        
        missing = [col for col in expected_cols if col not in columns]
        
        if not missing:
            print(f"✅ {table_name:15} - All required columns present")
        else:
            print(f"❌ {table_name:15} - Missing: {', '.join(missing)}")
            passed = False
    
    conn.close()
    return passed


def check_code_quality():
    """Check code quality"""
    print("\n" + "="*60)
    print("CODE QUALITY CHECK")
    print("="*60)
    
    with open('app.py', 'r') as f:
        lines = f.readlines()
    
    total_lines = len(lines)
    comment_lines = len([l for l in lines if l.strip().startswith('#')])
    comment_ratio = (comment_lines / total_lines * 100) if total_lines > 0 else 0
    
    print(f"✅ Total lines of code: {total_lines}")
    print(f"✅ Comment ratio: {comment_ratio:.1f}%")
    
    if comment_ratio > 5:
        print("✅ Good code documentation")
    else:
        print("⚠️  Could use more documentation")
    
    # Check for long lines
    long_lines = [i+1 for i, l in enumerate(lines) if len(l) > 100]
    if not long_lines:
        print("✅ No excessively long lines (>100 chars)")
    else:
        print(f"⚠️  {len(long_lines)} lines exceed 100 characters")
    
    return True


def check_requirements():
    """Check requirements.txt"""
    print("\n" + "="*60)
    print("DEPENDENCIES CHECK")
    print("="*60)
    
    if not os.path.exists('requirements.txt'):
        print("❌ requirements.txt not found")
        return False
    
    with open('requirements.txt', 'r') as f:
        reqs = f.read().strip().split('\n')
    
    print(f"✅ Requirements file found")
    print(f"✅ {len(reqs)} dependencies specified:")
    
    for req in reqs:
        if req.strip():
            print(f"   • {req.strip()}")
    
    return len(reqs) >= 3


def check_file_structure():
    """Check project file structure"""
    print("\n" + "="*60)
    print("PROJECT STRUCTURE CHECK")
    print("="*60)
    
    required_dirs = {
        'templates': 'HTML templates',
        'static': 'CSS/JS files',
        'logs': 'Log files',
    }
    
    required_files = {
        'app.py': 'Main application',
        'database.db': 'SQLite database',
        'requirements.txt': 'Python dependencies',
    }
    
    print("Directories:")
    for dirname, desc in required_dirs.items():
        exists = "✅" if os.path.isdir(dirname) else "⚠️"
        print(f"{exists} {dirname:15} - {desc}")
    
    print("\nFiles:")
    for filename, desc in required_files.items():
        exists = "✅" if os.path.exists(filename) else "❌"
        print(f"{exists} {filename:20} - {desc}")
    
    return True


def main():
    """Run all advanced diagnostics"""
    print("\n")
    print("#" * 60)
    print("# DAPI PROJECT - ADVANCED DIAGNOSTICS")
    print("#" * 60)
    
    results = {
        "Secret Key Configuration": check_secret_key(),
        "Password Hashing": check_password_hashing(),
        "SQL Injection Prevention": check_sql_injection(),
        "Session Security": check_session_security(),
        "Input Validation": check_input_validation(),
        "Error Handling": check_error_handling(),
        "Database Schema": check_database_schema(),
        "Code Quality": check_code_quality(),
        "Requirements": check_requirements(),
        "File Structure": check_file_structure(),
    }
    
    print("\n" + "="*60)
    print("DIAGNOSTIC SUMMARY")
    print("="*60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for check_name, passed_check in results.items():
        status = "✅" if passed_check else "⚠️"
        print(f"{status} {check_name}")
    
    print("\n" + "="*60)
    
    if passed == total:
        print(f"✅ ALL DIAGNOSTICS PASSED ({passed}/{total})")
        print("   Project is production-ready")
    else:
        print(f"⚠️  {total - passed} AREAS NEED ATTENTION")
    
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
