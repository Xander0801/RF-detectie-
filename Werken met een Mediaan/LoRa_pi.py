# pi_rssi_sender_serial.py
import serial, time, json, subprocess, re, shutil, os, sys

# --- Instellingen ------------------------------------------------------------
SERIAL_PORT = "/dev/ttyACM0"  # LilyGO T3 via USB  pas aan als nodig
BAUDRATE    = 115200          # standaard ESP32
POLL_HZ     = float(os.environ.get("POLL_HZ", "20"))
POLL_DT     = 1.0 / POLL_HZ

DEFAULT_IFACE = "wlan0"
IW      = shutil.which("iw") or "/sbin/iw"
WPA_CLI = shutil.which("wpa_cli") or "wpa_cli"

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

# --- RSSI meten --------------------------------------------------------------
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

# --- Main loop: meten en via seriÃ«le poort sturen ----------------------------
def main():
    iface = get_connected_iface()
    host  = subprocess.getoutput("hostname")
    print(f"[pi_rssi_sender_serial] {host} via {iface} â†’ Serial TX @ {POLL_HZ:.1f} Hz", flush=True)

    try:
        ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1)
    except Exception as e:
        print(f"Kan seriÃ«le poort {SERIAL_PORT} niet openen:", e)
        sys.exit(1)

    while True:
        t0 = time.monotonic()

        rssi = poll_rssi(iface)
        if rssi is not None:
            msg = {"pi": host, "ts": time.time(), "rssi_dbm": round(float(rssi), 2)}
            try:
                ser.write((json.dumps(msg) + "\n").encode("utf-8"))
            except Exception as e:
                print("[Serial send error]", e, file=sys.stderr)

        time.sleep(max(0.0, POLL_DT - (time.monotonic() - t0)))

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
