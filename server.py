import os
import time
import sqlite3
import logging
import requests
import csv
import io
from datetime import datetime, timedelta, timezone
from threading import Thread, Event
from flask import Flask, jsonify, send_file, request, Response
from flask_cors import CORS

# Force UTC timezone
os.environ['TZ'] = 'UTC'
if hasattr(time, 'tzset'):
    time.tzset()

# ---------- Configuration ----------
DB_PATH = os.environ.get("DB_PATH", "iss_data.db")
API_URL = os.environ.get("ISS_API_URL", "https://api.wheretheiss.at/v1/satellites/25544")
# Default fetch interval (seconds)
FETCH_INTERVAL = int(os.environ.get("FETCH_INTERVAL_SEC", "1"))
SAMPLE_DATA = os.environ.get("SAMPLE_DATA", "0") == "1"
PORT = int(os.environ.get("PORT", "10000"))

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("iss-tracker")

# ---------- Flask app ----------
app = Flask(__name__, static_folder=".")
CORS(app)

# ---------- DB utilities ----------
def get_conn():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
      CREATE TABLE IF NOT EXISTS iss_positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        altitude REAL,
        timestamp TEXT NOT NULL,
        day TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
      )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON iss_positions(timestamp)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_day ON iss_positions(day)")
    conn.commit()
    conn.close()
    logger.info("Database initialized at %s", DB_PATH)

