# trilateration_gui_clean.py  (raw-paneel boven sliders + juiste z-order)
import matplotlib
matplotlib.use("TkAgg")

import socket, json, time, threading, collections
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from matplotlib.widgets import Slider, TextBox

# --------------------------------------------
# BASISINSTELLINGEN / PARAMETERS
# --------------------------------------------
PORT, WINDOW_S, AVG_N_MSGS = 5006, 6.0, 10
# PORT: UDP-poort waarop de GUI luistert naar Pi-telemetrie
# WINDOW_S: tijdsvenster in seconden; als een Pi langer dan dit venster niets stuurt,
#           wordt zijn buffer gewist (waardoor die Pi tijdelijk niet mee trilaterateert)
# AVG_N_MSGS: aantal laatste RSSI-metingen per Pi om het gemiddelde (ruisonderdrukking) te nemen

RAW_KEEP, RAW_COLS = 40, 70  # Raw-log: aantal regels en max kolombreedte

# Ankerposities (in meter) op de kaart. Aanpasbaar via de GUI-TextBoxen.
ANCHOR_INIT = {"A": (1.0, 1.0), "B": (1.0, 6.0), "C": (3.0, 3.0)}

# Kalibratieparameters per anker:
#  - rssi1m: verwachte RSSI (dBm) op 1 meter afstand
#  - n: padverlies-exponent (omgeving): typisch ~2.0 (vrije ruimte) tot ~3-3.5 (indoor)
CAL_INIT    = {"A": {"rssi1m": -55.0, "n": 2.2},
               "B": {"rssi1m": -55.0, "n": 2.2},
               "C": {"rssi1m": -55.0, "n": 2.2}}

ANC_ORDER = ["A", "B", "C"]

# Mapping van binnenkomend IP → vaste sleutel "A/B/C" (eerste 3 unieke IP's krijgen A,B,C)
ip_to_key, unused_keys = {}, ANC_ORDER.copy()

# --------------------------------------------
# STATE BUFFERS
# --------------------------------------------
raw_log = collections.deque(maxlen=RAW_KEEP)                         # tekstpaneel "Raw UDP data"
rssi_buf = {k: collections.deque(maxlen=AVG_N_MSGS) for k in ANC_ORDER}  # laatste RSSI's per anker (moving average)
last_ts  = {k: 0.0 for k in ANC_ORDER}                               # laatste timestamp per anker (voor WINDOW_S)
anchors  = {k: [*ANCHOR_INIT[k]] for k in ANC_ORDER}                 # werkende ankerposities (mutabel voor GUI)
cal      = {k: dict(CAL_INIT[k]) for k in ANC_ORDER}                 # werkende kalibratieparams (gewijzigd via sliders)
circles  = {k: None for k in ANC_ORDER}                              # cirkelplots per anker (afstandsvlakken)

# --------------------------------------------
# HULPFUNCTIES
# --------------------------------------------
def fmt_raw(ip, port, key, m):
    """
    Render een korte regel voor het RAW-paneel.
    Verwacht JSON met velden:
      - "pi": vrije naam van de Pi (optioneel)
      - "rssi_dbm": RSSI in dBm (float/str als float)
      - "ts": unix-tijdstempel (float/str als float)
    """
    try:
        r = float(m.get("rssi_dbm", 0.0)); ts = float(m.get("ts", time.time()))
    except Exception:
        r, ts = 0.0, time.time()
    tstr = time.strftime("%H:%M:%S", time.localtime(ts))
    name = m.get("pi", ""); k = key if key else "?"
    s = f"{tstr} {ip}:{port} [{k}] pi='{name}' rssi={r:.1f}"
    return s if len(s) <= RAW_COLS else s[:RAW_COLS-1] + "…"

def rssi_to_dist(rssi, rssi1m, n):
    """
    [F1] RSSI→AFSTAND (log-distance path loss model; SI-units met 'meter' als afstand):
      d = 10 ** ((rssi1m - rssi) / (10 * n))

    Waar komen de INPUTS vandaan?
      - rssi: gemiddelde van de laatste AVG_N_MSGS metingen uit rssi_buf[k] (berekend in de main-loop)
      - rssi1m: cal[k]["rssi1m"] (instelbaar via de sliders)
      - n:      cal[k]["n"]      (instelbaar via de sliders)
    """
    return 10 ** ((rssi1m - rssi) / (10.0 * n))

