# rssi_calibrator_1d.py
# 1D RSSI-kalibratie met één geselecteerde Pi (A/B/C)
# Links: 1D-lijn met marker op gekozen afstand (slider snapt per 0.5 m)
# Rechts: log-x grafiek RSSI(dBm) vs afstand (m) + "Leg vast" om punten te pinnen
# Fit-model: rssi = a + b*log10(d)  → rssi1m = a,  n = -b/10

import matplotlib
matplotlib.use("TkAgg")

import socket, json, time, threading, collections, csv, os
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Button, RadioButtons, Slider

# ---------------------------
# Instellingen
# ---------------------------
PORT      = 5006          # UDP-poort waarop Pi's zenden
WINDOW_S  = 6.0           # seconds; ouder dan dit = buffer leegmaken
BUF_N0    = 20            # startwaarde samples in ruisgemiddelde
RAW_KEEP  = 60            # ruwe regels bijhouden in paneel
ANC_ORDER = ["A", "B", "C"]
CSV_FILE  = "rssi_calibration_points.csv"

# ---------------------------
# State
# ---------------------------
ip_to_key, unused_keys = {}, ANC_ORDER.copy()
raw_log  = collections.deque(maxlen=RAW_KEEP)
rssi_buf = {k: collections.deque(maxlen=BUF_N0) for k in ANC_ORDER}
last_ts  = {k: 0.0 for k in ANC_ORDER}
pi_name  = {k: "" for k in ANC_ORDER}  # optioneel label uit payload

state = {
    "selected_key": "A",
    "agg_mode": "mean",     # "mean" of "median"
    "D_MAX": 10.0,          # x-as max voor 1D-lijn en log-plot
    "DIST": 1.0,            # huidige afstand (m) uit slider
}

# Vastgeklikte kalibratiepunten
# elk item: {"key": "A", "dist": float meters, "rssi": float dBm, "ts": unix}
points = []

# ---------------------------
# Helpers
# ---------------------------
def fmt_raw(ip, port, key, m):
    try:
        r = float(m.get("rssi_dbm", 0.0))
        ts = float(m.get("ts", time.time()))
    except (TypeError, ValueError):
        r, ts = 0.0, time.time()
    tstr = time.strftime("%H:%M:%S", time.localtime(ts))
    name = m.get("pi", "")
    s = f"{tstr} {ip}:{port} [{key if key else '?'}] pi='{name}' rssi={r:.1f}"
    return s if len(s) <= 90 else s[:89] + "…"

def current_rssi_for(key):
    buf = rssi_buf.get(key)
    if not buf:
        return None
    arr = np.asarray(buf, float)
    return float(np.mean(arr)) if state["agg_mode"] == "mean" else float(np.median(arr))

def fit_log_model(pts):
    """
    rssi = a + b*log10(d)  (least squares)
    pts: lijst (dist_m > 0, rssi_dbm)
    retourneert: (a, b, rssi1m=a, n=-b/10, R2)
    """
    x = np.array([np.log10(p[0]) for p in pts], dtype=float)
    y = np.array([p[1] for p in pts], dtype=float)
    X = np.vstack([np.ones_like(x), x]).T
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    a, b = float(coef[0]), float(coef[1])
    yhat = X @ coef
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2)) if len(y) > 1 else 0.0
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return a, b, a, -b / 10.0, r2

# ---------------------------
# UDP listener
# ---------------------------
def listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", PORT))
    print(f"[CAL] luistert op UDP :{PORT}")
    while True:
        data, addr = sock.recvfrom(65535)
        ip, sport = addr
        txt = data.decode("utf-8", errors="replace").strip()

        try:
            m = json.loads(txt)
        except json.JSONDecodeError as e:
            raw_log.appendleft(f"{ip}:{sport} <invalid JSON> {e}")
            continue

        key = ip_to_key.get(ip)
        if key is None and unused_keys:
            key = unused_keys.pop(0)
            ip_to_key[ip] = key
            print(f"[assign] {ip} → {key}")

        raw_log.appendleft(fmt_raw(ip, sport, key, m))

        if key is None:
            continue

        try:
            rssi = float(m["rssi_dbm"])
            ts = float(m["ts"])
        except (KeyError, TypeError, ValueError):
            continue

        if m.get("pi"):
            pi_name[key] = str(m["pi"])

        last_ts[key] = ts
        rssi_buf[key].append(rssi)

