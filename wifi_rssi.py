import subprocess, time, statistics, socket, csv, shutil, re, sys

# ---- Kalibratie (na 1x meten aanpassen) ----
RSSI0_1M = -45.0   # mediaan RSSI op 1 m (dBm) – zet dit na je 1m-meting!
N_EXP    = 2.2     # padverliesexponent: 2.0–2.4 (open), 2.5–3.5 (indoor)

IW = shutil.which("iw") or "/sbin/iw"

def get_connected_iface():
    # zoek interfaces via `iw dev`, neem degene waar `iw dev X link` "Connected" zegt
    out = subprocess.check_output([IW, "dev"], text=True, stderr=subprocess.DEVNULL)
    ifaces = re.findall(r"Interface\s+(\S+)", out)
    for ifn in ifaces:
        try:
            link = subprocess.check_output([IW, "dev", ifn, "link"], text=True)
            if "Connected" in link:
                return ifn
        except subprocess.CalledProcessError:
            pass
    # fallback
    return "wlan0"

def read_rssi_dbm(iface):
    out = subprocess.check_output([IW, "dev", iface, "link"], text=True)
    for ln in out.splitlines():
        if "signal:" in ln:
            return float(ln.split("signal:")[1].split("dBm")[0].strip())
    return None

def dist_from_rssi(rssi, rssi0=RSSI0_1M, n=N_EXP):
    # d = 10^((rssi0 - rssi)/(10*n)) met d0=1 m
    return 10 ** ((rssi0 - rssi) / (10.0 * n))

def main():
    iface = get_connected_iface()
    host  = socket.gethostname()
    print(f"Using Wi-Fi interface: {iface}", flush=True)

    buf, t0 = [], time.time()
    with open("wifi_rssi.csv","a", newline="") as f:
        w = csv.writer(f)
        # w.writerow(["ts","pi","iface","rssi_dbm","dist_m"])  # (eenmalige header)
        while True:
            try:
                v = read_rssi_dbm(iface)
            except subprocess.CalledProcessError:
                v = None
            if v is not None:
                buf.append(v)
            time.sleep(0.2)
            if time.time() - t0 >= 5:
                if buf:
                    med = statistics.median(buf)
                    d   = dist_from_rssi(med)
                    ts  = int(time.time())
                    print(f"{host} {ts} [{iface}] RSSI={med:.1f} dBm  d≈{d:.2f} m", flush=True)
                    w.writerow([ts, host, iface, round(med,1), round(d,3)])
                    f.flush()
                buf.clear()
                t0 = time.time()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
