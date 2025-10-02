# installeer pakket
sudo apt update
sudo apt install -y iw python3

# maak bestand aan
nano sender_wifi.py

# script
# sender_wifi.py — meet Wi-Fi RSSI van de verbonden AP (gsm/router) en stuurt elke 5 s naar collector
import subprocess, time, statistics, socket, json, shutil, re

# ---- PAS DIT AAN ----
COLLECTOR_IP   = "192.168.1.50"   # <-- IP van je laptop/collector
COLLECTOR_PORT = 5005
# Kalibratie (na 1x meten bij 1 m aanpassen):
RSSI0_1M = -45.0   # mediane Wi-Fi RSSI op 1 m (dBm), vaak −40 .. −55
N_EXP    = 2.2     # padverliesexponent (2.0–2.4 open, 2.5–3.5 indoor)
WINDOW_S = 5.0     # samplen, mediaan per 5 s

IW = shutil.which("iw") or "/sbin/iw"

def get_connected_iface():
    out = subprocess.check_output([IW, "dev"], text=True)
    ifaces = re.findall(r"Interface\s+(\S+)", out)
    for ifn in ifaces:
        link = subprocess.check_output([IW, "dev", ifn, "link"], text=True)
        if "Connected" in link:
            return ifn
    return "wlan0"

def read_rssi_dbm(iface):
    out = subprocess.check_output([IW, "dev", iface, "link"], text=True)
    for ln in out.splitlines():
        if "signal:" in ln:
            return float(ln.split("signal:")[1].split("dBm")[0].strip())

def dist_from_rssi(rssi, rssi0=RSSI0_1M, n=N_EXP):
    # log-distance model met d0=1 m
    return 10 ** ((rssi0 - rssi) / (10.0 * n))

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
host = socket.gethostname()
iface = get_connected_iface()
buf, t0 = [], time.time()

print(f"[sender] {host} via {iface} → {COLLECTOR_IP}:{COLLECTOR_PORT}")

while True:
    try:
        v = read_rssi_dbm(iface)
        if v is not None:
            buf.append(v)
    except Exception:
        pass
    time.sleep(0.2)
    if time.time() - t0 >= WINDOW_S:
        if buf:
            rssi = statistics.median(buf)
            dist = dist_from_rssi(rssi)
            msg = {
                "pi": host,
                "iface": iface,
                "ts": time.time(),
                "rssi_dbm": round(rssi, 1),
                "dist_m": round(dist, 3)
            }
            sock.sendto(json.dumps(msg).encode(), (COLLECTOR_IP, COLLECTOR_PORT))
            print("[sent]", msg, flush=True)
        buf.clear()
        t0 = time.time()

# run script
python3 sender_wifi.py

