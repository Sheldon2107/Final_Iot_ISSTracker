# server.py
from flask import Flask, jsonify, send_file, send_from_directory, request
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
    """Return label like 'Day 1' and the ISO date for today based on start_date."""
    if "start_date" not in data:
        # store start_date as ISO date so day numbering is stable across restarts
        data["start_date"] = datetime.date.today().isoformat()
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
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

        # Only keep up to RECORDS_PER_DAY for display/storage per requirement
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
                    "latitude": iss.get('latitude'),
                    "longitude": iss.get('longitude'),
                    "altitude": iss.get('altitude', None)
                }
                data["days"][day_label].append(record)
                # Save to file (persist across restarts)
                with open(DATA_FILE, 'w') as f:
                    json.dump(data, f, indent=2)
        except Exception as e:
            # keep background alive and log error
            print("Error fetching ISS data:", e)

        time.sleep(FETCH_INTERVAL)

# ---------------- API routes ----------------

@app.route('/api/last3days')
def last3days():
    """Return last 3 days data for charts (chronological)."""
    # sort day labels by their numeric part to preserve order Day 1, Day 2, ...
    day_labels = sorted(data["days"].keys(), key=lambda s: int(s.split()[1]) if s.split()[1].isdigit() else s)
    # take last 3 labels if more exist
    day_labels = day_labels[-3:]
    all_records = []
    for dl in day_labels:
        all_records.extend(data["days"].get(dl, []))
    return jsonify(all_records)

@app.route('/api/all-records')
def all_records():
    """Return records for selected day (or latest if none). Also return available_days."""
    per_page = int(request.args.get('per_page', RECORDS_PER_DAY))
    day = request.args.get('day')
    # determine available days in numeric order
    available_days = sorted(data["days"].keys(), key=lambda s: int(s.split()[1]) if s.split()[1].isdigit() else s)
    if not day:
        day = available_days[-1] if available_days else ''
    records = data["days"].get(day, [])[:per_page]
    return jsonify({"records": records, "available_days": available_days})

@app.route('/api/download-csv')
def download_csv():
    """Download CSV for selected day or all days."""
    all_flag = request.args.get('all') == '1' or request.args.get('all') == 'true'
    day = request.args.get('day')
    filename = f"iss_data_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.csv"
    rows = []

    if all_flag:
        # flatten all days in numeric order
        for dl in sorted(data["days"].keys(), key=lambda s: int(s.split()[1]) if s.split()[1].isdigit() else s):
            rows.extend(data["days"].get(dl, []))
    elif day and day in data["days"]:
        rows = data["days"][day]

    if not rows:
        return "No data available", 404

    # Create CSV on disk (small and temporary)
    with open(filename, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=["id","ts_utc","day","latitude","longitude","altitude"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    # send and let the platform / OS clean up later if you want; or optionally delete after send
    return send_file(filename, as_attachment=True)

# ---------------- Serve HTML in root (no templates folder) ----------------

@app.route('/')
def index():
    # serve index.html from the current working directory (root)
    return send_from_directory(os.getcwd(), 'index.html')

@app.route('/database')
def database():
    # serve database.html from the current working directory (root)
    return send_from_directory(os.getcwd(), 'database.html')

# Optional: serve any root-level static file (if you reference /somefile.js)
@app.route('/<path:filename>')
def root_static(filename):
    # but avoid exposing sensitive files - we only serve if file exists in cwd
    full = os.path.join(os.getcwd(), filename)
    if os.path.exists(full):
        return send_from_directory(os.getcwd(), filename)
    return "File not found", 404

# ---------------- Startup ----------------

if __name__ == '__main__':
    # Start background fetch thread
    t = Thread(target=fetch_iss_data, daemon=True)
    t.start()
    # run Flask (in production with gunicorn use Procfile: "web: gunicorn server:app")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
