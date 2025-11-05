# pi_rssi_sender_avg10_lora.py
import subprocess, time, json, shutil, re, sys
from SX127x.LoRa import LoRa
from SX127x.board_config import BOARD

# Meet- en stuurtempo
SAMPLE_DT   = 0.05   # elke 0.05 s RSSI-poll
AVG_COUNT   = 10     # aantal polls per bericht (gemiddelde van 10)

IFACE   = "wlan0"
IW      = shutil.which("iw") or "/sbin/iw"

def get_connected_iface():
    """Zoek een Wi-Fi interface die 'Connected' is; anders fallback naar wlan0."""
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
    return IFACE

def rssi_signal_poll(iface):
    """Snelle RSSI-poll via Wi-Fi interface (blijft hetzelfde)."""
    try:
        out = subprocess.check_output(["wpa_cli", "-i", iface, "signal_poll"], text=True)
        for ln in out.splitlines():
            if ln.startswith("RSSI="):
                return float(ln.split("=")[1])
    except Exception:
        pass
    try:
        out = subprocess.check_output([IW, "dev", iface, "link"], text=True)
        for ln in out.splitlines():
            if "signal:" in ln:
                return float(ln.split("signal:")[1].split("dBm")[0].strip())
    except Exception:
        pass
    return None

def main():
    # LoRa setup
    BOARD.setup()
    lora = LoRa(verbose=False)
    lora.set_mode_tx()  # Zet module in zendmodus

    iface = get_connected_iface()
    host  = subprocess.getoutput("hostname")
    print(f"[pi_rssi_sender_avg10_LoRa] {host} via {iface}", flush=True)

    buf = []  # buffer met laatste losse polls

    while True:
        t0 = time.monotonic()

        r = rssi_signal_poll(iface)
        if r is not None:
            buf.append(float(r))

        if len(buf) >= AVG_COUNT:
            avg_rssi = sum(buf) / len(buf)
            msg = {"pi": host, "ts": time.time(), "rssi_dbm": round(avg_rssi, 2)}
            try:
                # Verzenden via LoRa
                data_bytes = json.dumps(msg).encode('utf-8')
                lora.write_payload(data_bytes)
            except Exception as e:
                print("[LoRa-send error]", e)
            buf.clear()

        time.sleep(max(0.0, SAMPLE_DT - (time.monotonic() - t0)))

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
