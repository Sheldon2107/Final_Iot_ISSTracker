# server.py — ISS collector with Malaysian time (UTC+8)
from flask import Flask, jsonify, send_from_directory, request
import requests
import csv
import os
from threading import Thread, Event
from datetime import datetime, timedelta, timezone
import time

app = Flask(__name__)
DATA_FILE = 'iss_data.csv'
FETCH_INTERVAL = 60  # seconds
stop_event = Event()
MYT = timezone(timedelta(hours=8))  # Malaysia Time UTC+8

# Ensure CSV file exists with header
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'latitude', 'longitude', 'altitude', 'velocity', 'ts_myt'])


def safe_float(v):
    try:
        return float(v)
    except Exception:
        return None


def fetch_iss_data():
    while not stop_event.is_set():
        try:
            res = requests.get('https://api.wheretheiss.at/v1/satellites/25544', timeout=8)
            if res.status_code == 200:
                d = res.json()
                timestamp = int(d.get('timestamp', time.time()))
                latitude = safe_float(d.get('latitude'))
                longitude = safe_float(d.get('longitude'))
                altitude = safe_float(d.get('altitude'))
                velocity = safe_float(d.get('velocity'))
                
                # Malaysian time in ISO format for CSV
                ts_myt = datetime.fromtimestamp(timestamp, tz=MYT).strftime('%Y-%m-%d %H:%M:%S')
                # Prepend single quote for Excel-safe text
                ts_myt_excel = "'" + ts_myt
                
                with open(DATA_FILE, 'a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([timestamp, latitude, longitude, altitude, velocity, ts_myt_excel])
                    
                print(f"✅ Fetched ISS data: {ts_myt}")
        except Exception as e:
            print("❌ Error fetching ISS data:", e)
        
        stop_event.wait(FETCH_INTERVAL)


# Start background fetching thread
t = Thread(target=fetch_iss_data, daemon=True)
t.start()


# ✅ FIXED: This endpoint now returns ALL records for database.html
@app.route('/api/preview')
def api_preview():
    """Returns all records from the CSV file for the database viewer"""
    records = []
    
    if not os.path.exists(DATA_FILE):
        return jsonify({'records': []})
    
    try:
        with open(DATA_FILE, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
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
                except Exception as e:
                    print(f"⚠️ Skipping invalid row: {e}")
                    continue
        
        print(f"📊 Returning {len(records)} total records to database viewer")
        return jsonify({'records': records})
        
    except Exception as e:
        print(f"❌ Error reading CSV: {e}")
        return jsonify({'records': [], 'error': str(e)})


# ✅ NEW: Separate endpoint for index.html (dashboard) - returns recent data only
@app.route('/api/dashboard')
def api_dashboard():
    """Returns recent records for the dashboard/map view"""
    records = []
    
    if not os.path.exists(DATA_FILE):
        return jsonify({'records': []})
    
    try:
        with open(DATA_FILE, 'r') as f:
            reader = csv.DictReader(f)
            all_rows = list(reader)
            
            # Get last 500 records for performance
            recent_rows = all_rows[-500:] if len(all_rows) > 500 else all_rows
            
            for row in recent_rows:
                try:
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
                except Exception:
                    continue
        
        return jsonify({'records': records})
        
    except Exception as e:
        print(f"❌ Error reading CSV: {e}")
        return jsonify({'records': [], 'error': str(e)})


@app.route('/api/all-records')
def api_all_records():
    """Advanced endpoint with pagination and filtering"""
    if not os.path.exists(DATA_FILE):
        return jsonify({
            "records": [], "total": 0, "page": 1, "per_page": 1, 
            "total_pages": 1, "available_days": []
        })

    try:
        page = max(1, int(request.args.get('page', 1)))
    except Exception:
        page = 1
    
    try:
        per_page = min(5000, max(1, int(request.args.get('per_page', 1000))))
    except Exception:
        per_page = 1000
    
    day_filter = request.args.get('day', None)
    
    rows = []
    with open(DATA_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for i, r in enumerate(reader):
            try:
                ts = int(r.get('timestamp', 0))
            except Exception:
                continue
            
            dt = datetime.fromtimestamp(ts, tz=MYT)
            day = dt.strftime('%Y-%m-%d')
            
            rows.append({
                "id": i + 1,
                "timestamp_unix": ts,
                "ts_myt": r.get('ts_myt', dt.strftime('%Y-%m-%d %H:%M:%S')),
                "latitude": safe_float(r.get('latitude')),
                "longitude": safe_float(r.get('longitude')),
                "altitude": safe_float(r.get('altitude')),
                "velocity": safe_float(r.get('velocity')),
                "day": day
            })
    
    rows_sorted = sorted(rows, key=lambda x: x['timestamp_unix'], reverse=True)
    days = sorted(list({r['day'] for r in rows}), reverse=True)
    
    filtered = [r for r in rows_sorted if (day_filter is None or r['day'] == day_filter)]
    total = len(filtered)
    total_pages = (total + per_page - 1) // per_page if total else 1
    
    start = (page - 1) * per_page
    end = start + per_page
    page_records = filtered[start:end]
    
    return jsonify({
        "records": page_records,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "available_days": days
    })


# Serve frontend files
@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')


@app.route('/database')
def serve_database():
    return send_from_directory('.', 'database.html')


@app.route('/api/download')
def download_csv():
    if os.path.exists(DATA_FILE):
        return send_from_directory('.', DATA_FILE, as_attachment=True)
    return "CSV file not found", 404


@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)


if __name__ == '__main__':
    try:
        print("🚀 Starting ISS Tracker Server...")
        print(f"📍 Data file: {DATA_FILE}")
        print(f"⏱️  Fetch interval: {FETCH_INTERVAL}s")
        print(f"🌏 Timezone: MYT (UTC+8)")
        app.run(debug=True, host='0.0.0.0', port=5000)
    finally:
        stop_event.set()
