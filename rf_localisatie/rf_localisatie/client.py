# client.py — Pi #2 of #3 met echte Wi-Fi RSSI
import socket, json, time, subprocess, re

CENTRAL_IP   = "192.168.43.105"   # <-- vervang door IP van centrale Pi #1
CENTRAL_PORT = 5005
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# === PAS AAN PER PI ===
pi_id       = 2                  # op Pi #3 zet je 3
pi_position = (0.0, 6.0)         # kies je vaste coördinaat
WLAN_IFACE  = "wlan0"            # controleer met `iw dev`

def get_local_rssi():
    try:
        out = subprocess.check_output(["iwconfig", WLAN_IFACE], stderr=subprocess.STDOUT)
        text = out.decode(errors="ignore")
        match = re.search(r"Signal level=(-?\d+) dBm", text)
        if match:
            return float(match.group(1))
        else:
            return -90.0
    except Exception as e:
        print("RSSI read error:", e)
        return -90.0

print(f"[CLIENT {pi_id}] Start verzenden naar {CENTRAL_IP}:{CENTRAL_PORT}")

while True:
    rssi = get_local_rssi()
    packet = {"id": pi_id, "pos": pi_position, "rssi": float(rssi)}
    sock.sendto(json.dumps(packet).encode(), (CENTRAL_IP, CENTRAL_PORT))
    print(f"[CLIENT {pi_id}] RSSI={rssi} dBm → verzonden")
    time.sleep(1.0)
