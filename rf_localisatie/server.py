# server.py — Centrale Raspberry (Pi #1) met ECHTE Wi-Fi RSSI
from flask import Flask, render_template, jsonify
import socket, threading, json, time, math, subprocess, re, statistics

# ========== CONFIG ==========
CENTRAL_ID   = 1                      # centrale is Pi #1
CENTRAL_POS  = (2.5, 4.0)             # pas aan jouw opstelling
UDP_PORT     = 5005

# Stel HIER je hotspot in (BSSID voorkeur; SSID kan ook)
CENTRAL_TARGET_BSSID = "aa:bb:cc:dd:ee:ff"   # <-- zet hier jouw BSSID (lower/upper maakt niet uit)
CENTRAL_TARGET_SSID  = None                  # of bv. "NoortjeHotspot"

WLAN_IFACE = "wlan0"                 # Wi-Fi interface op de Pi

# Path-loss model: rssi ≈ A0 - 10*n*log10(d)
A0 = -45.0      # RSSI op 1 m (dBm) — KALIBREER!
N  = 2.2        # padverlies exponent (2 buiten; 2.2–3 binnen)
# ============================

app = Flask(__name__)
# latest_data[id] = {"id":int, "pos":[x,y], "rssi":float, "ts":float}
latest_data = {}

# ---------- Wi-Fi RSSI helpers ----------
def _iw_scan():
    # Kan 1–2 s duren; roep dit niet té vaak op.
    out = subprocess.check_output(["iw", "dev", WLAN_IFACE, "scan"], stderr=subprocess.STDOUT)
    return out.decode(errors="ignore")

def _parse_cells(iw_text):
    cells = []
    blocks = re.split(r"\nBSS ", iw_text)
    for b in blocks[1:]:
        m_bssid = re.match(r"([0-9a-f:]{17})", b, re.I)
        if not m_bssid:
            continue
        bssid = m_bssid.group(1).lower()
        m_sig = re.search(r"\nsignal:\s*(-?\d+(?:\.\d+)?)\s*dBm", b)
        rssi = float(m_sig.group(1)) if m_sig else None
        m_ssid = re.search(r"\n\tSSID:\s*(.+)", b)
        ssid = m_ssid.group(1).strip() if m_ssid else None
        cells.append({"bssid": bssid, "ssid": ssid, "rssi": rssi})
    return cells

def read_wifi_rssi_by_bssid(target_bssid, samples=2, interval=0.4):
    target_bssid = target_bssid.lower()
    vals = []
    for _ in range(samples):
        iw_text = _iw_scan()
        cells = _parse_cells(iw_text)
        hit = next((c for c in cells if c["bssid"] == target_bssid and c["rssi"] is not None), None)
        if hit:
            vals.append(hit["rssi"])
        time.sleep(interval)
    return float(statistics.median(vals)) if vals else None

def read_wifi_rssi_by_ssid(target_ssid, samples=2, interval=0.4):
    target_ssid = target_ssid.strip()
    vals = []
    for _ in range(samples):
        iw_text = _iw_scan()
        cells = _parse_cells(iw_text)
        same = [c for c in cells if c["ssid"] == target_ssid and c["rssi"] is not None]
        if same:
            vals.append(max(c["rssi"] for c in same))
        time.sleep(interval)
    return float(statistics.median(vals)) if vals else None

# simpele cache zodat we niet elke seconde een zware scan doen
_last_scan_ts = 0.0
_last_rssi = None
def get_local_rssi():
    global _last_scan_ts, _last_rssi
    now = time.time()
    if now - _last_scan_ts < 1.5 and _last_rssi is not None:
        return _last_rssi
    rssi = None
    if CENTRAL_TARGET_BSSID:
        rssi = read_wifi_rssi_by_bssid(CENTRAL_TARGET_BSSID, samples=2, interval=0.3)
    elif CENTRAL_TARGET_SSID:
        rssi = read_wifi_rssi_by_ssid(CENTRAL_TARGET_SSID, samples=2, interval=0.3)
    _last_scan_ts, _last_rssi = now, (rssi if rssi is not None else -90.0)
    return _last_rssi

# ---------- UDP ontvanger (clients #2/#3) ----------
def udp_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    while True:
        try:
            data, addr = sock.recvfrom(2048)
            pkt = json.loads(data.decode())
            i = int(pkt["id"])
            x, y = float(pkt["pos"][0]), float(pkt["pos"][1])
            rssi = float(pkt["rssi"])
            latest_data[i] = {"id": i, "pos": [x, y], "rssi": rssi, "ts": time.time()}
            # print ter debug:
            # print("RX", addr, "id=", i, "rssi=", rssi)
        except Exception as e:
            print("Bad packet:", e)

# ---------- centrale publiceert zichzelf ----------
def central_publisher():
    while True:
        latest_data[CENTRAL_ID] = {
            "id": CENTRAL_ID,
            "pos": [CENTRAL_POS[0], CENTRAL_POS[1]],
            "rssi": float(get_local_rssi()),
            "ts": time.time(),
        }
        time.sleep(1.0)

# ---------- RSSI -> afstand ----------
def rssi_to_distance(rssi, a0=A0, n=N):
    try:
        return 10 ** ((a0 - rssi) / (10.0 * n))
    except Exception:
        return float("inf")

# ---------- Trilateratie 3 ankers ----------
def trilaterate_3anchors(anchors):
    if len(anchors) != 3:
        return (0.0, 0.0)
    anchors = sorted(anchors, key=lambda p: p["id"])
    (x1, y1) = anchors[0]["pos"]; d1 = rssi_to_distance(anchors[0]["rssi"])
    (x2, y2) = anchors[1]["pos"]; d2 = rssi_to_distance(anchors[1]["rssi"])
    (x3, y3) = anchors[2]["pos"]; d3 = rssi_to_distance(anchors[2]["rssi"])

    A11 = 2*(x2 - x1); A12 = 2*(y2 - y1)
    A21 = 2*(x3 - x1); A22 = 2*(y3 - y1)
    b1 = (x2**2 + y2**2 - d2**2) - (x1**2 + y1**2 - d1**2)
    b2 = (x3**2 + y3**2 - d3**2) - (x1**2 + y1**2 - d1**2)
    det = A11*A22 - A12*A21
    if abs(det) < 1e-9:
        return (0.0, 0.0)
    X = ( b1*A22 - A12*b2) / det
    Y = (-b1*A21 + A11*b2) / det
    return (X, Y)

def compute_phone_position():
    needed = [1, 2, 3]
    if not all(i in latest_data for i in needed):
        return (0.0, 0.0)
    anchors = [latest_data[i] for i in needed]
    return trilaterate_3anchors(anchors)

# ---------- Flask routes ----------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/data")
def data():
    pis = [latest_data[i] for i in sorted(latest_data) if i in (1,2,3)]
    px, py = compute_phone_position()
    return jsonify({"pis": pis, "phone": [px, py], "model": {"A0": A0, "N": N}})

@app.route("/debug")
def debug():
    return jsonify(latest_data)

if __name__ == "__main__":
    threading.Thread(target=udp_server, daemon=True).start()
    threading.Thread(target=central_publisher, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
