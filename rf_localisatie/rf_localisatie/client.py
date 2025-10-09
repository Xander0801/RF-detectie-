# client.py — Pi #2 of Pi #3 met ECHTE Wi-Fi RSSI
import socket, json, time, subprocess, re, statistics

CENTRAL_IP   = "192.168.1.100"   # <-- IP van de centrale Pi #1
CENTRAL_PORT = 5005
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# === PAS AAN PER PI ===
pi_id       = 2                  # op Pi #3 zet je 3
pi_position = (0.0, 6.0)         # kies je vaste coördinaat
WLAN_IFACE  = "wlan0"

# Hotspot die je wil meten (BSSID voorkeur; SSID kan ook)
TARGET_BSSID = "aa:bb:cc:dd:ee:ff"   # <-- zet hier jouw BSSID
TARGET_SSID  = None                  # of bv. "NoortjeHotspot"

# ---- Wi-Fi RSSI helpers ----
def _iw_scan():
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

def read_wifi_rssi(samples=2, interval=0.4):
    vals = []
    for _ in range(samples):
        iw_text = _iw_scan()
        cells = _parse_cells(iw_text)
        hit = None
        if TARGET_BSSID:
            hit = next((c for c in cells if c["bssid"] == TARGET_BSSID.lower() and c["rssi"] is not None), None)
        elif TARGET_SSID:
            same = [c for c in cells if c["ssid"] == TARGET_SSID and c["rssi"] is not None]
            if same:
                # sterkste zender met die SSID
                hit = max(same, key=lambda c: c["rssi"])
        if hit:
            vals.append(hit["rssi"])
        time.sleep(interval)
    return float(statistics.median(vals)) if vals else None

while True:
    rssi = read_wifi_rssi()
    if rssi is None:
        # niet gezien tijdens scan → stuur een zwakke waarde zodat server nog kan draaien
        rssi = -90.0
    packet = {"id": pi_id, "pos": pi_position, "rssi": float(rssi)}
    sock.sendto(json.dumps(packet).encode(), (CENTRAL_IP, CENTRAL_PORT))
    time.sleep(1.0)
