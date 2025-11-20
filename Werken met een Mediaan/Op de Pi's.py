# pi_rssi_sender_raw.py
# -----------------------------------------------------------------------------
# Doel: elke meting van de verbonden Wi-Fi link-RSSI meteen via UDP naar
#       de laptop sturen als JSON {"pi": <hostname>, "ts": <unix>, "rssi_dbm": <float>}
#
# Poll- en send-cadence:
#   - We pollen standaard 10 Hz en sturen elke poll meteen door (geen buffering).
#
# Waar komt de RSSI vandaan?
#   1) wpa_cli -i <iface> signal_poll → regel "RSSI=-60"
#      (bron/CLI code: https://android.googlesource.com/platform/external/wpa_supplicant_8/+/oreo-dr1-dev/wpa_supplicant/wpa_cli.c)
#   2) Fallback: iw dev <iface> link → regel "signal: -60 dBm"
#      (docs: https://wireless.docs.kernel.org/en/latest/en/users/documentation/iw.html
#             + ArchWiki usage: https://wiki.archlinux.org/title/Network_configuration/Wireless)
#
# UDP zenden met Python sockets:
#   - socket.sendto(...) met bytes → zie Python docs https://docs.python.org/3/library/socket.html
# -----------------------------------------------------------------------------

import subprocess, time, socket, json, shutil, re, sys, os

# >>> VUL DIT IN (of gebruik omgevingsvariabelen):
COLLECTOR_IP   = os.environ.get("COLLECTOR_IP", "172.20.10.8")
COLLECTOR_PORT = int(os.environ.get("COLLECTOR_PORT", "5006"))

# Poll- en zendtempo
POLL_HZ        = float(os.environ.get("POLL_HZ", "20"))   # 10 Hz = elke 0.1 s
POLL_DT        = 1.0 / POLL_HZ

# Interface detectie
DEFAULT_IFACE  = "wlan0"
IW             = shutil.which("iw") or "/sbin/iw"
WPA_CLI        = shutil.which("wpa_cli") or "wpa_cli"

def get_connected_iface():
    """
    Zoek een Wi-Fi interface die 'Connected' is; anders fallback naar DEFAULT_IFACE.
    We lezen iw dev en dan per interface iw dev <if> link (status).
    Docs: Linux Wireless 'iw' page (link in header).
    """
    try:
        out = subprocess.check_output([IW, "dev"], text=True, stderr=subprocess.DEVNULL)
        ifaces = re.findall(r"Interface\s+(\S+)", out)
        for ifn in ifaces:
            try:
                link = subprocess.check_output([IW, "dev", ifn, "link"], text=True)
                if "Connected" in link:
                    return ifn
            except subprocess.CalledProcessError:
                pass
    except Exception:
        pass
    return DEFAULT_IFACE

def poll_rssi_wpacli(iface):
    """
    Snelle RSSI-poll via wpa_cli signal_poll.
    Verwacht o.a. lijnen:
        RSSI=-60
        FREQUENCY=2412
    (bronlink in header)
    """
    try:
        out = subprocess.check_output([WPA_CLI, "-i", iface, "signal_poll"], text=True)
        for ln in out.splitlines():
            if ln.startswith("RSSI="):
                return float(ln.split("=", 1)[1].strip())
    except Exception:
        pass
    return None

def poll_rssi_iw(iface):
    """
    Fallback: parse 'iw dev <iface> link' → 'signal: -60 dBm'
    (docs gelinkt in header)
    """
    try:
        out = subprocess.check_output([IW, "dev", iface, "link"], text=True)
        for ln in out.splitlines():
            if "signal:" in ln:
                v = ln.split("signal:")[1].split("dBm")[0].strip()
                return float(v)
    except Exception:
        pass
    return None

def poll_rssi(iface):
    """Probeer eerst wpa_cli, dan iw."""
    r = poll_rssi_wpacli(iface)
    if r is not None:
        return r
    return poll_rssi_iw(iface)

def main():
    iface = get_connected_iface()
    host  = socket.gethostname()
    print(f"[pi_rssi_sender_raw] {host} via {iface} → {COLLECTOR_IP}:{COLLECTOR_PORT} | {POLL_HZ:.1f} Hz", flush=True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    while True:
        t0 = time.monotonic()

        rssi = poll_rssi(iface)
        if rssi is not None:
            msg = {"pi": host, "ts": time.time(), "rssi_dbm": float(rssi)}
            try:
                # UDP JSON → bytes (socket.sendto docs gelinkt in header)
                sock.sendto(json.dumps(msg).encode("utf-8"), (COLLECTOR_IP, COLLECTOR_PORT))
            except Exception as e:
                print("[send-err]", e, file=sys.stderr)

        # Nauwkeurige pauze om ~POLL_HZ aan te houden
        time.sleep(max(0.0, POLL_DT - (time.monotonic() - t0)))

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
