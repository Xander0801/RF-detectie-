# rssi_calibrator_with_histogram_layout.py
# CSV-velden per RAW-signaal: host_ip, rssi_dbm, dist_m
import matplotlib
matplotlib.use("TkAgg")

import socket, json, time, threading, collections, csv, os
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Button, RadioButtons, Slider

# ----------------------------- Instellingen -----------------------------
PORT        = 5006
MED_WINDOW  = 500                  # bufferlengte (freeze bij 500)
ANC_ORDER   = ["A", "B", "C"]

# ----------------------------- State ------------------------------------
ip_to_key, unused_keys = {}, ANC_ORDER.copy()
last_ts  = {k: 0.0 for k in ANC_ORDER}
pi_name  = {k: ""  for k in ANC_ORDER}
buffers  = {k: collections.deque(maxlen=MED_WINDOW) for k in ANC_ORDER}
fill_on  = {k: False for k in ANC_ORDER}

points = []                        # vaste kalibratiepunten
state  = {"selected_key": "A", "DIST": 1.0}

# ----------------------------- CSV (RAW) --------------------------------
rec_active = False
_rec_rows, _rec_lock = [], threading.Lock()
CSV_HEADER = ["host_ip", "rssi_dbm", "dist_m"]   # exact: host-ip, rssi_dbm, dist_m

def _rec_add(row):
    if not rec_active:
        return
    with _rec_lock:
        _rec_rows.append({k: row.get(k, "") for k in CSV_HEADER})

def _rec_export():
    if not _rec_rows:
        return None
    # afstand in bestandsnaam op moment van export
    d = float(state["DIST"])
    fname = f"rssi_session_{time.strftime('%Y%m%d_%H%M%S')}_d{d:.2f}m.csv"
    try:
        with _rec_lock:
            rows = list(_rec_rows)
        with open(fname, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_HEADER)
            w.writeheader()
            w.writerows(rows)
        return os.path.abspath(fname)
    except OSError:
        return None

# ----------------------------- Helpers ----------------------------------
def current_median(key):
    buf = buffers[key]
    if not buf:
        return None, 0
    arr = np.asarray(buf, float)
    return float(np.median(arr)), len(arr)

def fit_log_model(distances, rssi_values):
    ds = np.asarray(distances, float); ys = np.asarray(rssi_values, float)
    mask = ds > 0
    if np.sum(mask) < 2:
        raise ValueError("min. 2 punten met d>0 nodig")
    x = np.log10(ds[mask]); y = ys[mask]
    X = np.vstack([np.ones_like(x), x]).T
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    a, b = float(coef[0]), float(coef[1])
    yhat = X @ coef
    ss_res = float(np.sum((y - yhat)**2))
    ss_tot = float(np.sum((y - np.mean(y))**2))
    r2 = 1.0 - ss_res/ss_tot if ss_tot > 0 else 1.0
    return a, b, (-b/10.0), r2

def clear_buffer(key):
    buffers[key].clear()

# ----------------------------- UDP listener ------------------------------
def listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", PORT))
    print(f"[CAL] listening UDP :{PORT}")
    while True:
        data, addr = sock.recvfrom(65535)
        ip, _ = addr
        try:
            m = json.loads(data.decode("utf-8", errors="replace").strip())
        except json.JSONDecodeError:
            continue

        key = ip_to_key.get(ip)
        if key is None and unused_keys:
            key = unused_keys.pop(0); ip_to_key[ip] = key
            print(f"[assign] {ip} → {key}")
        if key is None:
            continue

        try:
            rssi = float(m["rssi_dbm"]); ts = float(m["ts"])
        except (KeyError, TypeError, ValueError):
            continue

        if m.get("pi"):
            pi_name[key] = str(m["pi"])
        last_ts[key] = ts

        # Vullen tot vol; daarna automatisch pauzeren (freeze histogram)
        if fill_on.get(key, False) and (len(buffers[key]) < MED_WINDOW):
            buffers[key].append(rssi)
            if len(buffers[key]) >= MED_WINDOW:
                fill_on[key] = False  # stop bij vol

        # CSV: log elk RAW-signaal van de geselecteerde Pi
        if rec_active and key == state["selected_key"]:
            _rec_add({
                "host_ip": ip,
                "rssi_dbm": f"{rssi:.2f}",
                "dist_m":  f"{float(state['DIST']):.3f}",
            })

