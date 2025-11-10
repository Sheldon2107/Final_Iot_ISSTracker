# server.py — minimal CSV-based ISS collector + preview endpoint
from flask import Flask, jsonify, send_from_directory, request
import requests
import csv
import os
from threading import Thread, Event
from datetime import datetime, timedelta
import time

app = Flask(__name__)
DATA_FILE = 'iss_data.csv'
FETCH_INTERVAL = 1  # seconds
stop_event = Event()

# Ensure CSV file exists with header (timestamp = unix seconds)
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp','latitude','longitude','altitude','velocity'])

def safe_float(v):
    try:
        return float(v)
    except Exception:
        return None

def fetch_iss_data():
    while not stop_event.is_set():
        try:
            res = requests.get('https://api.wheretheiss.at/v1/satellites/25544', timeout=8)
            if res.status_code == 200:
                d = res.json()
                # Some providers use different keys; handle defensively
                timestamp = int(d.get('timestamp', time.time()))
                latitude = safe_float(d.get('latitude'))
                longitude = safe_float(d.get('longitude'))
                altitude = safe_float(d.get('altitude'))
                velocity = safe_float(d.get('velocity'))
                with open(DATA_FILE, 'a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([timestamp, latitude, longitude, altitude, velocity])
        except Exception as e:
            # Print errors to container logs
            print("Error fetching ISS data:", e)
        # wait but allow stop_event to break early
        stop_event.wait(FETCH_INTERVAL)

# Start background fetching thread (daemon)
t = Thread(target=fetch_iss_data, daemon=True)
t.start()

@app.route('/api/preview')
def api_preview():
    # day_index semantics: 0 = first day found in CSV
    try:
        day_index = int(request.args.get('day_index', 0))
    except Exception:
        day_index = 0

    records = []
    if not os.path.exists(DATA_FILE):
        return jsonify({'records': []})

    with open(DATA_FILE, 'r') as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)
        if not all_rows:
            return jsonify({'records': []})

        # compute start of day 0 (based on first record timestamp)
        try:
            first_ts = int(all_rows[0]['timestamp'])
        except Exception:
            # If first row missing or invalid, return empty
            return jsonify({'records': []})

        start_of_day = datetime.utcfromtimestamp(first_ts).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=day_index)
        end_of_day = start_of_day + timedelta(days=1)

        for row in all_rows:
            try:
                ts = int(row['timestamp'])
            except Exception:
                continue
            dt = datetime.utcfromtimestamp(ts)
            if start_of_day <= dt < end_of_day:
                lat = safe_float(row.get('latitude'))
                lon = safe_float(row.get('longitude'))
                alt = safe_float(row.get('altitude'))
                vel = safe_float(row.get('velocity'))
                records.append({
                    'timestamp': ts,
                    'ts_utc': dt.strftime('%Y-%m-%d %H:%M:%S'),
                    'latitude': lat,
                    'longitude': lon,
                    'altitude': alt,
                    'velocity': vel
                })

    return jsonify({'records': records})

# Serve frontend files
@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

# Keep this route name since your dashboard uses <a href="/database">
@app.route('/database')
def serve_database():
    return send_from_directory('.', 'database.html')

@app.route('/api/download')
def download_csv():
    if os.path.exists(DATA_FILE):
        return send_from_directory('.', DATA_FILE, as_attachment=True)
    return "CSV file not found", 404

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

if __name__ == '__main__':
    try:
        # Run dev server on port 5000
        app.run(debug=True, host='0.0.0.0', port=5000)
    finally:
        stop_event.set()
