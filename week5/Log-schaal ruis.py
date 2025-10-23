# rssi_calibrator_1d.py
# -----------------------------------------------------------------------------
# 1D RSSI-kalibratie met één geselecteerde Pi (A/B/C) + CSV-opname.
# Links: 1D-lijn met afstand-slider (0.5 m stap), rechts: log-x grafiek RSSI(dBm) vs afstand.
# Fit-model: rssi = a + b*log10(d)  → rssi1m = a,  n = -b/10.
#
# Opname:
#   - Start opname: alle binnenkomende RAW-pakketten gelogd (en Raw-venster wordt zichtbaar).
#   - Leg vast: punt pinnen én snapshot (LEG_VAST) loggen met ruisgemiddelde op die afstand.
#   - Stop + export opname: alles naar timestamped CSV.
#   - Export punten CSV: schrijft enkel de ‘Leg vast’-punten weg.
# -----------------------------------------------------------------------------

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
BUF_N0    = 20            # startwaarde samples in ruisgemiddelde (N)
RAW_KEEP  = 60            # ruwe regels bijhouden
ANC_ORDER = ["A", "B", "C"]

CSV_POINTS = "rssi_calibration_points.csv"  # enkel de ‘Leg vast’-punten

# ---------------------------
# State
# ---------------------------
ip_to_key, unused_keys = {}, ANC_ORDER.copy()  # IP → A/B/C
raw_log  = collections.deque(maxlen=RAW_KEEP)  # tekstregels voor Raw-paneel
rssi_buf = {k: collections.deque(maxlen=BUF_N0) for k in ANC_ORDER}
last_ts  = {k: 0.0 for k in ANC_ORDER}
pi_name  = {k: "" for k in ANC_ORDER}

state = {
    "selected_key": "A",
    "agg_mode": "mean",     # "mean" of "median"
    "D_MAX": 10.0,          # x-as max
    "DIST": 1.0,            # huidige afstand (m)
}

# Vastgeklikte fitpunten: {"key","dist","rssi","ts"}
points = []

# ---------------------------
# CSV-opname (RAW + LEG_VAST)
# ---------------------------
rec_active      = False
rec_rows        = []
rec_started_ts  = None
rec_last_export = None
_rec_lock       = threading.Lock()

REC_HEADER = [
    "event", "host_time", "src_ip", "src_port", "key", "pi_name",
    "payload_ts", "rssi_dbm", "agg_mode", "agg_N", "dist_m", "rssi_mean",
]

def _rec_append_row(row):
    if not rec_active:
        return
    with _rec_lock:
        rec_rows.append({k: row.get(k, "") for k in REC_HEADER})

def _export_session_csv():
    """Schrijf huidige opname weg met timestamp in bestandsnaam. Return pad of None."""
    global rec_last_export
    if not rec_rows:
        return None
    ts_label = time.strftime("%Y%m%d_%H%M%S", time.localtime(rec_started_ts or time.time()))
    fname = f"rssi_session_{ts_label}.csv"
    try:
        with _rec_lock:
            rows_copy = list(rec_rows)
        with open(fname, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=REC_HEADER)
            w.writeheader()
            for r in rows_copy:
                w.writerow(r)
        rec_last_export = os.path.abspath(fname)
        return rec_last_export
    except Exception as e:
        print("[CSV] export-fout:", e)
        return None

# ---------------------------
# Helpers
# ---------------------------
def fmt_raw(ip, port, key, m):
    """1-regelige tekst voor het Raw-paneel."""
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
    """Ruisgefilterde RSSI (mean/median) uit de buffer van key."""
    buf = rssi_buf.get(key)
    if not buf:
        return None
    arr = np.asarray(buf, float)
    return float(np.mean(arr)) if state["agg_mode"] == "mean" else float(np.median(arr))