def trilaterate(points_xy, dists):
    """
    [F2] TRILATERATIE via linearisatie en least-squares:
      We hebben 3 (of meer) cirkels: (x - xi)^2 + (y - yi)^2 = di^2
      Trek de vergelijking van anker 1 af van de anderen en lineariseer:
        2(xi - x1) * x + 2(yi - y1) * y = (xi^2 + yi^2 - di^2) - (x1^2 + y1^2 - d1^2)
      Dit geeft A * [x y]^T = b. We lossen in LSZIN (np.linalg.lstsq).

    Waar komen de INPUTS vandaan?
      - points_xy: lijst van ankerposities [(xA,yA), (xB,yB), (xC,yC)] uit 'anchors'
      - dists:     lijst van berekende afstanden [dA, dB, dC] uit [F1]
    """
    (x1, y1), d1 = points_xy[0], dists[0]
    A, b = [], []
    for (xi, yi), di in zip(points_xy[1:], dists[1:]):
        A.append([2*(xi-x1), 2*(yi-y1)])
        b.append((xi*xi + yi*yi - di*di) - (x1*x1 + y1*y1 - d1*d1))
    A = np.asarray(A, float); b = np.asarray(b, float)
    xy, *_ = np.linalg.lstsq(A, b, rcond=None)
    return float(xy[0]), float(xy[1])

# --------------------------------------------
# UDP LISTENER (neemt data van de Pi's aan)
# --------------------------------------------
def listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", PORT))
    print(f"[GUI] luistert op UDP :{PORT}")
    while True:
        data, addr = sock.recvfrom(65535)
        ip, sport = addr
        txt = data.decode("utf-8", errors="replace").strip()

        # Parse JSON of log 'invalid JSON'
        try:
            m = json.loads(txt)
        except Exception as e:
            raw_log.appendleft(f"{ip}:{sport} <invalid JSON> {e}")
            continue

        # Koppel nieuw IP aan eerstvolgende sleutel A/B/C
        key = ip_to_key.get(ip)
        if key is None and unused_keys:
            key = unused_keys.pop(0); ip_to_key[ip] = key
            print(f"[assign] {ip} → {key}")

        # Toon raw-regel (bovenaan = meest recent)
        raw_log.appendleft(fmt_raw(ip, sport, key, m))

        # Als we al 3 Pi's hebben en er komt een 4e IP binnen: niet plotten
        if key is None:
            continue

        # Extractie van gemeten waarden uit de UDP-payload
        try:
            rssi = float(m["rssi_dbm"])  # dBm
            ts = float(m["ts"])          # unix-timestamp (s)
        except Exception:
            continue

        # Buffering voor ruisonderdrukking:
        #  - sliding window van AVG_N_MSGS
        #  - later wordt het gemiddelde genomen (zie main-loop)
        rssi_buf[key].append(rssi)
        last_ts[key] = ts

