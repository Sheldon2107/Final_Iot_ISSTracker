# server.py — ISS collector with Malaysia time (UTC+8)
from flask import Flask, jsonify, send_from_directory, request
import requests
import csv
import os
from threading import Thread, Event
from datetime import datetime, timedelta, timezone
import time

app = Flask(__name__)

FETCH_INTERVAL = 60  # seconds
stop_event = Event()
MYT = timezone(timedelta(hours=8))  # Malaysia Time UTC+8
DATA_FOLDER = "data"  # folder to store daily CSVs
os.makedirs(DATA_FOLDER, exist_ok=True)

def safe_float(v):
    try:
        return float(v)
    except Exception:
        return None

def get_today_csv_path():
    today = datetime.now(MYT).strftime("%Y-%m-%d")
    return os.path.join(DATA_FOLDER, f"iss_{today}.csv")

def ensure_csv(file_path):
    if not os.path.exists(file_path):
        with open(file_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp','latitude','longitude','altitude','velocity','ts_myt'])

def fetch_and_save_iss_data():
    """Fetch ISS data once and save to today's CSV."""
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

            csv_file = get_today_csv_path()
            ensure_csv(csv_file)

            with open(csv_file, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([timestamp, latitude, longitude, altitude, velocity, ts_myt_excel])
            return True
    except Exception as e:
        print("Error fetching ISS data:", e)
    return False

def fetch_loop():
    """Background fetch loop (only for local)."""
    while not stop_event.is_set():
        fetch_and_save_iss_data()
        stop_event.wait(FETCH_INTERVAL)

# Start background thread locally
if os.environ.get("RENDER") is None:
    t = Thread(target=fetch_loop, daemon=True)
    t.start()

# --- Routes ---

@app.route("/api/fetch-now")
def api_fetch_now():
    success = fetch_and_save_iss_data()
    return jsonify({"success": success})

@app.route("/api/all-records")
def api_all_records():
    # List all CSV files in DATA_FOLDER
    csv_files = sorted([f for f in os.listdir(DATA_FOLDER) if f.startswith("iss_") and f.endswith(".csv")], reverse=True)
    all_data = []
    days = []

    for idx, file in enumerate(csv_files):
        day_label = file.replace("iss_", "").replace(".csv", "")
        days.append(day_label)

        path = os.path.join(DATA_FOLDER, file)
        with open(path, "r") as f:
            reader = csv.DictReader(f)
            rows = []
            for i, r in enumerate(reader):
                try:
                    ts = int(r.get("timestamp", 0))
                except:
                    continue
                dt = datetime.fromtimestamp(ts, tz=MYT)
                rows.append({
                    "id": i+1,
                    "timestamp_unix": ts,
                    "ts_myt": r.get("ts_myt", dt.strftime("%Y-%m-%d %H:%M:%S")),
                    "latitude": safe_float(r.get("latitude")),
                    "longitude": safe_float(r.get("longitude")),
                    "altitude": safe_float(r.get("altitude")),
                    "velocity": safe_float(r.get("velocity")),
                    "day": day_label
                })
            all_data.extend(rows)

    all_data_sorted = sorted(all_data, key=lambda x: x["timestamp_unix"], reverse=True)
    return jsonify({
        "records": all_data_sorted,
        "total": len(all_data_sorted),
        "page": 1,
        "per_page": len(all_data_sorted),
        "total_pages": 1,
        "available_days": days
    })

@app.route("/api/download")
def download_csv():
    day = request.args.get("day")
    if day:
        file_name = f"iss_{day}.csv"
        path = os.path.join(DATA_FOLDER, file_name)
        if os.path.exists(path):
            return send_from_directory(DATA_FOLDER, file_name, as_attachment=True)
        return f"CSV for {day} not found", 404
    else:
        # Combine all CSVs
        combined_file = os.path.join(DATA_FOLDER, "iss_all_days_combined.csv")
        with open(combined_file, "w", newline="") as f_out:
            writer = None
            for file in sorted(os.listdir(DATA_FOLDER)):
                if not file.startswith("iss_") or not file.endswith(".csv"):
                    continue
                with open(os.path.join(DATA_FOLDER, file), "r") as f_in:
                    reader = csv.reader(f_in)
                    header = next(reader)
                    if writer is None:
                        writer = csv.writer(f_out)
                        writer.writerow(header)
                    for row in reader:
                        writer.writerow(row)
        return send_from_directory(DATA_FOLDER, "iss_all_days_combined.csv", as_attachment=True)

@app.route("/")
def serve_index():
    return send_from_directory(".", "index.html")

@app.route("/database")
def serve_database():
    return send_from_directory(".", "database.html")

@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory(".", path)

if __name__ == "__main__":
    try:
        app.run(debug=True, host="0.0.0.0", port=5000)
    finally:
        stop_event.set()
