#!/usr/bin/env python3
import urllib.request, urllib.parse, sys

url = 'http://127.0.0.1:5000/login'
data = urllib.parse.urlencode({'username': 'staff', 'password': 'staff123'}).encode()
req = urllib.request.Request(url, data=data, method='POST')
try:
    resp = urllib.request.urlopen(req, timeout=10)
    print('STATUS', resp.getcode())
    body = resp.read().decode('utf-8', errors='replace')
    print(body[:4000])
except Exception as e:
    try:
        # urllib.error.HTTPError has .read() with response body
        body = e.read().decode('utf-8', errors='replace')
        print('HTTP ERROR BODY:')
        print(body[:8000])
    except Exception:
        pass
    print('ERROR', type(e), e)
    sys.exit(2)
