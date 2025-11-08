from flask import Flask, jsonify, send_file, request
from flask_cors import CORS
import requests
import threading
import time
from datetime import datetime
import io
import csv

app = Flask(__name__)
CORS(app)

# --- CONFIG ---
FETCH_INTERVAL = 1  # seconds
RECORDS_PER_DAY = 86400  # 1 record/sec * 60*60*24
TOTAL_DAYS = 3
TOTAL_RECORDS = RECORDS_PER_DAY * TOTAL_DAYS

# --- GLOBAL DATA STORE ---
data_points = []

# --- FUNCTION TO FETCH ISS DATA ---
def fetch_iss_data():
    while True:
        try:
            response = requests.get("https://api.wheretheiss.at/v1/satellites/25544")
            if response.status_code == 200:
                res = response.json()
                record = {
                    "ts_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    "latitude": res["latitude"],
                    "longitude": res["longitude"],
                    "altitude": res["altitude"]  # in km
                }
                data_points.append(record)

                # Keep only the last 3 days (rolling buffer)
                if len(data_points) > TOTAL_RECORDS:
                    data_points.pop(0)

            else:
                print("Error fetching ISS data:", response.status_code)

        except Exception as e:
            print("Exception during fetch:", e)

        time.sleep(FETCH_INTERVAL)

# --- START BACKGROUND THREAD ---
threading.Thread(target=fetch_iss_data, daemon=True).start()

# --- API ENDPOINTS ---

@app.route("/api/last3days", methods=["GET"])
def get_last_3_days():
    """Returns all 3 days of data currently in memory"""
    return jsonify(data_points)

@app.route("/api/day/<int:day>", methods=["GET"])
def get_day(day):
    """Returns data for a specific day (1,2,3)"""
    if day < 1 or day > TOTAL_DAYS:
        return jsonify({"error": "Invalid day"}), 400

    start_idx = max(0, (day - 1) * RECORDS_PER_DAY)
    end_idx = min(len(data_points), day * RECORDS_PER_DAY)
    return jsonify(data_points[start_idx:end_idx])

@app.route("/api/download", methods=["GET"])
def download_csv():
    """Download current data as CSV. Optional ?day=1,2,3"""
    day = request.args.get("day", type=int)
    rows = data_points

    if day:
        if day < 1 or day > TOTAL_DAYS:
            return jsonify({"error": "Invalid day"}), 400
        start_idx = max(0, (day - 1) * RECORDS_PER_DAY)
        end_idx = min(len(data_points), day * RECORDS_PER_DAY)
        rows = data_points[start_idx:end_idx]

    # Prepare CSV in memory
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["ts_utc", "latitude", "longitude", "altitude"])
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"iss_data{'_day'+str(day) if day else ''}.csv"
    )

# --- RUN SERVER (for local testing only; Render uses Gunicorn) ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)


