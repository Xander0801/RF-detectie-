import matplotlib
matplotlib.use("TkAgg")  # Forceer TkAgg-backend voor interactieve GUI

import json, time, threading, collections
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from matplotlib.widgets import Slider, TextBox
import serial

# =============================
# Instellingen (LoRa/vensters)
# =============================
SERIAL_PORT   = "COM9"      # Windows: COM9, Linux bv "/dev/ttyUSB0"
BAUDRATE      = 115200
WINDOW_S      = 6.0         # Inactivevenster: buffers leeg na >6 s geen data
MED_WINDOW_N  = 30          # Ruisfilter: rollende mediaan over N samples
RAW_KEEP      = 40          # Max #regels in RAW-tekstpaneel

# Ankers + init kalibratie (rssi@1m, n)
ANC_ORDER   = ["A", "B", "C"]
ANCHOR_INIT = {"A": (0.0, 0.0), "B": (0.0, 2.0), "C": (2.0, 1.0)}
CAL_INIT    = {k: {"rssi1m": -55.0, "n": 2.2} for k in ANC_ORDER}

# =============================
# State (buffers en configuratie)
# =============================
ip_to_key, unused_keys = {}, ANC_ORDER.copy()                   # dynamische identifier → A/B/C
rssi_buf = {k: collections.deque(maxlen=MED_WINDOW_N) for k in ANC_ORDER}
last_ts  = {k: 0.0 for k in ANC_ORDER}
anchors  = {k: [*ANCHOR_INIT[k]] for k in ANC_ORDER}            # mutabel voor textbox-updates
cal      = {k: dict(CAL_INIT[k]) for k in ANC_ORDER}
circles  = {k: None for k in ANC_ORDER}                         # grafische cirkels per anker
raw_log  = collections.deque(maxlen=RAW_KEEP)

# =============================
# Helpers
# =============================
def fmt_raw(id_str, port, key, m):
    """Maak 1 compacte RAW-regel (tijd, ID, key, rssi)."""
    try:
        r = float(m.get("rssi_dbm", 0.0)); ts = float(m.get("ts", time.time()))
    except Exception:
        r, ts = 0.0, time.time()
    t = time.strftime("%H:%M:%S", time.localtime(ts))
    k = key if key else "?"
    return f"{t} {id_str}:{port} [{k}] rssi={r:.1f}"[:70]

def rssi_to_dist(rssi, rssi1m, n):
    return 10 ** ((rssi1m - rssi) / (10.0 * n))

def trilaterate(points_xy, dists):
    (x1, y1), d1 = points_xy[0], dists[0]
    A, b = [], []
    for (xi, yi), di in zip(points_xy[1:], dists[1:]):
        A.append([2*(xi-x1), 2*(yi-y1)])
        b.append((xi*xi + yi*yi - di*di) - (x1*x1 + y1*y1 - d1*d1))
    A, b = np.asarray(A, float), np.asarray(b, float)
    xy, *_ = np.linalg.lstsq(A, b, rcond=None)
    return float(xy[0]), float(xy[1])

# =============================
# Serial-listener (ontvang Pi-telemetrie via LoRa)
# =============================
def listener():
    try:
        ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1)
        print(f"[GUI] Listening on serial {SERIAL_PORT} @ {BAUDRATE}")
    except Exception as e:
        print(f"[GUI] Kan seriële poort {SERIAL_PORT} niet openen:", e)
        return

    while True:
        try:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue

            # JSON parsen
            try:
                m = json.loads(line)
            except Exception as e:
                raw_log.appendleft(f"{SERIAL_PORT} <bad JSON> {e}")
                continue

            # Eerste 3 unieke apparaten krijgen A/B/C
            device_id = m["pi"]  # unieke hostnaam van Pi
            key = ip_to_key.get(device_id)
            if key is None and unused_keys:
                key = unused_keys.pop(0)
                ip_to_key[device_id] = key
                print(f"[assign] LORA → {key}")

            raw_log.appendleft(fmt_raw("lora", 0, key, m))

            # RSSI buffer + timestamp
            try:
                rssi = float(m["rssi_dbm"])
                ts = float(m["ts"])
            except Exception:
                continue
            rssi_buf[key].append(rssi)
            last_ts[key] = ts

        except Exception as e:
            print("[Serial read error]", e)