# ---------------------------
# GUI
# ---------------------------
def main():
    threading.Thread(target=listener, daemon=True).start()

    plt.rcParams.update({"font.size": 10})
    fig = plt.figure(figsize=(12.5, 7.0))
    fig.subplots_adjust(left=0.04, right=0.98, bottom=0.06, top=0.95)

    # Linker 1D-lijn
    ax_line = fig.add_axes([0.06, 0.60, 0.58, 0.32])
    ax_line.set_title("1D afstandslijn (gekozen Pi → gsm)")
    ax_line.set_xlabel("afstand (m)")
    ax_line.set_xlim(0, state["D_MAX"])
    ax_line.set_ylim(-1, 1)
    ax_line.get_yaxis().set_visible(False)
    ax_line.grid(True, axis="x", alpha=0.25)
    dist_marker, = ax_line.plot([], [], marker="o", markersize=10)
    ax_line.hlines(0, 0, state["D_MAX"], linestyles="dotted", alpha=0.4)

    # Rechter log-grafiek
    ax_log = fig.add_axes([0.67, 0.10, 0.31, 0.82])
    ax_log.set_title("Kalibratie: RSSI(dBm) vs afstand (m) [log x-as]")
    ax_log.set_xscale("log")
    ax_log.set_xlabel("afstand d (m)")
    ax_log.set_ylabel("RSSI (dBm)")
    ax_log.grid(True, which="both", axis="x", alpha=0.25)
    ax_log.grid(True, which="major", axis="y", alpha=0.25)
    scat = ax_log.scatter([], [])
    live_pt, = ax_log.plot([], [], marker="x", linestyle="None", alpha=0.6, label="live")
    fit_line, = ax_log.plot([], [], linestyle="-", alpha=0.7, label="fit")
    ax_log.legend(loc="lower left")
    info_txt = ax_log.text(0.02, 0.98, "", transform=ax_log.transAxes,
                           va="top", ha="left",
                           bbox=dict(boxstyle="round", fc="white", alpha=0.85))

    # IP ↔ Key-tabel (onder 1D-lijn)
    ax_tab = fig.add_axes([0.06, 0.48, 0.58, 0.10]); ax_tab.axis("off")
    tab_text = ax_tab.text(0.01, 0.9, "IP ↔ Key (wachten…)\n",
                           va="top", family="monospace")

    # ---- Besturingen ----
    ax_radio = fig.add_axes([0.06, 0.34, 0.12, 0.12])
    radio = RadioButtons(ax_radio, ANC_ORDER, active=0)
    ax_radio.set_title("Kies Pi")
    def on_radio(label):
        state["selected_key"] = label
    radio.on_clicked(on_radio)

    ax_radio2 = fig.add_axes([0.20, 0.34, 0.14, 0.12])
    radio2 = RadioButtons(ax_radio2, ["mean", "median"], active=0)
    ax_radio2.set_title("Ruisfilter")
    def on_radio2(label):
        state["agg_mode"] = label
    radio2.on_clicked(on_radio2)

    ax_n = fig.add_axes([0.36, 0.38, 0.28, 0.04])
    sl_n = Slider(ax_n, "Samples N", 5, 100, valinit=BUF_N0, valfmt="%.0f")
    def on_sl_n(val):
        n = int(round(val))
        for k in ANC_ORDER:
            old = list(rssi_buf[k])
            rssi_buf[k] = collections.deque(old[-n:], maxlen=n)
    sl_n.on_changed(on_sl_n)

    # Afstand-slider: 0.5–30 m, stap 0.5 m
    ax_dist = fig.add_axes([0.36, 0.32, 0.28, 0.04])
    sl_dist = Slider(ax_dist, "Afstand (m)", 0.5, 30.0, valinit=state["DIST"], valstep=0.5)
    def on_dist(val):
        state["DIST"] = float(val)
    sl_dist.on_changed(on_dist)

    # Knoppen
    ax_fix   = fig.add_axes([0.06, 0.20, 0.14, 0.07]);   btn_fix   = Button(ax_fix, "Leg vast")
    ax_undo  = fig.add_axes([0.22, 0.20, 0.12, 0.07]);   btn_undo  = Button(ax_undo, "Undo")
    ax_clear = fig.add_axes([0.36, 0.20, 0.12, 0.07]);   btn_clear = Button(ax_clear, "Clear")
    ax_save  = fig.add_axes([0.50, 0.20, 0.20, 0.07]);   btn_save  = Button(ax_save, "Export CSV")

    def on_fix(_):
        d = max(0.5, float(state["DIST"]))  # veiligheid: d>0
        r = current_rssi_for(state["selected_key"])
        if r is None:
            return
        points.append({"key": state["selected_key"], "dist": d, "rssi": r, "ts": time.time()})

    def on_undo(_):
        if points:
            points.pop()

    def on_clear(_):
        points.clear()

    def on_save(_):
        rows = [("ts","key","dist_m","rssi_dbm")]
        for p in points:
            rows.append((int(p["ts"]), p["key"], f"{p['dist']:.3f}", f"{p['rssi']:.2f}"))
        try:
            with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows(rows)
            print(f"[CSV] weggeschreven → {os.path.abspath(CSV_FILE)}")
        except OSError as e:
            print("[CSV] fout:", e)

    btn_fix.on_clicked(on_fix)
    btn_undo.on_clicked(on_undo)
    btn_clear.on_clicked(on_clear)
    btn_save.on_clicked(on_save)

    # Xmax-slider (voor beide panelen handig)
    ax_dmax = fig.add_axes([0.72, 0.20, 0.17, 0.07])
    sl_dmax = Slider(ax_dmax, "Xmax (m)", 5, 30, valinit=state["D_MAX"], valfmt="%.0f")
    def on_dmax(val):
        state["D_MAX"] = float(val)
        ax_line.set_xlim(0, state["D_MAX"])
        ax_line.figure.canvas.draw_idle()
    sl_dmax.on_changed(on_dmax)

    # ---------------------------
    # Render-loop
    # ---------------------------
    while True:
        now = time.time()
        for k in ANC_ORDER:
            if (now - last_ts[k]) > WINDOW_S:
                rssi_buf[k].clear()

        # 1D marker
        d_cur = max(0.5, float(state["DIST"]))
        dist_marker.set_data([d_cur], [0.0])
        ax_line.set_xlim(0, state["D_MAX"])

        # ----- Data voor rechter plot -----
        # verzamel geldige (d>0) punten
        xs_pts = [p["dist"] for p in points if p["dist"] > 0]
        ys_pts = [p["rssi"] for p in points if p["dist"] > 0]

        # live punt
        live_r = current_rssi_for(state["selected_key"])
        if live_r is not None:
            live_pt.set_data([d_cur], [live_r])
        else:
            live_pt.set_data([], [])

        # vaste punten plotten
        if xs_pts:
            scat.set_offsets(np.c_[xs_pts, ys_pts])
        else:
            scat.set_offsets(np.empty((0, 2)))

        # X-limieten van log-plot EXPLICIET zetten (nooit autoscale op x)
        xmax_data = max(xs_pts) if xs_pts else 0.5
        x_max = max(0.5, state["D_MAX"], d_cur, xmax_data)
        ax_log.set_xlim(0.5, x_max)

        # Fit tekenen + parameters tonen (alleen als ≥2 punten)
        if len(xs_pts) >= 2:
            try:
                a, b, rssi1m, n, r2 = fit_log_model(list(zip(xs_pts, ys_pts)))
                # Gebruik logspace binnen [0.5, x_max]
                xfit = np.logspace(np.log10(0.5), np.log10(x_max), 200)
                yfit = a + b * np.log10(xfit)
                fit_line.set_data(xfit, yfit)
                fit_info = (f"Fit: rssi = a + b·log10(d)\n"
                            f"a = {a:.2f} dBm  (rssi1m)\n"
                            f"b = {b:.2f}\n"
                            f"n = {n:.3f}\n"
                            f"R² = {r2:.3f}")
            except Exception as e:
                fit_line.set_data([], [])
                fit_info = f"Fit fout: {e}"
        else:
            fit_line.set_data([], [])
            fit_info = "Min. 2 punten nodig voor fit."

        # Alleen y autoscales (x blijft vast)
        ax_log.relim()
        ax_log.autoscale_view(scalex=False, scaley=True)

        mode_label = "gemiddelde" if state["agg_mode"] == "mean" else "mediaan"
        info_txt.set_text(
            (f"Pi: {state['selected_key']} | ruisfilter: {mode_label} "
             f"over N={rssi_buf[state['selected_key']].maxlen}\n") +
            (f"Actuele RSSI ≈ {live_r:.1f} dBm" if live_r is not None else "(geen live RSSI)") +
            f"\nHuidige afstand: {d_cur:.1f} m\n\n{fit_info}"
        )

        # IP ↔ Key tabel
        if ip_to_key:
            lines = ["IP ↔ Key (naam):"]
            for ip, k in ip_to_key.items():
                nm = pi_name.get(k, "")
                lines.append(f"  {ip:<15} → {k}  {('('+nm+')') if nm else ''}")
            tab_text.set_text("\n".join(lines))
        else:
            tab_text.set_text("IP ↔ Key (wachten…)")

        fig.canvas.draw_idle()
        plt.pause(0.05)

if __name__ == "__main__":
    main()
