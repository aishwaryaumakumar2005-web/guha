import sqlite3
import os

BACKUP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backup_data.db')
OUTPUT_FILE = 'neon_import.sql'

def sqlite_to_sql():
    """Convert SQLite database to SQL file"""
    print(f"Converting {BACKUP_PATH} to SQL...")
    
    conn = sqlite3.connect(BACKUP_PATH)
    
    with open(OUTPUT_FILE, 'w') as f:
        for line in conn.iterdump():
            f.write(line + '\n')
    
    conn.close()
    
    print(f"Successfully created {OUTPUT_FILE}")
    print(f"File size: {os.path.getsize(OUTPUT_FILE)} bytes")
    print("You can now import this file in Neon dashboard")

if __name__ == '__main__':
    sqlite_to_sql()