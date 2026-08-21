#!/bin/bash
python -m gunicorn wsgi:app -b 0.0.0.0:$PORT --timeout 180 --graceful-timeout 30