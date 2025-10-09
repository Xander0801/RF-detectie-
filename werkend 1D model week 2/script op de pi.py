# wifi_1d_sender_fast.py — ~2–10 Hz updates met lichtgewicht meting
import subprocess, time, statistics, socket, json, shutil, re, collections, math

COLLECTOR_IP   = "10.93.182.89"   # <-- IP van je laptop
COLLECTOR_PORT = 5006

# Kalibratie (invullen na 1 m meting)
RSSI0_1M = -45.0
N_EXP    = 2.2

# Snelheids-instellingen
SAMPLE_DT   = 0.1   # elke 0.1 s RSSI-sample nemen
WINDOW_S    = 1.0   # mediaan over de laatste 1.0 s
SEND_PERIOD = 0.5   # elke 0.5 s een bericht sturen (probeer 0.2 s als je wilt)

iface = "wlan0"     # zet desnoods automatisch (zoals in je vorige code)

def rssi_signal_poll():
    """
    Snelle meting via wpa_supplicant socket:
    'wpa_cli -i wlan0 signal_poll' -> regels met RSSI=-xx
    """
    out = subprocess.check_output(["wpa_cli", "-i", iface, "signal_poll"], text=True)
    # Voorbeeld:
    # RSSI=-51
    # LINKSPEED=72
    # FREQUENCY=2412
    for ln in out.splitlines():
        if ln.startswith("RSSI="):
            return float(ln.split("=")[1])
    return None

def dist_from_rssi(rssi, rssi0=RSSI0_1M, n=N_EXP):
    return 10 ** ((rssi0 - rssi) / (10.0 * n))

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
host = socket.gethostname()

buf = collections.deque(maxlen=int(WINDOW_S / SAMPLE_DT) or 1)
t0_send = time.time()

print(f"[sender-fast] {host} → {COLLECTOR_IP}:{COLLECTOR_PORT}  "
      f"{1/SEND_PERIOD:.1f} Hz updates, window={WINDOW_S}s, sample={SAMPLE_DT}s",
      flush=True)

while True:
    t_start = time.time()
    try:
        r = rssi_signal_poll()
        if r is not None:
            buf.append(r)
    except Exception:
        pass

    # sturen op vaste periode
    if time.time() - t0_send >= SEND_PERIOD and buf:
        rssi_med = statistics.median(buf)
        dist = dist_from_rssi(rssi_med)
        msg = {
            "pi": host,
            "ts": time.time(),
            "rssi_dbm": round(rssi_med, 1),
            "dist_m": round(dist, 3)
        }
        sock.sendto(json.dumps(msg).encode(), (COLLECTOR_IP, COLLECTOR_PORT))
        # print("[sent]", msg)  # debug
        t0_send = time.time()

    # nauwkeurige sleep tot volgende sample
    dt = time.time() - t_start
    sl = max(0.0, SAMPLE_DT - dt)
    time.sleep(sl)
