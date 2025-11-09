from flask import Flask, jsonify, send_file, request
import requests
from datetime import datetime, timedelta
import threading
import csv
import io

app = Flask(__name__)

# --- Configuration ---
RECORD_INTERVAL = 1  # seconds
MAX_RECORDS_PER_DAY = 1000

# --- In-memory storage ---
# Structure: {'YYYY-MM-DD': [records]}
data_store = {}

# --- Helper functions ---
def fetch_iss_data():
    try:
        res = requests.get('https://api.wheretheiss.at/v1/satellites/25544')
        if res.status_code == 200:
            d = res.json()
            ts_utc = datetime.utcfromtimestamp(d['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
            record = {
                'id': None,  # Will assign below
                'ts_utc': ts_utc,
                'day': None,  # Will assign below
                'latitude': d['latitude'],
                'longitude': d['longitude'],
                'altitude': d['altitude']
            }

            # Determine current UTC day
            today_str = datetime.utcnow().strftime('%Y-%m-%d')
            if today_str not in data_store:
                data_store[today_str] = []

            # Assign ID and day
            record['id'] = len(data_store[today_str]) + 1
            # Day number: first recorded day = Day 1
            day_num = len(data_store)
            record['day'] = f"Day {day_num}"

            # Append record
            data_store[today_str].append(record)

            # Keep only MAX_RECORDS_PER_DAY for display purposes
            if len(data_store[today_str]) > MAX_RECORDS_PER_DAY:
                data_store[today_str] = data_store[today_str][:MAX_RECORDS_PER_DAY]

    except Exception as e:
        print("Error fetching ISS data:", e)

def start_fetching():
    def run():
        while True:
            fetch_iss_data()
            threading.Event().wait(RECORD_INTERVAL)
    thread = threading.Thread(target=run)
    thread.daemon = True
    thread.start()

# --- API Endpoints ---
@app.route('/api/last3days')
def last3days():
    # Return last 3 days combined in a list
    sorted_days = sorted(data_store.keys())
    result = []
    for day in sorted_days[-3:]:
        result.extend(data_store[day])
    return jsonify(result)

@app.route('/api/all-records')
def all_records():
    per_page = int(request.args.get('per_page', MAX_RECORDS_PER_DAY))
    day = request.args.get('day', None)
    sorted_days = sorted(data_store.keys())

    available_days = [f"Day {i+1}" for i in range(len(sorted_days))]

    if day:
        # Find the date string for this day
        day_index = int(day.split(' ')[1]) - 1
        if day_index < len(sorted_days):
            records = data_store[sorted_days[day_index]][:per_page]
        else:
            records = []
    else:
        # Default: latest day
        records = data_store[sorted_days[-1]][:per_page] if sorted_days else []

    return jsonify({'records': records, 'available_days': available_days})

@app.route('/api/download-csv')
def download_csv():
    all_flag = request.args.get('all', '0') == '1'
    day = request.args.get('day', None)
    sorted_days = sorted(data_store.keys())

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Record ID', 'Timestamp (UTC)', 'Day', 'Latitude', 'Longitude', 'Altitude (km)'])

    if all_flag:
        for d in sorted_days:
            for r in data_store[d]:
                writer.writerow([r['id'], r['ts_utc'], r['day'], r['latitude'], r['longitude'], r['altitude']])
    elif day:
        day_index = int(day.split(' ')[1]) - 1
        if day_index < len(sorted_days):
            for r in data_store[sorted_days[day_index]]:
                writer.writerow([r['id'], r['ts_utc'], r['day'], r['latitude'], r['longitude'], r['altitude']])
    else:
        # default latest day
        if sorted_days:
            for r in data_store[sorted_days[-1]]:
                writer.writerow([r['id'], r['ts_utc'], r['day'], r['latitude'], r['longitude'], r['altitude']])

    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode('utf-8')),
                     mimetype='text/csv',
                     as_attachment=True,
                     download_name='iss_data.csv')

# --- Routes for HTML ---
@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/database')
def database():
    return app.send_static_file('database.html')

# --- Main ---
if __name__ == '__main__':
    start_fetching()
    app.run(host='0.0.0.0', port=5000, debug=True)
