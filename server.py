from flask import Flask, jsonify, send_file, request
from threading import Thread
import time, datetime, json, os, csv
import requests

app = Flask(__name__)

DATA_FILE = 'iss_data.json'
RECORDS_PER_DAY = 1000
FETCH_INTERVAL = 86  # seconds (~1000 samples/day)

# Initialize data storage
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, 'r') as f:
        data = json.load(f)
else:
    data = {"days": {}}

def get_current_day():
    """Return string YYYY-MM-DD of day 1/2/3 based on first record date."""
    if "start_date" not in data:
        data["start_date"] = datetime.date.today().isoformat()
    start = datetime.date.fromisoformat(data["start_date"])
    today = datetime.date.today()
    day_number = (today - start).days + 1
    return f"Day {day_number}", today.isoformat()

def fetch_iss_data():
    """Background thread to fetch ISS data continuously."""
    while True:
        day_label, day_date = get_current_day()
        if day_label not in data["days"]:
            data["days"][day_label] = []

        # Only keep up to RECORDS_PER_DAY
        if len(data["days"][day_label]) >= RECORDS_PER_DAY:
            time.sleep(FETCH_INTERVAL)
            continue

        try:
            res = requests.get("https://api.wheretheiss.at/v1/satellites/25544", timeout=10)
            if res.status_code == 200:
                iss = res.json()
                record = {
                    "id": len(data["days"][day_label]) + 1,
                    "ts_utc": datetime.datetime.utcfromtimestamp(iss['timestamp']).strftime('%Y-%m-%d %H:%M:%S'),
                    "day": day_label,
                    "latitude": iss['latitude'],
                    "longitude": iss['longitude'],
                    "altitude": iss.get('altitude', None)
                }
                data["days"][day_label].append(record)
                # Save to file
                with open(DATA_FILE, 'w') as f:
                    json.dump(data, f, indent=2)
        except Exception as e:
            print("Error fetching ISS data:", e)

        time.sleep(FETCH_INTERVAL)

@app.route('/api/last3days')
def last3days():
    """Return last 3 days data for charts."""
    all_records = []
    for day_label in sorted(data["days"].keys()):
        all_records.extend(data["days"][day_label])
    return jsonify(all_records)

@app.route('/api/all-records')
def all_records():
    """Return records for selected day, default latest."""
    day = request.args.get('day')
    if not day:
        day = sorted(data["days"].keys())[-1] if data["days"] else ''
    records = data["days"].get(day, [])
    available_days = sorted(data["days"].keys())
    return jsonify({"records": records, "available_days": available_days})

@app.route('/api/download-csv')
def download_csv():
    """Download CSV for selected day or all days."""
    all_flag = request.args.get('all')
    day = request.args.get('day')
    filename = f"iss_data_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.csv"
    rows = []

    if all_flag:
        for day_label, recs in data["days"].items():
            rows.extend(recs)
    elif day and day in data["days"]:
        rows = data["days"][day]

    if not rows:
        return "No data available", 404

    # Create CSV
    with open(filename, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=["id","ts_utc","day","latitude","longitude","altitude"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    return send_file(filename, as_attachment=True)

if __name__ == '__main__':
    # Start background thread
    t = Thread(target=fetch_iss_data, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000)
