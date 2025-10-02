"""Eenvoudige 1D-visualisatie: x-as met Pi op x=0 en GSM-stip op x=afstand."""
import matplotlib
matplotlib.use("TkAgg")  # werkt meestal op Windows; alternatief: 'QtAgg' met pyqt5
import socket, json, time, threading
import matplotlib.pyplot as plt

PORT = 5006             # moet gelijk zijn aan de sender
AX_MAX_M = 25.0         # schaal van de x-as (pas aan aan jullie ruimte)
WINDOW_S = 10.0         # metingen jonger dan dit gebruiken

last = {"ts": 0.0, "dist": None, "rssi": None, "pi": ""}

def listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", PORT))
    print(f"[collector-1d] luistert op UDP :{PORT}")
    while True:
        data, addr = sock.recvfrom(65535)
        try:
            m = json.loads(data.decode("utf-8"))
            last.update({"ts": float(m["ts"]), "dist": float(m["dist_m"]),
                         "rssi": float(m["rssi_dbm"]), "pi": m.get("pi","")})
            print(f"[recv] {addr} d={last['dist']:.2f} m  RSSI={last['rssi']:.1f}  pi={last['pi']}")
        except Exception as e:
            print("[warn] ongeldige boodschap:", e)

def main():
    threading.Thread(target=listener, daemon=True).start()

    plt.ion()
    fig, ax = plt.subplots()
    ax.set_xlim(-1, AX_MAX_M)
    ax.set_ylim(-1, 1)
    ax.set_yticks([])
    ax.set_xlabel("Afstand (m)")
    ax.axvline(0, color="black")  # Pi op x=0
    ax.text(0.1, 0.2, "Pi", transform=ax.get_xaxis_transform())
    dot, = ax.plot([], [], marker="o", markersize=10)
    txt = ax.text(0.02, 0.95, "", transform=ax.transAxes, va="top")

    while True:
        now = time.time()
        if last["dist"] is not None and now - last["ts"] <= WINDOW_S:
            x = max(0.0, min(AX_MAX_M, last["dist"]))
            dot.set_data([x], [0])
            txt.set_text(f"pi={last['pi']}  d≈{x:.2f} m  RSSI={last['rssi']:.1f} dBm")
        else:
            dot.set_data([], [])
            txt.set_text("Wacht op metingen…")
        fig.canvas.draw_idle()
        plt.pause(0.1)

if __name__ == "__main__":
    main()
