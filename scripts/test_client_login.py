#!/usr/bin/env python3
import os, sys
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from app import create_app

app = create_app()

with app.test_client() as c:
    try:
        resp = c.post('/login', data={'username': 'staff', 'password': 'staff123'}, follow_redirects=True)
        print('STATUS', resp.status_code)
        print(resp.get_data(as_text=True)[:2000])
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise
