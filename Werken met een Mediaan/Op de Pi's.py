# pi_rssi_sender_raw.py
import subprocess, time, socket, json, shutil, re, sys, os

# --- Instellingen (env-override mogelijk) ------------------------------------
COLLECTOR_IP   = os.environ.get("COLLECTOR_IP", "10.0.0.1")
COLLECTOR_PORT = int(os.environ.get("COLLECTOR_PORT", "5006"))
POLL_HZ        = float(os.environ.get("POLL_HZ", "20"))   # 20 Hz → elke 0.05 s
POLL_DT        = 1.0 / POLL_HZ

# Tools & interface
DEFAULT_IFACE  = "wlan0"
IW             = shutil.which("iw") or "/sbin/iw"
WPA_CLI        = shutil.which("wpa_cli") or "wpa_cli"

# --- Interface zoeken --------------------------------------------------------
def get_connected_iface():
    try:
        out = subprocess.check_output([IW, "dev"], text=True, stderr=subprocess.DEVNULL)
        for ifn in re.findall(r"Interface\s+(\S+)", out):
            try:
                link = subprocess.check_output([IW, "dev", ifn, "link"], text=True)
                if "Connected" in link:
                    return ifn
            except subprocess.CalledProcessError:
                pass
    except Exception:
        pass
    return DEFAULT_IFACE

# --- RSSI polling ------------------------------------------------------------
def poll_rssi_wpacli(iface):
    try:
        out = subprocess.check_output([WPA_CLI, "-i", iface, "signal_poll"], text=True)
        for ln in out.splitlines():
            if ln.startswith("RSSI="):
                return float(ln.split("=", 1)[1].strip())
    except Exception:
        pass
    return None

def poll_rssi_iw(iface):
    try:
        out = subprocess.check_output([IW, "dev", iface, "link"], text=True)
        for ln in out.splitlines():
            if "signal:" in ln:
                val = ln.split("signal:")[1].split("dBm")[0].strip()
                return float(val)
    except Exception:
        pass
    return None

def poll_rssi(iface):
    r = poll_rssi_wpacli(iface)
    return r if r is not None else poll_rssi_iw(iface)

# --- Main loop: meten en via UDP sturen --------------------------------------
def main():
    iface = get_connected_iface()
    host  = socket.gethostname()
    print(f"[pi_rssi_sender_raw] {host} via {iface} → {COLLECTOR_IP}:{COLLECTOR_PORT} | {POLL_HZ:.1f} Hz", flush=True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # UDP socket

    while True:
        t0 = time.monotonic()

        rssi = poll_rssi(iface)
        if rssi is not None:
            msg = {"pi": host, "ts": time.time(), "rssi_dbm": round(float(rssi), 2)}
            try:
                # UDP JSON versturen (socket.sendto)
                sock.sendto(json.dumps(msg).encode("utf-8"), (COLLECTOR_IP, COLLECTOR_PORT))
            except Exception as e:
                print("[send-err]", e, file=sys.stderr)

        # Houd ongeveer POLL_HZ aan
        time.sleep(max(0.0, POLL_DT - (time.monotonic() - t0)))

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