def save_position(latitude, longitude, altitude, ts_utc):
    day = ts_utc.split(" ")[0]
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
      INSERT INTO iss_positions (latitude, longitude, altitude, timestamp, day)
      VALUES (?, ?, ?, ?, ?)
    """, (latitude, longitude, altitude, ts_utc, day))
    conn.commit()
    conn.close()

def get_record_count():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM iss_positions")
    count = cur.fetchone()[0]
    conn.close()
    return count

# ---------- Fetching ISS ----------
def parse_wther_resp(data):
    ts = datetime.utcfromtimestamp(int(data.get("timestamp", time.time())))
    return {
        "latitude": float(data.get("latitude")),
        "longitude": float(data.get("longitude")),
        "altitude": float(data.get("altitude", 0.0)),
        "ts_utc": ts.strftime("%Y-%m-%d %H:%M:%S")
    }

def parse_open_notify(data):
    ts = datetime.utcfromtimestamp(int(data.get("timestamp", time.time())))
    pos = data.get("iss_position", {})
    return {
        "latitude": float(pos.get("latitude")),
        "longitude": float(pos.get("longitude")),
        "altitude": None,
        "ts_utc": ts.strftime("%Y-%m-%d %H:%M:%S")
    }

def fetch_iss_position():
    try:
        resp = requests.get(API_URL, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("iss_position"):
            return parse_open_notify(data)
        else:
            return parse_wther_resp(data)
    except Exception as e:
        logger.warning("Fetch error: %s", e)
        return None

# ---------- Background collection ----------
stop_event = Event()
def background_loop():
    while not stop_event.is_set():
        pos = fetch_iss_position()
        if pos:
            save_position(pos["latitude"], pos["longitude"], pos["altitude"], pos["ts_utc"])
            count = get_record_count()
            if count and count % 3600 == 0:
                logger.info("Collected %d records (~%0.2f days)", count, count / 86400.0)
        stop_event.wait(FETCH_INTERVAL)

# ---------- API endpoints ----------
@app.route("/")
def index():
    try:
        return send_file("index.html")
    except Exception:
        return "ISS Tracker API", 200

@app.route("/database")
def database_view():
    try:
        return send_file("database.html")
    except Exception:
        return "Database viewer not found", 404

@app.route("/api/current")
def api_current():
    pos = fetch_iss_position()
    if pos:
        try:
            save_position(pos["latitude"], pos["longitude"], pos["altitude"], pos["ts_utc"])
        except Exception:
            pass
        return jsonify(pos)
    # fallback to last saved
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT latitude, longitude, altitude, timestamp AS ts_utc, day FROM iss_positions ORDER BY timestamp DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if row:
        return jsonify({
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "altitude": row["altitude"],
            "ts_utc": row["ts_utc"],
            "day": row["day"]
        })
    return jsonify({"error": "No data available"}), 404

@app.route("/api/preview")
def api_preview():
    """Returns recent records for the dashboard - limit to last 500 for performance"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
          SELECT latitude, longitude, altitude, timestamp AS ts_utc, day
          FROM iss_positions
          ORDER BY timestamp DESC
          LIMIT 500
        """)
        rows = cur.fetchall()
        conn.close()
        
        # Reverse to get chronological order
        records = [{
            "latitude": r["latitude"],
            "longitude": r["longitude"],
            "altitude": r["altitude"],
            "ts_utc": r["ts_utc"],
            "day": r["day"]
        } for r in reversed(rows)]
        
        return jsonify({"records": records})
    except Exception as e:
        logger.exception("Error in /api/preview: %s", e)
        return jsonify({"error": "Unable to fetch preview data"}), 500

@app.route("/api/all-records")
def api_all_records():
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(5000, max(1, int(request.args.get("per_page", 1000))))
        day_filter = request.args.get("day", None)
        conn = get_conn()
        cur = conn.cursor()

        if day_filter:
            cur.execute("SELECT COUNT(*) FROM iss_positions WHERE day = ?", (day_filter,))
            total = cur.fetchone()[0]
            cur.execute("SELECT DISTINCT day FROM iss_positions ORDER BY day DESC")
            days = [r["day"] for r in cur.fetchall()]
            cur.execute("""
              SELECT id, latitude, longitude, altitude, timestamp AS ts_utc, day
              FROM iss_positions
              WHERE day = ?
              ORDER BY timestamp DESC
              LIMIT ? OFFSET ?
            """, (day_filter, per_page, (page - 1) * per_page))
        else:
            cur.execute("SELECT COUNT(*) FROM iss_positions")
            total = cur.fetchone()[0]
            cur.execute("SELECT DISTINCT day FROM iss_positions ORDER BY day DESC")
            days = [r["day"] for r in cur.fetchall()]
            cur.execute("""
              SELECT id, latitude, longitude, altitude, timestamp AS ts_utc, day
              FROM iss_positions
              ORDER BY timestamp DESC
              LIMIT ? OFFSET ?
            """, (per_page, (page - 1) * per_page))

        rows = cur.fetchall()
        conn.close()

        records = [{
            "id": r["id"],
            "latitude": r["latitude"],
            "longitude": r["longitude"],
            "altitude": r["altitude"],
            "ts_utc": r["ts_utc"],
            "day": r["day"]
        } for r in rows]

        total_pages = (total + per_page - 1) // per_page if total else 1
        return jsonify({
            "records": records,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "available_days": days
        })
    except Exception as e:
        logger.exception("Error in /api/all-records: %s", e)
        return jsonify({"error": "Unable to fetch records"}), 500

@app.route("/api/download")
def api_download_csv():
    """Download all ISS position data as CSV"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
          SELECT id, latitude, longitude, altitude, timestamp, day, created_at
          FROM iss_positions
          ORDER BY timestamp ASC
        """)
        rows = cur.fetchall()
        conn.close()
        
        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow(['ID', 'Latitude', 'Longitude', 'Altitude (km)', 'Timestamp (UTC)', 'Day', 'Created At'])
        
        # Write data
        for row in rows:
            writer.writerow([
                row["id"],
                row["latitude"],
                row["longitude"],
                row["altitude"],
                row["timestamp"],
                row["day"],
                row["created_at"]
            ])
        
        output.seek(0)
        
        # Generate filename with current date
        filename = f"iss_positions_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename={filename}'}
        )
    except Exception as e:
        logger.exception("Error in /api/download: %s", e)
        return jsonify({"error": "Unable to generate CSV"}), 500

@app.route("/api/stats")
def api_stats():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM iss_positions")
        total = cur.fetchone()[0]
        cur.execute("SELECT day, COUNT(*) AS cnt FROM iss_positions GROUP BY day ORDER BY day DESC")
        per_day = {r["day"]: r["cnt"] for r in cur.fetchall()}
        
        # Get date range
        cur.execute("SELECT MIN(timestamp) as first, MAX(timestamp) as last FROM iss_positions")
        date_range = cur.fetchone()
        conn.close()
        
        total_hours = total / 3600.0
        total_days = total_hours / 24.0
        
        return jsonify({
            "total_records": total,
            "total_hours": round(total_hours, 2),
            "total_days": round(total_days, 2),
            "records_per_day": per_day,
            "collection_interval_seconds": FETCH_INTERVAL,
            "first_record": date_range["first"] if date_range["first"] else None,
            "last_record": date_range["last"] if date_range["last"] else None
        })
    except Exception as e:
        logger.exception("Error in /api/stats: %s", e)
        return jsonify({"error": "Unable to fetch stats"}), 500

# ---------- startup ----------
if __name__ == "__main__":
    logger.info("Starting ISS Tracker (DB=%s) FETCH_INTERVAL=%ss", DB_PATH, FETCH_INTERVAL)
    init_database()

    if SAMPLE_DATA and get_record_count() == 0:
        now = datetime.utcnow()
        conn = get_conn()
        cur = conn.cursor()
        logger.info("Generating sample data (1000 records)...")
        for i in range(1000):
            tp = now - timedelta(seconds=i)
            cur.execute("""
              INSERT INTO iss_positions (latitude, longitude, altitude, timestamp, day)
              VALUES (?, ?, ?, ?, ?)
            """, (45.0 + (i % 180) - 90, -180.0 + (i * 0.72) % 360, 408.0 + (i % 20) * 0.3, tp.strftime("%Y-%m-%d %H:%M:%S"), tp.strftime("%Y-%m-%d")))
        conn.commit()
        conn.close()
        logger.info("Sample data generated")

    # start background collector thread (daemon)
    t = Thread(target=background_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=PORT, debug=False)
