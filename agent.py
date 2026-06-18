import os
import json
import time
import sqlite3
import logging
import asyncio
import requests
import threading
from datetime import datetime

# Import the existing OPC UA script
from inoex import read_machine_data

# ── Configuration & Setup ────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "buffer.db")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(BASE_DIR, "agent.log")),
        logging.StreamHandler()
    ]
)

# Global state for machines dynamically fetched from ERPNext
active_machines = []
machines_lock = threading.Lock()

def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(
            f"Configuration file not found at '{CONFIG_PATH}'. "
            "Please copy 'config.json.example' to 'config.json' and fill in your ERPNext credentials."
        )
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

config = load_config()

# ── Database Initialization ──────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS extruder_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            machine_name TEXT NOT NULL,
            data_json TEXT NOT NULL,
            status TEXT DEFAULT 'pending'
        )
    """)
    conn.commit()
    conn.close()

# ── API Helpers ──────────────────────────────────────────────────────────────
def get_headers():
    return {
        "Authorization": f"token {config['api_key']}:{config['api_secret']}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

def update_active_machines():
    """Periodically fetches the active machines from ERPNext."""
    url = f"{config['erpnext_url']}/api/resource/Production Machine"
    params = {
        "filters": '[["is_active","=",1]]',
        "fields": '["name", "machine_ip"]'
    }
    try:
        response = requests.get(url, headers=get_headers(), params=params, timeout=10)
        response.raise_for_status()
        machines = response.json().get("data", [])
        
        with machines_lock:
            global active_machines
            active_machines = machines
            
        logging.info(f"Updated active machines list: {len(active_machines)} machines found.")
    except Exception as e:
        logging.error(f"Failed to fetch active machines from ERPNext: {e}")

# ── The Fetcher (Machine -> SQLite) ──────────────────────────────────────────
def fetch_loop():
    """Polls machines every 60 seconds and saves to SQLite."""
    while True:
        cycle_start = time.time()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with machines_lock:
            machines_to_poll = list(active_machines)
            
        if not machines_to_poll:
            logging.warning("No active machines to poll. Waiting for config sync...")
        
        for machine in machines_to_poll:
            machine_name = machine.get("name")
            machine_ip = machine.get("machine_ip")
            
            try:
                # Poll OPC UA
                data = asyncio.run(read_machine_data(machine_ip))
                if not data:
                    logging.debug(f"Machine {machine_name} returned no data.")
                    continue
                
                # Save to local SQLite buffer
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO extruder_events (timestamp, machine_name, data_json) VALUES (?, ?, ?)",
                    (now_str, machine_name, json.dumps(data))
                )
                conn.commit()
                conn.close()
                logging.debug(f"Buffered data for {machine_name} at {now_str}")
                
            except Exception as e:
                logging.error(f"Error fetching data from {machine_name}: {e}")
        
        # Sleep until the next minute mark
        elapsed = time.time() - cycle_start
        sleep_time = max(0, 60 - elapsed)
        time.sleep(sleep_time)

# ── The Forwarder (SQLite -> ERPNext) ────────────────────────────────────────
def forward_loop():
    """Continuously checks SQLite for pending events and pushes them to ERPNext."""
    url = f"{config['erpnext_url']}/api/method/nl_apex.apex_piping.overrides.extruder_session.receive_extruder_payload"
    
    while True:
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            # Fetch up to 50 pending records
            cursor.execute("SELECT id, timestamp, machine_name, data_json FROM extruder_events WHERE status='pending' ORDER BY timestamp ASC LIMIT 50")
            rows = cursor.fetchall()
            
            if not rows:
                conn.close()
                time.sleep(10)  # Wait before checking again if empty
                continue
                
            payload = []
            row_ids = []
            
            for row in rows:
                row_ids.append(row[0])
                payload.append({
                    "timestamp": row[1],
                    "machine": row[2],
                    "data": json.loads(row[3])
                })
                
            # Try pushing to ERPNext
            response = requests.post(
                url, 
                headers=get_headers(), 
                json={"events": payload},
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()
            if result.get("message", {}).get("status") == "success":
                # Mark as synced (or delete them to save space)
                # We will delete them to keep SQLite small
                placeholders = ','.join('?' * len(row_ids))
                cursor.execute(f"DELETE FROM extruder_events WHERE id IN ({placeholders})", row_ids)
                conn.commit()
                logging.info(f"Successfully pushed {len(row_ids)} events to ERPNext.")
            else:
                logging.error(f"ERPNext returned unexpected response: {result}")
                time.sleep(15) # Wait before retry
                
            conn.close()
            
        except requests.exceptions.RequestException as e:
            logging.error(f"Network error pushing to ERPNext (will retry): {e}")
            time.sleep(15) # Wait before retry
        except Exception as e:
            logging.error(f"Unexpected error in Forwarder loop: {e}")
            time.sleep(15) # Wait before retry

# ── Background Sync Loop ─────────────────────────────────────────────────────
def sync_machines_loop():
    """Keeps the active machines list updated every 15 minutes."""
    while True:
        update_active_machines()
        time.sleep(900) # 15 minutes

# ── Main Entrypoint ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.info("Starting Extruder Edge Agent...")
    init_db()
    
    # Do an initial sync before starting loops
    update_active_machines()
    
    # Start threads
    t_sync = threading.Thread(target=sync_machines_loop, daemon=True)
    t_fetch = threading.Thread(target=fetch_loop, daemon=True)
    t_forward = threading.Thread(target=forward_loop, daemon=True)
    
    t_sync.start()
    t_fetch.start()
    t_forward.start()
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Shutting down Edge Agent.")