# --------------------------------------------
# MAIN + GUI
# --------------------------------------------
def main():
    # Start de listener-thread (daemon)
    threading.Thread(target=listener, daemon=True).start()

    # Matplotlib-figuur
    plt.rcParams.update({"font.size": 10})
    fig = plt.figure(figsize=(12.5, 7.0))
    fig.subplots_adjust(left=0.04, right=0.98, bottom=0.06, top=0.95)

    # Linker kaart
    ax_map = fig.add_axes([0.06, 0.32, 0.58, 0.62]); ax_map.set_zorder(1)
    ax_map.set_aspect("equal", adjustable="box")
    ax_map.set_xlabel("x (m)"); ax_map.set_ylabel("y (m)")
    ax_map.grid(True, alpha=0.25)

    def set_axes_limits():
        # Houd de kaart self-scaling rond de huidige ankerposities
        xs = [anchors[k][0] for k in ANC_ORDER]
        ys = [anchors[k][1] for k in ANC_ORDER]
        ax_map.set_xlim(min(xs)-2, max(xs)+2)
        ax_map.set_ylim(min(ys)-2, max(ys)+2)
    set_axes_limits()

    # Plot ankers en labels
    base_scatter = {k: ax_map.scatter([anchors[k][0]],[anchors[k][1]], marker="^", s=60)
                    for k in ANC_ORDER}
    labels = {k: ax_map.text(anchors[k][0]+0.12, anchors[k][1]+0.12, k, fontsize=10, weight="bold")
              for k in ANC_ORDER}

    # Punt voor geschatte positie (uit [F2])
    est_dot, = ax_map.plot([], [], marker="o", markersize=10)

    # Tekstblokje met actuele info (afstanden, rssi-avg, en EST)
    info_txt = ax_map.text(0.01, 0.99, "", transform=ax_map.transAxes,
                           va="top", ha="left",
                           bbox=dict(boxstyle="round", fc="white", alpha=0.85))

    # *** RAW paneel (hoger geplaatst, boven sliders, witte achtergrond, hogere z-order) ***
    ax_raw = fig.add_axes([0.67, 0.66, 0.31, 0.30])  # hoger + iets compacter
    ax_raw.set_zorder(5)
    ax_raw.set_title("Raw UDP data (nieuwste boven)")
    ax_raw.axis("off")
    ax_raw.set_facecolor("white")             # masker
    ax_raw.patch.set_alpha(1.0)
    raw_text = ax_raw.text(0.01, 0.98, "(nog geen data)", va="top", ha="left",
                           transform=ax_raw.transAxes, family="monospace", fontsize=9)
    raw_text.set_clip_on(True)                # clip binnen as

    # *** Sliders (lager geplaatst, z-order lager dan raw) ***
    # Deze sliders beïnvloeden direct de INPUTS voor [F1]:
    #   cal["X"]["rssi1m"] en cal["X"]["n"]  (X ∈ {A,B,C})
    slider_specs = [
        ("A RSSI@1m (dBm)", -80, -30, cal["A"]["rssi1m"]),
        ("A n",              1.6,  3.5, cal["A"]["n"]),
        ("B RSSI@1m (dBm)", -80, -30, cal["B"]["rssi1m"]),
        ("B n",              1.6,  3.5, cal["B"]["n"]),
        ("C RSSI@1m (dBm)", -80, -30, cal["C"]["rssi1m"]),
        ("C n",              1.6,  3.5, cal["C"]["n"]),
    ]
    sliders = []
    y0, dy = 0.56, 0.05     # lager startpunt om overlap met RAW te vermijden
    for i, (label, vmin, vmax, v0) in enumerate(slider_specs):
        axsl = fig.add_axes([0.67, y0 - i*dy, 0.31, 0.03])
        axsl.set_zorder(2)  # onder raw
        sl = Slider(axsl, label, vmin, vmax, valinit=v0, valfmt="%.2f")
        sliders.append(sl)

    def on_slider_change(_):
        # Schrijf sliderwaarden terug naar 'cal' (INPUTS voor [F1])
        cal["A"]["rssi1m"], cal["A"]["n"] = sliders[0].val, sliders[1].val
        cal["B"]["rssi1m"], cal["B"]["n"] = sliders[2].val, sliders[3].val
        cal["C"]["rssi1m"], cal["C"]["n"] = sliders[4].val, sliders[5].val
    for sl in sliders: sl.on_changed(on_slider_change)

    # Positievelden ankers (INPUTS voor [F2])
    ax_pos_panel = fig.add_axes([0.06, 0.06, 0.58, 0.20]); ax_pos_panel.axis("off")
    ax_pos_panel.text(0.01, 0.92, "Posities (meter)", weight="bold")

    def add_textbox_norm(left, bottom, width, height, label, init):
        axt = fig.add_axes([left, bottom, width, height]); axt.set_zorder(1)
        return TextBox(axt, label, initial=str(init))

    tb = {}
    cols = {"A": 0.06, "B": 0.27, "C": 0.48}
    for key in ANC_ORDER:
        x0 = cols[key]
        tbx = add_textbox_norm(x0, 0.11, 0.08, 0.06, f"{key} x", anchors[key][0])
        tby = add_textbox_norm(x0, 0.04, 0.08, 0.06, f"{key} y", anchors[key][1])
        tb[key] = (tbx, tby)

        def submit_x(text, kk=key):
            # Aanpassing anker-x → update plot en as-limieten (INPUT voor [F2])
            try:
                anchors[kk][0] = float(text)
                base_scatter[kk].set_offsets([anchors[kk][0], anchors[kk][1]])
                labels[kk].set_position((anchors[kk][0]+0.12, anchors[kk][1]+0.12))
                set_axes_limits()
            except Exception: pass

        def submit_y(text, kk=key):
            # Aanpassing anker-y → update plot en as-limieten (INPUT voor [F2])
            try:
                anchors[kk][1] = float(text)
                base_scatter[kk].set_offsets([anchors[kk][0], anchors[kk][1]])
                labels[kk].set_position((anchors[kk][0]+0.12, anchors[kk][1]+0.12))
                set_axes_limits()
            except Exception: pass

        tbx.on_submit(submit_x); tby.on_submit(submit_y)

    # Mappingoverzicht van IP → sleutel (A/B/C)
    map_text = ax_map.text(0.01, -0.12, "IP → Key: (wachten…)",
                           transform=ax_map.transAxes, va="top", ha="left")

    # --------------------------------------------
    # RENDER-LOOP
    # --------------------------------------------
    while True:
        now = time.time()
        # Inactieve buffers legen (ouder dan WINDOW_S)
        for k in ANC_ORDER:
            if (now - last_ts[k]) > WINDOW_S:
                rssi_buf[k].clear()

        pts, dists, lines = [], [], []
        for k in ANC_ORDER:
            if rssi_buf[k]:
                # Gemiddelde RSSI over laatste AVG_N_MSGS metingen (ruis reduceren)
                mean_rssi = float(np.mean(rssi_buf[k]))

                # [F1] Afstand uit RSSI (met inputs uit sliders 'cal[k]' en mean_rssi)
                dist = rssi_to_dist(mean_rssi, cal[k]["rssi1m"], cal[k]["n"])

                # Visualisatie: cirkel rond elk anker met straal = 'dist'
                x, y = anchors[k]
                if circles[k] is not None: circles[k].remove()
                c = Circle((x, y), max(0.05, dist), fill=False, alpha=0.35)
                ax_map.add_patch(c); circles[k] = c

                # Verzamel inputs voor [F2]
                pts.append((x, y))
                dists.append(dist)

                # Info-regel voor overlay
                lines.append(f"{k}: d={dist:.2f}m • RSSĪ={mean_rssi:.1f}  (1m={cal[k]['rssi1m']:.1f}, n={cal[k]['n']:.2f})")
            else:
                # Geen recente data → verwijder eventuele oude cirkel
                if circles[k] is not None: circles[k].remove(); circles[k] = None

        # [F2] Trilateratie als er ≥3 geldige ankers zijn
        if len(pts) >= 3:
            try:
                px, py = trilaterate(pts, dists)  # gebruikt 'pts' (anchors) en 'dists' uit [F1]
                est_dot.set_data([px], [py])
                info_txt.set_text(" | ".join(lines) + f"\nEST ≈ ({px:.2f}, {py:.2f}) m")
            except Exception as e:
                est_dot.set_data([], []); info_txt.set_text("Trilateratie fout: " + str(e))
        else:
            est_dot.set_data([], [])
            info_txt.set_text((" | ".join(lines) if lines else "Wacht op metingen…")
                              + "\n(≥3 recente ankers nodig)")

        # Update RAW-paneel en IP→Key mapping
        raw_text.set_text("\n".join(raw_log) if raw_log else "(nog geen data)")
        map_text.set_text("IP → Key: " + (", ".join([f"{ip}→{k}" for ip, k in ip_to_key.items()]) if ip_to_key else "(wachten…)"))

        # Render
        fig.canvas.draw_idle()
        plt.pause(0.05)

if __name__ == "__main__":
    main()
