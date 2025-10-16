# wifi_1d_sender_adaptive.py — snelle, stabiele afstand met adaptieve filtering
import subprocess, time, statistics, socket, json, shutil, re, collections, math, sys

COLLECTOR_IP   = "10.111.33.89"   # <-- IP van je laptop
COLLECTOR_PORT = 5006

# Kalibratie (zet na je 1 m meting)
RSSI0_1M = -55.0
N_EXP    = 2.2

# Snelheid & filtering
SAMPLE_DT     = 0.05   # sample elke 50 ms
ROBUST_WIN_S  = 0.8    # venster voor robuuste median (s)  (0.6–1.0 is goed)
SEND_PERIOD   = 0.25   # stuur elke 0.25 s (4 Hz). Mag naar 0.2 s.

# Adaptieve EMA op RSSI
TAU_STILL     = 2.5    # traag (glad) als stilstand
TAU_MOVE      = 0.5    # snel als beweging
MOVE_DB_THRESH= 1.8    # “groot genoeg” stap in dB t.o.v. laatste EMA
MAD_MOVE_DB   = 1.2    # of onrust: 1.4826*MAD > drempel → snel

# Slew-rate limiter op afstand (m/s). 0 = uit
V_MAX         = 2.0

iface = "wlan0"

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

def rssi_signal_poll():
    """ Snelle meting via wpa_cli; fallback naar iw link. """
    try:
        out = subprocess.check_output(["wpa_cli", "-i", iface, "signal_poll"], text=True)
        for ln in out.splitlines():
            if ln.startswith("RSSI="):
                return float(ln.split("=")[1])
    except Exception:
        pass
    # fallback
    out = subprocess.check_output([IW, "dev", iface, "link"], text=True)
    for ln in out.splitlines():
        if "signal:" in ln:
            return float(ln.split("signal:")[1].split("dBm")[0].strip())
    return None

def rssi_to_dist(rssi, rssi0=RSSI0_1M, n=N_EXP):
    return 10 ** ((rssi0 - rssi) / (10.0 * n))

def robust_stats(vals):
    med = statistics.median(vals)
    mad = statistics.median([abs(v - med) for v in vals]) or 1e-6
    return med, 1.4826 * mad  # schaal-MAD ≈ σ

def main():
    global iface
    iface = get_connected_iface()
    host  = socket.gethostname()
    print(f"[sender-adaptive] {host} via {iface} → {COLLECTOR_IP}:{COLLECTOR_PORT}", flush=True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # buffers & states
    buf = collections.deque(maxlen=max(1, int(ROBUST_WIN_S / SAMPLE_DT)))
    ema_rssi = None
    last_send_t = time.monotonic()
    last_ema_t  = time.monotonic()
    last_dist   = None

    while True:
        t_loop = time.monotonic()
        # 1) sample
        try:
            r = rssi_signal_poll()
            if r is not None:
                buf.append(r)
        except Exception:
            pass

        # 2) periodiek sturen
        if t_loop - last_send_t >= SEND_PERIOD and buf:
            vals = list(buf)
            r_med, r_sigma = robust_stats(vals) if len(vals) >= 3 else (vals[-1], 0.0)

            # 3) adaptief EMA op RSSI
            if ema_rssi is None:
                ema_rssi = r_med
                last_ema_t = t_loop
            dt = max(1e-3, t_loop - last_ema_t)
            moving = (abs(r_med - ema_rssi) > MOVE_DB_THRESH) or (r_sigma > MAD_MOVE_DB)
            tau = TAU_MOVE if moving else TAU_STILL
            alpha = dt / (tau + dt)
            ema_rssi = (1 - alpha) * ema_rssi + alpha * r_med
            last_ema_t = t_loop

            # 4) naar afstand + optionele snelheidslimiet
            dist_inst = rssi_to_dist(ema_rssi)
            if last_dist is None:
                dist_s = dist_inst
            else:
                if V_MAX > 0:
                    max_step = V_MAX * (t_loop - last_send_t)
                    dist_s = max(last_dist - max_step, min(last_dist + max_step, dist_inst))
                else:
                    dist_s = dist_inst

            # 5) versturen
            msg = {
                "pi": host,
                "ts": time.time(),
                "rssi_dbm": round(ema_rssi, 2),   # we sturen de GEFILTERDE RSSI
                "dist_m": round(dist_s, 3)
            }
            sock.sendto(json.dumps(msg).encode(), (COLLECTOR_IP, COLLECTOR_PORT))
            # print("[sent]", msg)
            last_send_t = t_loop
            last_dist   = dist_s

        # nauwkeurige sleep
        sl = max(0.0, SAMPLE_DT - (time.monotonic() - t_loop))
        time.sleep(sl)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