# ----------------------------- GUI --------------------------------------
def main():
    threading.Thread(target=listener, daemon=True).start()

    plt.rcParams.update({"font.size": 10})
    fig = plt.figure(figsize=(12.0, 7.2))
    fig.subplots_adjust(left=0.06, right=0.98, bottom=0.08, top=0.94)

    # Rechter hoofdplot
    ax = fig.add_axes([0.40, 0.16, 0.58, 0.76])
    ax.set_title("Calibration: RSSI (dBm) vs distance (m)")
    ax.set_xlabel("distance d (m)")
    ax.set_ylabel("RSSI (dBm)")
    ax.grid(True, alpha=0.25)
    ax.set_xlim(0.0, 10.0)
    ax.set_ylim(-100.0, -30.0)
    scat = ax.scatter([], [], label="points")
    fit_line, = ax.plot([], [], lw=1.8, label="fit")
    ax.legend(loc="lower right")
    metrics_txt = ax.text(
        0.02, 0.98, "Add \u2265 2 points with d>0 to compute a, b, n, R\u00b2",
        transform=ax.transAxes, va="top", ha="left",
        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="0.8", alpha=0.9)
    )

    # Bediening links
    ax_radio = fig.add_axes([0.06, 0.82, 0.26, 0.12]); ax_radio.set_title("Select Pi")
    radio = RadioButtons(ax_radio, ANC_ORDER, active=0)
    def on_radio(label):
        state["selected_key"] = label
        for k in ANC_ORDER: fill_on[k] = False
        clear_buffer(label)
    radio.on_clicked(on_radio)

    ax_dist = fig.add_axes([0.06, 0.74, 0.26, 0.05])
    sl_dist = Slider(ax_dist, "Distance (m)", 0.0, 10.0, valinit=state["DIST"], valstep=0.25)  # 0.25 m stappen
    sl_dist.label.set_horizontalalignment("left"); sl_dist.label.set_x(0.02)
    sl_dist.on_changed(lambda v: state.update(DIST=float(v)))

    ax_start = fig.add_axes([0.06, 0.66, 0.12, 0.07]); btn_start = Button(ax_start, "Start buffer")
    ax_fix   = fig.add_axes([0.20, 0.66, 0.12, 0.07]); btn_fix   = Button(ax_fix,   "Fix point")
    ax_undo  = fig.add_axes([0.06, 0.58, 0.12, 0.07]); btn_undo  = Button(ax_undo,  "Undo")
    ax_clear = fig.add_axes([0.20, 0.58, 0.12, 0.07]); btn_clear = Button(ax_clear, "Clear")
    ax_rec_start = fig.add_axes([0.06, 0.46, 0.12, 0.07]); btn_rec_start = Button(ax_rec_start, "Start rec")
    ax_rec_stop  = fig.add_axes([0.20, 0.46, 0.12, 0.07]); btn_rec_stop  = Button(ax_rec_stop,  "Stop+Export")

    ax_status = fig.add_axes([0.06, 0.38, 0.32, 0.06]); ax_status.axis("off")
    status_txt = ax_status.text(0.0, 0.5, "Rec: OFF | rows=0", va="center", family="monospace")

    # Histogram links-onder (x-as: -80 .. -10 dBm)
    ax_hist = fig.add_axes([0.06, 0.10, 0.33, 0.26])
    ax_hist.set_title("Buffer histogram (selected Pi)")
    ax_hist.set_xlabel("RSSI (dBm)")
    ax_hist.set_ylabel("count")
    ax_hist.set_xlim(-80, -10)
    ax_hist.set_ylim(0, 1)
    bin_edges = np.arange(-80, -10 + 1, 1)
    bars = ax_hist.bar(bin_edges[:-1], np.zeros(len(bin_edges)-1), width=1.0, align="edge", edgecolor="none")
    mean_line,   = ax_hist.plot([], [], linewidth=2, label="mean")
    median_line, = ax_hist.plot([], [], linestyle="--", linewidth=2, label="median")
    p05_line,    = ax_hist.plot([], [], linestyle=":", linewidth=2, label="p5")
    p95_line,    = ax_hist.plot([], [], linestyle=":", linewidth=2, label="p95")
    ax_hist.legend(loc="upper right", fontsize=8)

    # Tekst onder de histogram-as met getallen
    ax_hist_info = fig.add_axes([0.06, 0.06, 0.33, 0.03]); ax_hist_info.axis("off")
    hist_info_txt = ax_hist_info.text(0.0, 0.5, "", va="center", family="monospace", fontsize=9)

    # Handlers
    def _status(extra=""):
        with _rec_lock: n = len(_rec_rows)
        k = state["selected_key"]; _, cnt = current_median(k)
        s = f"Rec: {'ON' if rec_active else 'OFF'} | rows={n} | Buffer[{k}]: {'FILL' if fill_on[k] else 'PAUSE'} {cnt}/{MED_WINDOW}"
        if extra: s += f" | {extra}"
        status_txt.set_text(s)

    def on_start(_):
        k = state["selected_key"]; clear_buffer(k)
        for kk in ANC_ORDER: fill_on[kk] = False
        fill_on[k] = True; _status("buffer started")

    def on_fix(_):
        k = state["selected_key"]; med, cnt = current_median(k)
        if med is None: _status("no samples"); return
        d = float(state["DIST"])
        points.append({"key": k, "dist": d, "rssi": med, "ts": time.time(), "samples": cnt})
        clear_buffer(k); fill_on[k] = False; _status("point fixed")

    def on_undo(_):
        if points: points.pop(); _status("undo")

    def on_clear(_):
        points.clear(); _status("cleared")

    def on_rec_start(_):
        global rec_active, _rec_rows
        with _rec_lock: _rec_rows = []
        rec_active = True; _status("rec started")

    def on_rec_stop(_):
        global rec_active
        rec_active = False
        path = _rec_export()
        _status("CSV saved" if path else "no data")

    btn_start.on_clicked(on_start); btn_fix.on_clicked(on_fix)
    btn_undo.on_clicked(on_undo);   btn_clear.on_clicked(on_clear)
    btn_rec_start.on_clicked(on_rec_start); btn_rec_stop.on_clicked(on_rec_stop)

    # ----------------------------- Render-loop -----------------------------
    while True:
        # Punten + fit
        xs = [p["dist"] for p in points]; ys = [p["rssi"] for p in points]
        scat.set_offsets(np.c_[xs, ys] if xs else np.empty((0, 2)))
        if len(xs) >= 2 and np.sum(np.asarray(xs) > 0) >= 2:
            try:
                a, b, n, r2 = fit_log_model(xs, ys)
                xfit = np.linspace(0.1, 10.0, 200)
                fit_line.set_data(xfit, a + b * np.log10(xfit))
                metrics_txt.set_text(f"a={a:.2f} dBm   b={b:.3f}   n={n:.3f}   R\u00b2={r2:.3f}")
            except Exception as e:
                fit_line.set_data([], []); metrics_txt.set_text(f"Fit error: {e}")
        else:
            fit_line.set_data([], [])
            metrics_txt.set_text("Add \u2265 2 points with d>0 to compute a, b, n, R\u00b2")

        # Histogram (updaten enkel zolang buffer niet gepauzeerd is? → data stopt bij vol door listener)
        k = state["selected_key"]
        if buffers[k]:
            arr = np.asarray(buffers[k], float)
            counts, _ = np.histogram(arr, bins=bin_edges)
            for bar, h in zip(bars, counts): bar.set_height(h)
            ymax = max(1, int(counts.max() * 1.2))
            ax_hist.set_ylim(0, ymax)
            mu, med = float(np.mean(arr)), float(np.median(arr))
            p05, p95 = float(np.percentile(arr, 5)), float(np.percentile(arr, 95))
            for line, x in ((mean_line, mu), (median_line, med), (p05_line, p05), (p95_line, p95)):
                line.set_data([x, x], [0, ymax])
            hist_info_txt.set_text(f"mean={mu:.2f}  median={med:.2f}  p5={p05:.2f}  p95={p95:.2f}")
        else:
            for bar in bars: bar.set_height(0)
            for line in (mean_line, median_line, p05_line, p95_line):
                line.set_data([], [])
            hist_info_txt.set_text("")

        _status()
        fig.canvas.draw_idle()
        plt.pause(0.05)

if __name__ == "__main__":
    main()
