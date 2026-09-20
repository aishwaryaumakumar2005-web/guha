#!/bin/bash
python -m gunicorn wsgi:app -w 1 --threads 4 -b 0.0.0.0:$PORT --timeout 180 --graceful-timeout 30