# =============================
# GUI en render-loop
# =============================
def main():
    # Start serial listener in achtergrondthread
    threading.Thread(target=listener, daemon=True).start()

    # Basis figure/axes
    plt.rcParams.update({"font.size": 10})
    fig = plt.figure(figsize=(12.6, 7.0))
    fig.subplots_adjust(left=0.02, right=0.98, bottom=0.06, top=0.95)

    # Linkerkolom: IP→Key-overzicht
    ax_left = fig.add_axes([0.02, 0.50, 0.14, 0.46]); ax_left.axis("off")
    map_text = ax_left.text(0.0, 1.0, "ID→Key (wachten…)", va="top",
                            family="monospace", fontsize=9,
                            bbox=dict(boxstyle="round", fc="white", alpha=0.9))

    # Midden: kaart met ankers/cirkels/estimate
    ax = fig.add_axes([0.20, 0.28, 0.46, 0.66])
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("x (m)"); ax.set_ylabel("y (m)")
    ax.grid(True, alpha=0.25)

    def set_limits():
        xs = [anchors[k][0] for k in ANC_ORDER]
        ys = [anchors[k][1] for k in ANC_ORDER]
        pad = 2.0
        ax.set_xlim(min(xs)-pad, max(xs)+pad)
        ax.set_ylim(min(ys)-pad, max(ys)+pad)
    set_limits()

    scatter = {k: ax.scatter([anchors[k][0]], [anchors[k][1]], marker="^", s=60) for k in ANC_ORDER}
    labels  = {k: ax.text(anchors[k][0]+0.12, anchors[k][1]+0.12, k, weight="bold") for k in ANC_ORDER}
    est_dot, = ax.plot([], [], "o", ms=9)
    info_txt = ax.text(0.01, 0.99, "", transform=ax.transAxes, va="top",
                       bbox=dict(boxstyle="round", fc="white", alpha=0.85))

    # Rechtsboven: RAW-log
    ax_raw = fig.add_axes([0.70, 0.64, 0.27, 0.30]); ax_raw.axis("off")
    raw_text = ax_raw.text(0.0, 1.0, "(no data)", va="top", family="monospace")

    # Links onder sliders voor rssi@1m en n per anker
    sliders = []
    x_sl, w_sl = 0.02, 0.14
    y0, dy, h = 0.47, 0.035, 0.028
    i = 0
    for k in ANC_ORDER:
        for (label, vmin, vmax, v0, fld) in (
            (f"{k} rssi@1m", -80.0, -30.0, cal[k]["rssi1m"], "rssi1m"),
            (f"{k} n",        1.6,    3.5,  cal[k]["n"],       "n"),
        ):
            a = fig.add_axes([x_sl, y0 - dy*i, w_sl, h])
            sl = Slider(a, label, vmin, vmax, valinit=v0, valfmt="%.2f")
            sl.on_changed(lambda _v, kk=k, f=fld, s=sl: cal[kk].__setitem__(f, float(s.val)))
            sliders.append(sl); i += 1

    # TextBoxen om ankerposities aan te passen
    def make_pos_boxes(k, x0):
        def _box(label, init, onsubmit):
            a = fig.add_axes([x0, 0.13 if "x" in label else 0.06, 0.08, 0.06])
            tb = TextBox(a, label, initial=str(init)); tb.on_submit(onsubmit); return tb
        def sx(txt):
            try:
                anchors[k][0] = float(txt); scatter[k].set_offsets([anchors[k][0], anchors[k][1]])
                labels[k].set_position((anchors[k][0]+0.12, anchors[k][1]+0.12)); set_limits()
            except Exception: pass
        def sy(txt):
            try:
                anchors[k][1] = float(txt); scatter[k].set_offsets([anchors[k][0], anchors[k][1]])
                labels[k].set_position((anchors[k][0]+0.12, anchors[k][1]+0.12)); set_limits()
            except Exception: pass
        _box(f"{k} x", anchors[k][0], sx); _box(f"{k} y", anchors[k][1], sy)

    fig.text(0.20, 0.22, "Ankerposities (m):", weight="bold")
    for k, x0 in zip(ANC_ORDER, [0.20, 0.36, 0.52]): make_pos_boxes(k, x0)

    # =============================
    # Render-loop
    # =============================
    while True:
        now = time.time()
        for k in ANC_ORDER:
            if (now - last_ts[k]) > WINDOW_S:
                rssi_buf[k].clear()

        pts, dists, lines = [], [], []
        for k in ANC_ORDER:
            if rssi_buf[k]:
                med = float(np.median(np.asarray(rssi_buf[k], float)))
                d   = rssi_to_dist(med, cal[k]["rssi1m"], cal[k]["n"])
                x, y = anchors[k]
                if circles[k] is not None: circles[k].remove()
                c = Circle((x, y), max(0.05, d), fill=False, alpha=0.35)
                ax.add_patch(c); circles[k] = c
                pts.append((x, y)); dists.append(d)
                lines.append(f"{k}: d={d:.2f}m • RSSI~{med:.1f}")
            elif circles[k] is not None:
                circles[k].remove(); circles[k] = None

        if len(pts) >= 3:
            try:
                px, py = trilaterate(pts, dists)
                est_dot.set_data([px], [py])
                info_txt.set_text(" | ".join(lines) + f"\nEST ≈ ({px:.2f}, {py:.2f}) m")
            except Exception:
                est_dot.set_data([], []); info_txt.set_text(f"Trilateratie fout")
        else:
            est_dot.set_data([], []); info_txt.set_text((" | ".join(lines) if lines else "Wachten…") + "\n(≥3 ankers nodig)")

        raw_text.set_text("\n".join(raw_log) if raw_log else "(no data)")
        if ip_to_key:
            lines_map = ["ID → Key:"]
            for id_str, k in ip_to_key.items(): lines_map.append(f"  {id_str:<15} → {k}")
            map_text.set_text("\n".join(lines_map))
        else:
            map_text.set_text("ID→Key (wachten…)")

        fig.canvas.draw_idle()
        plt.pause(0.05)

if __name__ == "__main__":
    main()
