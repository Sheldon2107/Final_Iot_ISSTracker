# server.py — ISS collector with Malaysian time (UTC+8)
from flask import Flask, jsonify, send_from_directory, request
import requests
import csv, os, time
from threading import Thread, Event
from datetime import datetime, timedelta, timezone

app = Flask(__name__)
DATA_FILE = 'iss_data.csv'
FETCH_INTERVAL = 60
stop_event = Event()

MYT = timezone(timedelta(hours=8))  # Malaysia Time UTC+8

# Ensure CSV file exists
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp','latitude','longitude','altitude','velocity','ts_myt'])

def safe_float(v):
    try: return float(v)
    except: return None

def fetch_and_save_iss_data():
    try:
        res = requests.get('https://api.wheretheiss.at/v1/satellites/25544', timeout=8)
        if res.status_code == 200:
            d = res.json()
            ts = int(d.get('timestamp', time.time()))
            lat = safe_float(d.get('latitude'))
            lon = safe_float(d.get('longitude'))
            alt = safe_float(d.get('altitude'))
            vel = safe_float(d.get('velocity'))
            ts_myt = datetime.fromtimestamp(ts, tz=MYT).strftime('%Y-%m-%d %H:%M:%S')
            ts_myt_excel = "'" + ts_myt
            with open(DATA_FILE,'a',newline='') as f:
                writer = csv.writer(f)
                writer.writerow([ts, lat, lon, alt, vel, ts_myt_excel])
            return True
    except Exception as e:
        print("ISS fetch error:", e)
    return False

def fetch_loop():
    while not stop_event.is_set():
        fetch_and_save_iss_data()
        stop_event.wait(FETCH_INTERVAL)

# Run background thread locally
if os.environ.get("RENDER") is None:
    t = Thread(target=fetch_loop, daemon=True)
    t.start()

# Manual fetch
@app.route('/api/fetch-now')
def api_fetch_now():
    return jsonify({'success': fetch_and_save_iss_data()})

# Preview by day_index
@app.route('/api/preview')
def api_preview():
    try:
        day_index = int(request.args.get('day_index',0))
    except: day_index = 0

    records = []
    if not os.path.exists(DATA_FILE): return jsonify({'records':[]})

    with open(DATA_FILE,'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        if not rows: return jsonify({'records':[]})
        first_ts = int(rows[0]['timestamp'])
        start_day = datetime.fromtimestamp(first_ts,tz=MYT).replace(hour=0,minute=0,second=0,microsecond=0) + timedelta(days=day_index)
        end_day = start_day + timedelta(days=1)

        for r in rows:
            try: ts = int(r['timestamp'])
            except: continue
            dt = datetime.fromtimestamp(ts,tz=MYT)
            if start_day <= dt < end_day:
                records.append({
                    'timestamp': ts,
                    'ts_myt': r.get('ts_myt', dt.strftime('%Y-%m-%d %H:%M:%S')),
                    'latitude': safe_float(r.get('latitude')),
                    'longitude': safe_float(r.get('longitude')),
                    'altitude': safe_float(r.get('altitude')),
                    'velocity': safe_float(r.get('velocity'))
                })
    return jsonify({'records':records})

# All records (for database page)
@app.route('/api/all-records')
def api_all_records():
    if not os.path.exists(DATA_FILE):
        return jsonify({"records":[],"total":0,"available_days":[]})

    rows = []
    with open(DATA_FILE,'r') as f:
        reader = csv.DictReader(f)
        for i,r in enumerate(reader):
            try: ts = int(r.get('timestamp',0))
            except: continue
            dt = datetime.fromtimestamp(ts,tz=MYT)
            day = dt.strftime('%Y-%m-%d')
            rows.append({
                "id": i+1,
                "timestamp_unix": ts,
                "ts_myt": r.get('ts_myt', dt.strftime('%Y-%m-%d %H:%M:%S')),
                "latitude": safe_float(r.get('latitude')),
                "longitude": safe_float(r.get('longitude')),
                "altitude": safe_float(r.get('altitude')),
                "velocity": safe_float(r.get('velocity')),
                "day": day
            })
    return jsonify({
        "records": sorted(rows,key=lambda x:x['timestamp_unix']),
        "total": len(rows),
        "available_days": sorted(list({r['day'] for r in rows}))
    })

@app.route('/')
def serve_index(): return send_from_directory('.', 'index.html')
@app.route('/database') def serve_db(): return send_from_directory('.', 'database.html')
@app.route('/api/download')
def download_csv(): return send_from_directory('.', DATA_FILE, as_attachment=True) if os.path.exists(DATA_FILE) else ("CSV not found",404)
@app.route('/<path:path>')
def serve_static(path): return send_from_directory('.', path)

if __name__ == '__main__':
    try: app.run(debug=True,host='0.0.0.0',port=5000)
    finally: stop_event.set()
