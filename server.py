import os
import csv
import json
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, send_from_directory

import requests

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- CONFIG ----
RECORDS_PER_DAY = 1000
TOTAL_DAYS = 3
FETCH_INTERVAL = 3  # seconds (use ~3s to respect rate limit)
DATA_FILE = os.path.join(BASE_DIR, 'iss_data.json')

# ---- DATA STORAGE ----
# Structure: { "day1": [...], "day2": [...], "day3": [...] }
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, 'r') as f:
        iss_data = json.load(f)
else:
    iss_data = {f"day{i+1}": [] for i in range(TOTAL_DAYS)}

# Helper to save data
def save_data():
    with open(DATA_FILE, 'w') as f:
        json.dump(iss_data, f, indent=2)

# ---- Determine current day (based on first deploy date) ----
DEPLOY_DATE = datetime.utcnow()
def get_current_day():
    delta = datetime.utcnow() - DEPLOY_DATE
    day_index = min(delta.days, TOTAL_DAYS - 1)
    return f"day{day_index + 1}"

# ---- ISS FETCH THREAD ----
def fetch_iss():
    while True:
        try:
            day_key = get_current_day()
            if len(iss_data[day_key]) < RECORDS_PER_DAY:
                res = requests.get("https://api.wheretheiss.at/v1/satellites/25544")
                if res.status_code == 200:
                    d = res.json()
                    record = {
                        "id": len(iss_data[day_key]) + 1,
                        "ts_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                        "day": day_key,
                        "latitude": d.get("latitude"),
                        "longitude": d.get("longitude"),
                        "altitude": d.get("altitude")
                    }
                    iss_data[day_key].append(record)
                    save_data()
            time.sleep(FETCH_INTERVAL)
        except Exception as e:
            print("Error fetching ISS data:", e)
            time.sleep(FETCH_INTERVAL)

threading.Thread(target=fetch_iss, daemon=True).start()

# ---- ROUTES ----
@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/database')
def database():
    return send_from_directory(BASE_DIR, 'database.html')

@app.route('/api/last3days')
def api_last3days():
    # Return combined data from all days
    all_records = []
    for day in iss_data.values():
        all_records.extend(day)
    return jsonify(all_records)

@app.route('/api/all-records')
def api_all_records():
    per_page = int(request.args.get('per_page', RECORDS_PER_DAY))
    day_param = request.args.get('day')
    available_days = [f"day{i+1}" for i in range(TOTAL_DAYS)]

    records = []
    if day_param and day_param in iss_data:
        records = iss_data[day_param][:per_page]
    else:
        # combine all days
        for day in available_days:
            records.extend(iss_data[day][:per_page])

    return jsonify({
        "available_days": available_days,
        "records": records
    })

@app.route('/api/download-csv')
def api_download_csv():
    day_param = request.args.get('day')
    all_param = request.args.get('all')
    filename = f"iss_data_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.csv"
    filepath = os.path.join(BASE_DIR, filename)

    rows = []
    if all_param == "1" or not day_param:
        for day in iss_data:
            rows.extend(iss_data[day])
    elif day_param in iss_data:
        rows.extend(iss_data[day_param])

    with open(filepath, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Record ID", "Timestamp UTC", "Day", "Latitude", "Longitude", "Altitude km"])
        for r in rows:
            writer.writerow([r["id"], r["ts_utc"], r["day"], r["latitude"], r["longitude"], r["altitude"]])

    return send_from_directory(BASE_DIR, filename, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
