"""Simple Neon Postgres health-check script.

Checks connectivity, server version, current database, current user,
database size, and active connection counts. Reads `DATABASE_URL` from the
environment or falls back to `render.yaml` in the repo root.

Usage:
  python scripts/neon_health_check.py

Environment:
  DATABASE_URL - optional; when not set the script reads `render.yaml`.
"""
import os
import re
import sys
import psycopg2
import psycopg2.extras


def read_database_url_from_render_yaml(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except FileNotFoundError:
        return None
    m = re.search(r"DATABASE_URL\s*:\s*\"?(?P<url>[^\n\"]+)\"?", text)
    return m.group('url').strip() if m else None


def human_readable_bytes(n):
    for unit in ['B','KB','MB','GB','TB']:
        if n < 1024.0:
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} PB"


def main():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        render_yaml = os.path.join(repo_root, 'render.yaml')
        db_url = read_database_url_from_render_yaml(render_yaml)

    if not db_url:
        print('DATABASE_URL not set and render.yaml not found/contains no DATABASE_URL')
        sys.exit(2)

    print('Using DATABASE_URL from environment' if os.environ.get('DATABASE_URL') else f'Using DATABASE_URL from {render_yaml}')

    try:
        conn = psycopg2.connect(db_url, connect_timeout=10)
    except Exception as e:
        print('Connection failed:', e)
        sys.exit(3)

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute('SELECT version()')
            version = cur.fetchone()[0]
            cur.execute('SELECT current_database()')
            current_db = cur.fetchone()[0]
            cur.execute('SELECT current_user')
            current_user = cur.fetchone()[0]
            cur.execute('SELECT now()')
            now = cur.fetchone()[0]

            cur.execute("SELECT pg_database_size(current_database())")
            size_bytes = cur.fetchone()[0] or 0
            cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
            size_pretty = cur.fetchone()[0] or '0'

            cur.execute("SELECT COUNT(*) FROM pg_stat_activity")
            active_conns = cur.fetchone()[0]
            cur.execute("SELECT setting::int FROM pg_settings WHERE name='max_connections'")
            max_conns_row = cur.fetchone()
            max_conns = int(max_conns_row[0]) if max_conns_row else None

            print('--- Neon Postgres Health Check ---')
            print('Server version:', version)
            print('Current database:', current_db)
            print('Current user:', current_user)
            print('Time:', now)
            print('Database size:', f'{size_pretty} ({size_bytes} bytes)')
            if max_conns is not None:
                print(f'Connections: {active_conns} active / {max_conns} max')
            else:
                print(f'Connections: {active_conns} active')

            # show top active queries (if any)
            cur.execute("""
                SELECT pid, usename, state, query_start, now() - query_start AS duration,
                       substring(query,1,300) AS query
                FROM pg_stat_activity
                WHERE state <> 'idle' AND pid <> pg_backend_pid()
                ORDER BY query_start DESC
                LIMIT 10
            """)
            active_queries = cur.fetchall()
            if active_queries:
                print('\nTop active queries:')
                for r in active_queries:
                    pid = r['pid']
                    user = r['usename']
                    state = r['state']
                    started = r['query_start']
                    dur = r['duration']
                    q = r['query']
                    print(f' - pid={pid} user={user} state={state} duration={dur}\n   {q[:200]}')
            else:
                print('\nNo non-idle queries found.')

            # simple quick health query
            cur.execute('SELECT 1')
            ok = cur.fetchone()[0]
            print('\nSimple query result:', ok)

    finally:
        conn.close()


if __name__ == '__main__':
    main()
