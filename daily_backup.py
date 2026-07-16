#!/usr/bin/env python
"""
Daily Database Backup Script
Run this script manually or schedule it with Windows Task Scheduler for automated daily backups.
"""
import os
import shutil
from datetime import datetime, date
import sys

def get_backup_dir():
    """Get the backup directory path"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    backup_dir = os.path.join(script_dir, 'backups')
    return backup_dir

def create_backup():
    """Create a daily backup of the database"""
    try:
        backup_dir = get_backup_dir()
        os.makedirs(backup_dir, exist_ok=True)
        
        # Database path
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(script_dir, 'instance', 'institute.db')
        
        if not os.path.exists(db_path):
            print(f"Error: Database file not found at {db_path}")
            return False
        
        # Create backup with date
        today_str = date.today().isoformat()
        backup_name = f'auto_backup_{today_str}.db'
        backup_path = os.path.join(backup_dir, backup_name)
        
        # Skip if backup already exists for today
        if os.path.exists(backup_path):
            print(f"Backup already exists for today: {backup_name}")
            return True
        
        # Copy database to backup location
        shutil.copy2(db_path, backup_path)
        
        # Get file size for reporting
        size_mb = os.path.getsize(backup_path) / (1024 * 1024)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        print(f"[{timestamp}] Backup created successfully: {backup_name} ({size_mb:.2f} MB)")
        
        # Clean up old backups (keep last 30 days)
        cleanup_old_backups(backup_dir)
        
        return True
        
    except Exception as e:
        print(f"Error creating backup: {e}")
        return False

def cleanup_old_backups(backup_dir, keep_days=30):
    """Remove backups older than specified days"""
    try:
        from datetime import timedelta
        cutoff_date = date.today() - timedelta(days=keep_days)
        
        for filename in os.listdir(backup_dir):
            if filename.startswith('auto_backup_') and filename.endswith('.db'):
                file_path = os.path.join(backup_dir, filename)
                file_date = datetime.fromtimestamp(os.path.getmtime(file_path)).date()
                
                if file_date < cutoff_date:
                    os.remove(file_path)
                    print(f"Removed old backup: {filename}")
                    
    except Exception as e:
        print(f"Error cleaning up old backups: {e}")

if __name__ == '__main__':
    print("Starting daily database backup...")
    success = create_backup()
    if success:
        print("Backup completed successfully.")
        sys.exit(0)
    else:
        print("Backup failed.")
        sys.exit(1)
