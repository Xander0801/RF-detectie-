# pi_rssi_sender_avg10.py
# ----------------------------------------------
# Doel: enkel RSSI (dBm) naar de laptop sturen.
# Ruisreductie: neem 10 snelle metingen en stuur daarvan het GEMIDDELDE.
# Afstand wordt NIET op de Pi berekend; dat gebeurt op de laptop.
# ----------------------------------------------

import subprocess, time, socket, json, shutil, re, sys

# >>> VUL DIT IN: IP van je laptop (collector) en poort
COLLECTOR_IP   = "10.111.33.89"
COLLECTOR_PORT = 5006

# Meet- en stuurtempo
SAMPLE_DT   = 0.05   # elke 0.05 s RSSI-poll
AVG_COUNT   = 10     # aantal polls per bericht (gemiddelde van 10)
# Effectief stuurtempo ≈ AVG_COUNT * SAMPLE_DT  (hier ~0.5 s)

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
    """
    Snelle RSSI-poll:
    - Eerst via wpa_cli signal_poll (laag-overhead)
    - Fallback naar 'iw dev <iface> link'
    Retourneert RSSI in dBm (float) of None.
    """
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
    iface = get_connected_iface()
    host  = socket.gethostname()
    print(f"[pi_rssi_sender_avg10] {host} via {iface} → {COLLECTOR_IP}:{COLLECTOR_PORT}", flush=True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Optioneel: bind een vaste source-port zodat IP:poort stabiel blijft
    # sock.bind(("", 41000))

    buf = []  # buffer met de laatste losse polls voor het 10-gemiddelde

    while True:
        t0 = time.monotonic()

        r = rssi_signal_poll(iface)
        if r is not None:
            buf.append(float(r))

        # Als we 10 samples hebben: stuur gemiddelde en leeg buffer
        if len(buf) >= AVG_COUNT:
            avg_rssi = sum(buf) / len(buf)
            msg = {"pi": host, "ts": time.time(), "rssi_dbm": round(avg_rssi, 2)}
            try:
                sock.sendto(json.dumps(msg).encode(), (COLLECTOR_IP, COLLECTOR_PORT))
                # print("[sent]", msg)  # desnoods aanzetten voor debug
            except Exception as e:
                print("[send-err]", e)
            buf.clear()

        # Nauwkeurige pauze tot volgende poll
        time.sleep(max(0.0, SAMPLE_DT - (time.monotonic() - t0)))

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