def fit_log_model(pts):
    """
    rssi = a + b*log10(d) (least squares).
    pts: [(dist>0, rssi), ...] → (a, b, rssi1m=a, n=-b/10, R2)
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
        host_now = time.time()
        txt = data.decode("utf-8", errors="replace").strip()

        try:
            m = json.loads(txt)
        except json.JSONDecodeError as e:
            raw_log.appendleft(f"{ip}:{sport} <invalid JSON> {e}")
            continue

        # IP → A/B/C
        key = ip_to_key.get(ip)
        if key is None and unused_keys:
            key = unused_keys.pop(0)
            ip_to_key[ip] = key
            print(f"[assign] {ip} → {key}")

        raw_log.appendleft(fmt_raw(ip, sport, key, m))
        if key is None:   # meer dan 3 IP’s → negeer voor buffers/fit
            continue

        # Payloadwaarden
        try:
            rssi = float(m["rssi_dbm"])
            ts   = float(m["ts"])
        except (KeyError, TypeError, ValueError):
            continue

        if m.get("pi"):
            pi_name[key] = str(m["pi"])

        last_ts[key] = ts
        rssi_buf[key].append(rssi)

        # CSV: RAW rij (alleen tijdens opname)
        _rec_append_row({
            "event":      "RAW",
            "host_time":  f"{host_now:.3f}",
            "src_ip":     ip,
            "src_port":   str(sport),
            "key":        key,
            "pi_name":    pi_name.get(key, ""),
            "payload_ts": f"{ts:.3f}",
            "rssi_dbm":   f"{rssi:.2f}",
            "agg_mode":   "",
            "agg_N":      "",
            "dist_m":     "",
            "rssi_mean":  "",
        })

# ---------------------------
# GUI
# ---------------------------
def main():
    global rec_active, rec_started_ts, rec_rows, rec_last_export

    # Listener starten
    threading.Thread(target=listener, daemon=True).start()

    plt.rcParams.update({"font.size": 10})
    fig = plt.figure(figsize=(13.0, 7.2))
    fig.subplots_adjust(left=0.04, right=0.98, bottom=0.06, top=0.95)

    # ---- Linker 1D-lijn ------------------------------------------------------
    ax_line = fig.add_axes([0.05, 0.60, 0.55, 0.33])  # iets smaller
    ax_line.set_title("1D afstandslijn (gekozen Pi → gsm)")
    ax_line.set_xlabel("afstand (m)")
    ax_line.set_xlim(0, state["D_MAX"])
    ax_line.set_ylim(-1, 1)
    ax_line.get_yaxis().set_visible(False)
    ax_line.grid(True, axis="x", alpha=0.25)
    dist_marker, = ax_line.plot([], [], marker="o", markersize=10)
    ax_line.hlines(0, 0, state["D_MAX"], linestyles="dotted", alpha=0.4)

    # ---- Rechter log-grafiek -------------------------------------------------
    ax_log = fig.add_axes([0.62, 0.18, 0.33, 0.72])   # compacter & duidelijk naast links
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

    # ---- Raw-paneel ONDER de grafiek (niet overlappen, clip aan) ------------
    ax_raw = fig.add_axes([0.62, 0.02, 0.33, 0.13])
    ax_raw.set_facecolor("white")
    ax_raw.patch.set_alpha(1.0)
    ax_raw.set_title("Raw UDP (nieuwste boven)")
    ax_raw.axis("off")
    raw_text = ax_raw.text(0.01, 0.95, "Klik ‘Start opname’ voor live log.",
                           va="top", ha="left",
                           transform=ax_raw.transAxes,
                           family="monospace", fontsize=9)
    raw_text.set_clip_on(True)  # BELANGRIJK: geen overlap met grafiek erboven!

    # ---- IP ↔ Key-tabel (onder de 1D-lijn) ----------------------------------
    ax_tab = fig.add_axes([0.05, 0.48, 0.55, 0.10]); ax_tab.axis("off")
    tab_text = ax_tab.text(0.01, 0.9, "IP ↔ Key (wachten…)\n",
                           va="top", family="monospace")

    # ---- Besturingen links ---------------------------------------------------
    ax_radio = fig.add_axes([0.05, 0.34, 0.12, 0.12])
    radio = RadioButtons(ax_radio, ANC_ORDER, active=0)
    ax_radio.set_title("Kies Pi")
    def on_radio(label): state["selected_key"] = label
    radio.on_clicked(on_radio)

    ax_radio2 = fig.add_axes([0.19, 0.34, 0.14, 0.12])
    radio2 = RadioButtons(ax_radio2, ["mean", "median"], active=0)
    ax_radio2.set_title("Ruisfilter")
    def on_radio2(label): state["agg_mode"] = label
    radio2.on_clicked(on_radio2)

    ax_n = fig.add_axes([0.35, 0.38, 0.25, 0.04])
    sl_n = Slider(ax_n, "Samples N", 5, 100, valinit=BUF_N0, valfmt="%.0f")
    def on_sl_n(val):
        n = int(round(val))
        for k in ANC_ORDER:
            old = list(rssi_buf[k])
            rssi_buf[k] = collections.deque(old[-n:], maxlen=n)
    sl_n.on_changed(on_sl_n)

    ax_dist = fig.add_axes([0.35, 0.32, 0.25, 0.04])
    sl_dist = Slider(ax_dist, "Afstand (m)", 0.5, 30.0, valinit=state["DIST"], valstep=0.5)
    def on_dist(val): state["DIST"] = float(val)
    sl_dist.on_changed(on_dist)

    # Punt-knoppen (links onder)
    ax_fix   = fig.add_axes([0.05, 0.20, 0.14, 0.07]); btn_fix   = Button(ax_fix, "Leg vast (punt)")
    ax_undo  = fig.add_axes([0.21, 0.20, 0.12, 0.07]); btn_undo  = Button(ax_undo, "Undo")
    ax_clear = fig.add_axes([0.35, 0.20, 0.12, 0.07]); btn_clear = Button(ax_clear, "Clear")
    ax_savep = fig.add_axes([0.49, 0.20, 0.11, 0.07]); btn_savep = Button(ax_savep, "Export punten CSV")

    def on_fix(_):
        """Pin punt + snapshot loggen indien opname actief."""
        d = max(0.5, float(state["DIST"]))
        r = current_rssi_for(state["selected_key"])
        if r is None:
            return
        points.append({"key": state["selected_key"], "dist": d, "rssi": r, "ts": time.time()})
        _rec_append_row({
            "event":      "LEG_VAST",
            "host_time":  f"{time.time():.3f}",
            "src_ip":     "",
            "src_port":   "",
            "key":        state["selected_key"],
            "pi_name":    pi_name.get(state["selected_key"], ""),
            "payload_ts": "",
            "rssi_dbm":   "",
            "agg_mode":   state["agg_mode"],
            "agg_N":      str(rssi_buf[state["selected_key"]].maxlen),
            "dist_m":     f"{d:.3f}",
            "rssi_mean":  f"{r:.2f}",
        })

    def on_undo(_):
        if points:
            points.pop()

    def on_clear(_):
        points.clear()

    def on_save_points(_):
        rows = [("ts","key","dist_m","rssi_dbm")]
        for p in points:
            rows.append((int(p["ts"]), p["key"], f"{p['dist']:.3f}", f"{p['rssi']:.2f}"))
        try:
            with open(CSV_POINTS, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows(rows)
            print(f"[CSV] punten weggeschreven → {os.path.abspath(CSV_POINTS)}")
        except OSError as e:
            print("[CSV] fout punten-export:", e)

    btn_fix.on_clicked(on_fix)
    btn_undo.on_clicked(on_undo)
    btn_clear.on_clicked(on_clear)
    btn_savep.on_clicked(on_save_points)

    # ---- Rechter kolom: Xmax + opnameknoppen --------------------------------
    ax_dmax = fig.add_axes([0.62, 0.93, 0.33, 0.035])
    sl_dmax = Slider(ax_dmax, "Xmax (m)", 5, 30, valinit=state["D_MAX"], valfmt="%.0f")
    def on_dmax(val):
        state["D_MAX"] = float(val)
        ax_line.set_xlim(0, state["D_MAX"])
        ax_line.figure.canvas.draw_idle()
    sl_dmax.on_changed(on_dmax)

    ax_rec_start = fig.add_axes([0.62, 0.15, 0.16, 0.05]); btn_rec_start = Button(ax_rec_start, "Start opname")
    ax_rec_stop  = fig.add_axes([0.79, 0.15, 0.16, 0.05]); btn_rec_stop  = Button(ax_rec_stop,  "Stop + export opname")

    ax_rec_info  = fig.add_axes([0.62, 0.14, 0.33, 0.02]); ax_rec_info.axis("off")
    rec_info_txt = ax_rec_info.text(0.01, 0.5, "Opname: UIT | rijen=0", va="center", family="monospace")

    def _refresh_rec_info(extra=""):
        status = "AAN" if rec_active else "UIT"
        with _rec_lock:
            n = len(rec_rows)
        last = f" | laatste export: {rec_last_export}" if rec_last_export else ""
        if extra:
            last += f" | {extra}"
        rec_info_txt.set_text(f"Opname: {status} | rijen={n}{last}")

    def on_rec_start(_):
        """Start een nieuwe opname en toon live Raw."""
        global rec_active, rec_started_ts
        with _rec_lock:
            rec_rows.clear()
        rec_active = True
        rec_started_ts = time.time()
        _refresh_rec_info("gestart")

    def on_rec_stop(_):
        """Stop opname en exporteer sessie-CSV."""
        global rec_active
        rec_active = False
        path = _export_session_csv()
        _refresh_rec_info("CSV opgeslagen" if path else "geen data")

    btn_rec_start.on_clicked(on_rec_start)
    btn_rec_stop.on_clicked(on_rec_stop)

    # ---------------------------
    # Render-loop
    # ---------------------------
    while True:
        now = time.time()
        # buffers opruimen
        for k in ANC_ORDER:
            if (now - last_ts[k]) > WINDOW_S:
                rssi_buf[k].clear()

        # 1D marker
        d_cur = max(0.5, float(state["DIST"]))
        dist_marker.set_data([d_cur], [0.0])
        ax_line.set_xlim(0, state["D_MAX"])

        # rechter plot: vaste punten + live punt
        xs_pts = [p["dist"] for p in points if p["dist"] > 0]
        ys_pts = [p["rssi"] for p in points if p["dist"] > 0]

        live_r = current_rssi_for(state["selected_key"])
        if live_r is not None:
            live_pt.set_data([d_cur], [live_r])
        else:
            live_pt.set_data([], [])

        if xs_pts:
            scat.set_offsets(np.c_[xs_pts, ys_pts])
        else:
            scat.set_offsets(np.empty((0, 2)))

        # stabiele x-limieten
        xmax_data = max(xs_pts) if xs_pts else 0.5
        x_max = max(0.5, state["D_MAX"], d_cur, xmax_data)
        ax_log.set_xlim(0.5, x_max)

        # fit
        if len(xs_pts) >= 2:
            try:
                a, b, rssi1m, n, r2 = fit_log_model(list(zip(xs_pts, ys_pts)))
                xfit = np.logspace(np.log10(0.5), np.log10(x_max), 200)
                yfit = a + b * np.log10(xfit)
                fit_line.set_data(xfit, yfit)
                fit_info = (f"Fit: rssi = a + b·log10(d)\n"
                            f"a = {a:.2f} dBm  (rssi1m)\n"
                            f"b = {b:.2f}\n"
                            f"n = {-b/10.0:.3f}\n"
                            f"R² = {r2:.3f}")
            except Exception as e:
                fit_line.set_data([], [])
                fit_info = f"Fit fout: {e}"
        else:
            fit_line.set_data([], [])
            fit_info = "Min. 2 punten nodig voor fit."

        # alleen y autoscales
        ax_log.relim()
        ax_log.autoscale_view(scalex=False, scaley=True)

        # info-tekst
        mode_label = "gemiddelde" if state["agg_mode"] == "mean" else "mediaan"
        info_txt.set_text(
            (f"Pi: {state['selected_key']} | ruisfilter: {mode_label} "
             f"over N={rssi_buf[state['selected_key']].maxlen}\n") +
            (f"Actuele RSSI ≈ {live_r:.1f} dBm" if live_r is not None else "(geen live RSSI)") +
            f"\nHuidige afstand: {d_cur:.1f} m\n\n{fit_info}"
        )

        # Raw-paneel tonen ALLEEN tijdens opname
        if rec_active and raw_log:
            raw_text.set_text("\n".join(raw_log))
        else:
            raw_text.set_text("Klik ‘Start opname’ voor live log.")
        # (clip_on staat aan, dus geen overlopen in grafiek)

        # IP ↔ Key (links onder)
        if ip_to_key:
            lines = ["IP ↔ Key (naam):"]
            for ip, k in ip_to_key.items():
                nm = pi_name.get(k, "")
                lines.append(f"  {ip:<15} → {k}  {('('+nm+')') if nm else ''}")
            tab_text.set_text("\n".join(lines))
        else:
            tab_text.set_text("IP ↔ Key (wachten…)")

        # opname-status
        _refresh_rec_info()

        fig.canvas.draw_idle()
        plt.pause(0.05)

# Entrypoint
if __name__ == "__main__":
    main()
