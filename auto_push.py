"""
Auto-commit and push script for GitHub
Monitors file changes and automatically commits/pushes to GitHub
"""
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

# Configuration
WATCH_DIR = os.path.dirname(os.path.abspath(__file__))
CHECK_INTERVAL = 10  # seconds
GIT_BRANCH = "main"
EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "venv", "logs", ".idea", ".vscode"}
EXCLUDE_FILES = {".gitignore", "auto_push.py"}

def should_watch(path):
    """Check if file/directory should be watched"""
    rel_path = os.path.relpath(path, WATCH_DIR)
    parts = rel_path.split(os.sep)
    return not any(part in EXCLUDE_DIRS for part in parts) and path.name not in EXCLUDE_FILES

def get_watched_files():
    """Get all files to watch"""
    watched = set()
    for root, dirs, files in os.walk(WATCH_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for file in files:
            filepath = os.path.join(root, file)
            if should_watch(Path(filepath)):
                watched.add(filepath)
    return watched

def run_git_command(command):
    """Run git command"""
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=WATCH_DIR,
            capture_output=True,
            text=True
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return False, "", str(e)

def commit_and_push(changed_files):
    """Commit and push changes to GitHub"""
    try:
        # Add changes
        for file in changed_files:
            rel_path = os.path.relpath(file, WATCH_DIR)
            subprocess.run(
                f'git add "{rel_path}"',
                shell=True,
                cwd=WATCH_DIR,
                capture_output=True
            )
        
        # Check if there are staged changes
        status_ok, status_out, _ = run_git_command("git status --short")
        if not status_out:
            return
        
        # Create commit
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        success, stdout, stderr = run_git_command(
            f'git commit -m "Auto-update: {timestamp}"'
        )
        
        if success:
            # Push to GitHub
            push_ok, push_out, push_err = run_git_command(f"git push origin {GIT_BRANCH}")
            if push_ok:
                print(f"✅ [{timestamp}] Changes committed and pushed!")
            else:
                print(f"⚠️  [{timestamp}] Commit successful but push failed: {push_err}")
    except Exception as e:
        print(f"❌ Error: {e}")

def monitor_files():
    """Monitor files for changes"""
    print("🚀 Auto-Push Monitor Started")
    print(f"📁 Watching: {WATCH_DIR}")
    print(f"⏱️ Check interval: {CHECK_INTERVAL} seconds")
    print("-" * 50)
    
    watched_files = get_watched_files()
    file_times = {f: os.path.getmtime(f) for f in watched_files if os.path.exists(f)}
    
    try:
        while True:
            time.sleep(CHECK_INTERVAL)
            
            # Refresh watched files
            current_files = get_watched_files()
            changed = set()
            
            # Check for modified files
            for filepath in current_files:
                if os.path.exists(filepath):
                    current_time = os.path.getmtime(filepath)
                    if filepath not in file_times or file_times[filepath] != current_time:
                        changed.add(filepath)
                        file_times[filepath] = current_time
            
            # Check for new files
            new_files = current_files - set(file_times.keys())
            for filepath in new_files:
                changed.add(filepath)
                file_times[filepath] = os.path.getmtime(filepath)
            
            # Commit and push if changes detected
            if changed:
                commit_and_push(changed)
            
    except KeyboardInterrupt:
        print("\n⛔ Auto-Push Monitor Stopped")

if __name__ == "__main__":
    monitor_files()
