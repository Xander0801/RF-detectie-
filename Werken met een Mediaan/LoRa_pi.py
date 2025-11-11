# pi_rssi_sender_lora.py
import subprocess, time, json, shutil, re, sys, os
from SX127x.LoRa import LoRa
from SX127x.board_config import BOARD

# --- Instellingen ------------------------------------------------------------
POLL_HZ = float(os.environ.get("POLL_HZ", "20"))   # 20 Hz → elke 0.05 s
POLL_DT = 1.0 / POLL_HZ

DEFAULT_IFACE = "wlan0"
IW      = shutil.which("iw") or "/sbin/iw"
WPA_CLI = shutil.which("wpa_cli") or "wpa_cli"

# --- Interface zoeken --------------------------------------------------------
def get_connected_iface():
    """Zoek een Wi-Fi interface die 'Connected' is; anders fallback naar wlan0."""
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

# --- RSSI meting -------------------------------------------------------------
def poll_rssi_wpacli(iface):
    """Meet RSSI via `wpa_cli signal_poll`."""
    try:
        out = subprocess.check_output([WPA_CLI, "-i", iface, "signal_poll"], text=True)
        for ln in out.splitlines():
            if ln.startswith("RSSI="):
                return float(ln.split("=", 1)[1].strip())
    except Exception:
        pass
    return None

def poll_rssi_iw(iface):
    """Fallback: parse `iw dev <iface> link` → 'signal: -60 dBm'."""
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
    """Eerst wpa_cli, anders iw."""
    r = poll_rssi_wpacli(iface)
    return r if r is not None else poll_rssi_iw(iface)

# --- Main loop: meten en via LoRa sturen -------------------------------------
def main():
    # LoRa setup
    BOARD.setup()
    lora = LoRa(verbose=False)
    lora.set_mode_tx()

    iface = get_connected_iface()
    host  = subprocess.getoutput("hostname")
    print(f"[pi_rssi_sender_lora] {host} via {iface} → LoRa TX @ {POLL_HZ:.1f} Hz", flush=True)

    while True:
        t0 = time.monotonic()

        rssi = poll_rssi(iface)
        if rssi is not None:
            msg = {"pi": host, "ts": time.time(), "rssi_dbm": round(float(rssi), 2)}
            try:
                # JSON-payload via LoRa verzenden
                data_bytes = json.dumps(msg).encode('utf-8')
                lora.write_payload(data_bytes)
            except Exception as e:
                print("[LoRa-send error]", e, file=sys.stderr)

        # Houd ongeveer POLL_HZ aan
        time.sleep(max(0.0, POLL_DT - (time.monotonic() - t0)))

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
