from flask import Flask, jsonify, send_file
from flask_cors import CORS
import requests
import threading
import time
from datetime import datetime

app = Flask(__name__)
CORS(app)

# --- CONFIG ---
FETCH_INTERVAL = 1  # seconds
RECORDS_PER_DAY = 86400  # 1 record/sec * 60*60*24
TOTAL_DAYS = 3
TOTAL_RECORDS = RECORDS_PER_DAY * TOTAL_DAYS

# --- DATA STORE ---
data_points = []

# --- FETCH ISS DATA ---
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
                    "altitude": res["altitude"]  # km
                }
                data_points.append(record)
                if len(data_points) > TOTAL_RECORDS:
                    data_points.pop(0)
        except Exception as e:
            print("Fetch error:", e)
        time.sleep(FETCH_INTERVAL)

threading.Thread(target=fetch_iss_data, daemon=True).start()

# --- ROUTES ---
@app.route("/")
def dashboard():
    return send_file("database.html")

@app.route("/favicon.ico")
def favicon():
    return "", 204

@app.route("/api/last3days")
def get_last3days():
    return jsonify(data_points)

@app.route("/api/day/<int:day>")
def get_day(day):
    if day < 1 or day > TOTAL_DAYS:
        return jsonify({"error": "Invalid day"}), 400
    start_idx = (day-1)*RECORDS_PER_DAY
    end_idx = day*RECORDS_PER_DAY
    return jsonify(data_points[start_idx:end_idx])

# --- RUN ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
