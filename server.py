# server.py — ISS collector with Malaysian time (UTC+8), daily CSVs
from flask import Flask, jsonify, send_from_directory, request
import requests
import csv
import os
from threading import Thread, Event
from datetime import datetime, timedelta, timezone
import glob
import time

app = Flask(__name__)
FETCH_INTERVAL = 60  # seconds
stop_event = Event()

MYT = timezone(timedelta(hours=8))  # Malaysia Time UTC+8
CSV_FOLDER = 'data'  # folder to store daily CSVs
os.makedirs(CSV_FOLDER, exist_ok=True)

def safe_float(v):
    try:
        return float(v)
    except Exception:
        return None

def get_csv_filename(dt=None):
    """Return filename for a given datetime (default now)."""
    if dt is None:
        dt = datetime.now(MYT)
    return os.path.join(CSV_FOLDER, f"iss_data_{dt.strftime('%Y-%m-%d')}.csv")

def ensure_csv_exists(filename):
    if not os.path.exists(filename):
        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp','latitude','longitude','altitude','velocity','ts_myt'])

def fetch_and_save_iss_data():
    """Fetch ISS data once and save to today's CSV."""
    filename = get_csv_filename()
    ensure_csv_exists(filename)
    try:
        res = requests.get('https://api.wheretheiss.at/v1/satellites/25544', timeout=8)
        if res.status_code == 200:
            d = res.json()
            timestamp = int(d.get('timestamp', time.time()))
            latitude = safe_float(d.get('latitude'))
            longitude = safe_float(d.get('longitude'))
            altitude = safe_float(d.get('altitude'))
            velocity = safe_float(d.get('velocity'))

            ts_myt = datetime.fromtimestamp(timestamp, tz=MYT).strftime('%Y-%m-%d %H:%M:%S')
            ts_myt_excel = "'" + ts_myt  # Excel-friendly

            with open(filename, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([timestamp, latitude, longitude, altitude, velocity, ts_myt_excel])
            return True
    except Exception as e:
        print("Error fetching ISS data:", e)
    return False

def fetch_loop():
    while not stop_event.is_set():
        fetch_and_save_iss_data()
        stop_event.wait(FETCH_INTERVAL)

# Only start background thread locally, not on Render
if os.environ.get("RENDER") is None:
    t = Thread(target=fetch_loop, daemon=True)
    t.start()

# --- API Routes ---
@app.route('/api/fetch-now')
def api_fetch_now():
    success = fetch_and_save_iss_data()
    return jsonify({'success': success})

@app.route('/api/all-days')
def api_all_days():
    """Return list of available days (CSV filenames)."""
    files = sorted(glob.glob(os.path.join(CSV_FOLDER, 'iss_data_*.csv')), reverse=True)
    days = [os.path.basename(f).replace('iss_data_', '').replace('.csv','') for f in files]
    return jsonify({"days": days})

@app.route('/api/day/<day>')
def api_day_records(day):
    """Return all records for a specific day."""
    filename = os.path.join(CSV_FOLDER, f"iss_data_{day}.csv")
    records = []
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            reader = csv.DictReader(f)
            for i, r in enumerate(reader):
                records.append({
                    "id": i+1,
                    "timestamp_unix": int(r.get('timestamp', 0)),
                    "ts_myt": r.get('ts_myt'),
                    "latitude": safe_float(r.get('latitude')),
                    "longitude": safe_float(r.get('longitude')),
                    "altitude": safe_float(r.get('altitude')),
                    "velocity": safe_float(r.get('velocity')),
                    "day": day
                })
    return jsonify({"records": records})

@app.route('/api/download/day/<day>')
def download_day(day):
    filename = os.path.join(CSV_FOLDER, f"iss_data_{day}.csv")
    if os.path.exists(filename):
        return send_from_directory(CSV_FOLDER, os.path.basename(filename), as_attachment=True)
    return "CSV file not found", 404

@app.route('/api/download/all')
def download_all_combined():
    """Combine all daily CSVs into one for download."""
    combined_filename = os.path.join(CSV_FOLDER, 'iss_data_all.csv')
    files = sorted(glob.glob(os.path.join(CSV_FOLDER, 'iss_data_*.csv')))
    if not files:
        return "No CSV files found", 404

    # Write combined file
    with open(combined_filename, 'w', newline='') as out_f:
        writer = None
        for i, file in enumerate(files):
            with open(file, 'r') as f:
                reader = csv.reader(f)
                header = next(reader)
                if writer is None:
                    writer = csv.writer(out_f)
                    writer.writerow(header)
                for row in reader:
                    writer.writerow(row)
    return send_from_directory(CSV_FOLDER, 'iss_data_all.csv', as_attachment=True)

# Serve static HTML
@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

@app.route('/database')
def serve_database():
    return send_from_directory('.', 'database.html')

if __name__ == '__main__':
    try:
        app.run(debug=True, host='0.0.0.0', port=5000)
    finally:
        stop_event.set()
