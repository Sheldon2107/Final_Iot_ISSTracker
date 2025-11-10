# server.py — ISS Tracker Test Server (Rapid Simulation)
from flask import Flask, jsonify, send_from_directory, request
import csv
import os
from threading import Thread, Event
from datetime import datetime, timedelta, timezone
import random

app = Flask(__name__)
DATA_FILE = 'iss_data.csv'
FETCH_INTERVAL = 5  # seconds for fast testing
stop_event = Event()
MYT = timezone(timedelta(hours=8))  # Malaysia Time UTC+8

# --- Ensure CSV exists with header ---
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp','latitude','longitude','altitude','velocity','ts_myt'])

# --- Helper ---
def safe_float(v):
    try:
        return float(v)
    except:
        return None

# --- Background fetcher (simulated) ---
def fetch_iss_data():
    # Start simulation at 11 Nov 23:58
    simulated_time = datetime(2025, 11, 11, 23, 58, 0, tzinfo=MYT)

    while not stop_event.is_set():
        try:
            # Randomized ISS-like values
            latitude = round(random.uniform(-90, 90), 4)
            longitude = round(random.uniform(-180, 180), 4)
            altitude = round(random.uniform(400, 420), 2)
            velocity = round(random.uniform(7.5, 7.8), 2)

            timestamp = int(simulated_time.timestamp())
            ts_myt_excel = "'" + simulated_time.strftime('%Y-%m-%d %H:%M:%S')

            # Append to CSV
            with open(DATA_FILE, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([timestamp, latitude, longitude, altitude, velocity, ts_myt_excel])

            print(f"✅ Simulated ISS data: {ts_myt_excel}")

            # Increment time by FETCH_INTERVAL seconds
            simulated_time += timedelta(seconds=FETCH_INTERVAL)

        except Exception as e:
            print(f"❌ Error in fetch_iss_data: {e}")

        stop_event.wait(FETCH_INTERVAL)

# Start fetcher thread
Thread(target=fetch_iss_data, daemon=True).start()

# --- API: Preview all records ---
@app.route('/api/preview')
def api_preview():
    records = []
    if not os.path.exists(DATA_FILE):
        return jsonify({'records': []})
    try:
        with open(DATA_FILE, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = int(row['timestamp'])
                dt = datetime.fromtimestamp(ts, tz=MYT)
                records.append({
                    'timestamp': ts,
                    'ts_myt': row.get('ts_myt', dt.strftime('%Y-%m-%d %H:%M:%S')),
                    'latitude': safe_float(row.get('latitude')),
                    'longitude': safe_float(row.get('longitude')),
                    'altitude': safe_float(row.get('altitude')),
                    'velocity': safe_float(row.get('velocity'))
                })
        return jsonify({'records': records})
    except Exception as e:
        return jsonify({'records': [], 'error': str(e)})

# --- API: Download CSV ---
@app.route('/api/download')
def download_csv():
    if os.path.exists(DATA_FILE):
        return send_from_directory('.', DATA_FILE, as_attachment=True)
    return "CSV not found", 404

# --- Serve frontend ---
@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

@app.route('/database')
def serve_database():
    return send_from_directory('.', 'database.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

# --- Start server ---
if __name__ == '__main__':
    try:
        print("🚀 Starting ISS Tracker Test Server (fast simulation)...")
        print(f"📍 Data file: {DATA_FILE}")
        print(f"⏱ Fetch interval: {FETCH_INTERVAL}s")
        print(f"🌏 Timezone: MYT (UTC+8)")
        app.run(debug=True, host='0.0.0.0', port=5000)
    finally:
        stop_event.set()
