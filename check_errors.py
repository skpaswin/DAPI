#!/usr/bin/env python
"""
Project Error Checker - Comprehensive diagnostics for DAPI project
"""

import sqlite3
import os
import sys
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError

def check_python_modules():
    """Check if all required Python modules can be imported"""
    print("\n" + "="*60)
    print("PYTHON MODULES CHECK")
    print("="*60)
    
    modules = ['flask', 'werkzeug', 'requests', 'waitress']
    
    for module in modules:
        try:
            __import__(module)
            print(f"✅ {module:15} - OK")
        except ImportError as e:
            print(f"❌ {module:15} - ERROR: {e}")
            return False
    
    return True


def check_database():
    """Check database connectivity and schema"""
    print("\n" + "="*60)
    print("DATABASE CHECK")
    print("="*60)
    
    db_path = "database.db"
    
    if not os.path.exists(db_path):
        print(f"⚠️  Database file not found: {db_path}")
        print("   (Database will be created on first run)")
        return True
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        print(f"✅ Database connected: {db_path}")
        print(f"✅ Tables found: {len(tables)}")
        
        for table in tables:
            table_name = table[0]
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            print(f"   • {table_name:20} ({len(columns)} columns)")
        
        conn.close()
        return True
        
    except sqlite3.Error as e:
        print(f"❌ Database error: {e}")
        return False


def check_templates():
    """Check all template files for Jinja2 syntax errors"""
    print("\n" + "="*60)
    print("TEMPLATE FILES CHECK")
    print("="*60)
    
    templates_dir = "templates"
    
    if not os.path.exists(templates_dir):
        print(f"❌ Templates directory not found: {templates_dir}")
        return False
    
    env = Environment(loader=FileSystemLoader(templates_dir))
    template_files = list(Path(templates_dir).glob("*.html"))
    
    if not template_files:
        print(f"⚠️  No template files found")
        return True
    
    errors = False
    
    for template_file in sorted(template_files):
        template_name = template_file.name
        
        try:
            env.get_template(template_name)
            print(f"✅ {template_name:30} - OK")
        except TemplateSyntaxError as e:
            print(f"❌ {template_name:30} - SYNTAX ERROR at line {e.lineno}: {e.message}")
            errors = True
        except Exception as e:
            print(f"❌ {template_name:30} - ERROR: {e}")
            errors = True
    
    return not errors


def check_app_module():
    """Check if main app.py module loads without errors"""
    print("\n" + "="*60)
    print("APPLICATION MODULE CHECK")
    print("="*60)
    
    try:
        import app
        print(f"✅ app.py imports successfully")
        print(f"✅ Flask app instance created: {app.app}")
        print(f"✅ Database path configured: {app.db_path}")
        print(f"✅ Logging configured")
        
        # Check routes
        routes = []
        for rule in app.app.url_map.iter_rules():
            if rule.endpoint != 'static':
                routes.append(f"   • {rule.rule:30} ({rule.endpoint})")
        
        print(f"✅ Routes registered: {len([r for r in routes if 'static' not in r])}")
        for route in sorted(routes)[:5]:
            print(route)
        if len(routes) > 5:
            print(f"   ... and {len(routes) - 5} more routes")
        
        return True
        
    except SyntaxError as e:
        print(f"❌ Syntax error in app.py: {e}")
        return False
    except ImportError as e:
        print(f"❌ Missing import in app.py: {e}")
        return False
    except Exception as e:
        print(f"❌ Error loading app.py: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_static_files():
    """Check static files"""
    print("\n" + "="*60)
    print("STATIC FILES CHECK")
    print("="*60)
    
    static_dir = "static"
    
    if not os.path.exists(static_dir):
        print(f"⚠️  Static directory not found: {static_dir}")
        return True
    
    static_files = list(Path(static_dir).glob("*"))
    
    if not static_files:
        print(f"⚠️  No static files found")
        return True
    
    for file in sorted(static_files):
        if file.is_file():
            size = file.stat().st_size
            print(f"✅ {file.name:30} ({size:,} bytes)")
    
    return True


def check_logs():
    """Check logs directory"""
    print("\n" + "="*60)
    print("LOGS DIRECTORY CHECK")
    print("="*60)
    
    logs_dir = "logs"
    
    if not os.path.exists(logs_dir):
        print(f"⚠️  Logs directory not found (will be created on first run)")
        return True
    
    log_files = list(Path(logs_dir).glob("*.log"))
    
    if not log_files:
        print(f"ℹ️  No log files yet")
        return True
    
    total_size = 0
    for log_file in sorted(log_files):
        size = log_file.stat().st_size
        total_size += size
        print(f"✅ {log_file.name:30} ({size:,} bytes)")
    
    print(f"✅ Total logs size: {total_size:,} bytes ({total_size / 1024 / 1024:.2f} MB)")
    
    return True


def main():
    """Run all checks"""
    print("\n")
    print("#" * 60)
    print("# DAPI PROJECT ERROR CHECKER")
    print("#" * 60)
    
    results = {
        "Python Modules": check_python_modules(),
        "Database": check_database(),
        "Templates": check_templates(),
        "Application Module": check_app_module(),
        "Static Files": check_static_files(),
        "Logs Directory": check_logs(),
    }
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for check_name, passed_check in results.items():
        status = "✅ PASS" if passed_check else "❌ FAIL"
        print(f"{status:8} - {check_name}")
    
    print("\n" + "="*60)
    
    if passed == total:
        print(f"✅ ALL CHECKS PASSED ({passed}/{total})")
        print("   The project is ready for deployment")
        return 0
    else:
        print(f"⚠️  SOME CHECKS FAILED ({total - passed} issues found)")
        return 1


if __name__ == '__main__':
    sys.exit(main())
