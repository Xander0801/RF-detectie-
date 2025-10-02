# wifi_1d_sender.py — meet Wi-Fi RSSI → afstand en stuurt elke 5 s via UDP
import subprocess, time, statistics, socket, json, shutil, re, csv, sys

# ---- PAS AAN ----
COLLECTOR_IP   = "192.168.1.50"   # <-- IP van je laptop
COLLECTOR_PORT = 5006             # poort waarop de laptop luistert
RSSI0_1M = -45.0                  # mediane RSSI op 1 m (eerst kalibreren!)
N_EXP    = 2.2                    # padverliesexponent (2.0–3.5)
WINDOW_S = 5.0

IW = shutil.which("iw") or "/sbin/iw"

def get_connected_iface():
    out = subprocess.check_output([IW, "dev"], text=True, stderr=subprocess.DEVNULL)
    ifaces = re.findall(r"Interface\s+(\S+)", out)
    for ifn in ifaces:
        try:
            link = subprocess.check_output([IW, "dev", ifn, "link"], text=True)
            if "Connected" in link:
                return ifn
        except subprocess.CalledProcessError:
            pass
    return "wlan0"

def read_rssi_dbm(iface):
    out = subprocess.check_output([IW, "dev", iface, "link"], text=True)
    for ln in out.splitlines():
        if "signal:" in ln:
            return float(ln.split("signal:")[1].split("dBm")[0].strip())
    return None

def dist_from_rssi(rssi, rssi0=RSSI0_1M, n=N_EXP):
    return 10 ** ((rssi0 - rssi) / (10.0 * n))  # d0 = 1 m

def main():
    iface = get_connected_iface()
    host  = socket.gethostname()
    print(f"[sender] {host} via {iface} → {COLLECTOR_IP}:{COLLECTOR_PORT}", flush=True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    buf, t0 = [], time.time()
    with open("wifi_rssi.csv","a", newline="") as f:
        w = csv.writer(f)
        while True:
            try:
                v = read_rssi_dbm(iface)
                if v is not None:
                    buf.append(v)
            except subprocess.CalledProcessError:
                pass
            time.sleep(0.2)
            if time.time() - t0 >= WINDOW_S:
                if buf:
                    rssi = statistics.median(buf)
                    dist = dist_from_rssi(rssi)
                    ts   = time.time()
                    msg = {"pi": host, "ts": ts, "rssi_dbm": round(rssi,1), "dist_m": round(dist,3)}
                    sock.sendto(json.dumps(msg).encode(), (COLLECTOR_IP, COLLECTOR_PORT))
                    print("[sent]", msg, flush=True)
                    w.writerow([int(ts), host, iface, round(rssi,1), round(dist,3)]); f.flush()
                buf.clear(); t0 = time.time()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
