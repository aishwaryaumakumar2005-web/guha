#!/usr/bin/env bash
cd "$(dirname "$0")"
echo "Installing dependencies..."
pip3 install -r requirements.txt
echo "Initializing database..."
python3 init_db.py
echo "Starting server..."
python3 app.py
