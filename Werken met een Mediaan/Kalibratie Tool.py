import matplotlib
matplotlib.use("TkAgg")

import socket, json, time, threading, collections, csv, os
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Button, RadioButtons, Slider

# -----------------------------
# Instellingen
# -----------------------------
PORT, MED_WINDOW = 5006, 250         # UDP-poort en median-buffergrootte
ANC_ORDER = ["A", "B", "C"]          # Sleutels voor 3 Pi-ankers

# -----------------------------
# State (runtime opslag)
# -----------------------------
ip_to_key, unused_keys = {}, ANC_ORDER.copy()            # dynamische IP→Key mapping
last_ts  = {k: 0.0 for k in ANC_ORDER}                   # laatst ontvangen timestamp per key
pi_name  = {k: ""  for k in ANC_ORDER}                   # optionele Pi-hostname
buffers  = {k: collections.deque(maxlen=MED_WINDOW) for k in ANC_ORDER}  # mediane vensters
fill_on  = {k: False for k in ANC_ORDER}                 # of een buffer actief vult

points = []                                   # lijst met vaste kalibratiepunten (dicts)
state  = {"selected_key": "A", "DIST": 1.0}   # huidig geselecteerde Pi en afstand (m)

# CSV-opname (RAW + ‘LEG_VAST’-events)
rec_active = False
_rec_rows, _rec_lock = [], threading.Lock()
CSV_HEADER = [
    "event","host_time","key","pi_name","payload_ts",
    "rssi_dbm","agg_mode","agg_N","dist_m","rssi_value","samples_in_buffer"
]

def _rec_add(row):
    """Voeg rij toe aan opnamesessie (als rec_active=True)."""
    if not rec_active: return
    with _rec_lock:
        _rec_rows.append({k: row.get(k, "") for k in CSV_HEADER})

def _rec_export():
    """Schrijf opnamesessie weg naar timestamped CSV; retourneer pad of None."""
    if not _rec_rows: return None
    fname = f"rssi_session_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    try:
        with _rec_lock:
            rows = list(_rec_rows)
        with open(fname, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_HEADER)
            w.writeheader(); w.writerows(rows)
        return os.path.abspath(fname)
    except OSError:
        return None

# -----------------------------
# Meet/fit helpers
# -----------------------------
def current_median(key):
    """Mediane RSSI en samplecount uit buffer van key (of (None,0))."""
    buf = buffers[key]
    if not buf: return None, 0
    arr = np.asarray(buf, float)
    return float(np.median(arr)), len(arr)

def fit_log_model(distances, rssi_values):
    """
    Fit rssi = a + b*log10(d) met least squares.
    Retourneert: a, b, n(-b/10), R^2.
    """
    ds = np.asarray(distances, float); ys = np.asarray(rssi_values, float)
    mask = ds > 0
    if np.sum(mask) < 2: raise ValueError("min. 2 punten met d>0 nodig")
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
    """Leeg de mediane buffer van key."""
    buffers[key].clear()

# -----------------------------
# UDP-listener (ontvangst Pi-data)
# -----------------------------
def listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", PORT))
    print(f"[CAL] listening UDP :{PORT}")
    while True:
        data, addr = sock.recvfrom(65535)
        ip, _ = addr; host_now = time.time()
        # JSON payload decoderen
        try:
            m = json.loads(data.decode("utf-8", errors="replace").strip())
        except json.JSONDecodeError:
            continue
        # Eerste 3 unieke IP's krijgen A/B/C
        key = ip_to_key.get(ip)
        if key is None and unused_keys:
            key = unused_keys.pop(0); ip_to_key[ip] = key
            print(f"[assign] {ip} → {key}")
        if key is None: continue  # extra IP's negeren

        # Waarden uit payload
        try:
            rssi = float(m["rssi_dbm"]); ts = float(m["ts"])
        except (KeyError, TypeError, ValueError):
            continue
        if m.get("pi"): pi_name[key] = str(m["pi"])
        last_ts[key] = ts

        # Voeg toe aan buffer zolang 'fill_on[key]' actief is
        if fill_on.get(key, False):
            buffers[key].append(rssi)

        # Log eventueel RAW in CSV
        _rec_add({
            "event":"RAW","host_time":f"{host_now:.3f}","key":key,"pi_name":pi_name.get(key,""),
            "payload_ts":f"{ts:.3f}","rssi_dbm":f"{rssi:.2f}","agg_mode":"median","agg_N":str(MED_WINDOW),
            "dist_m":"","rssi_value":"","samples_in_buffer":""
        })

# -----------------------------
# GUI
# -----------------------------
def main():
    threading.Thread(target=listener, daemon=True).start()

    plt.rcParams.update({"font.size": 10})
    fig = plt.figure(figsize=(12.0, 7.2))
    # Ruime ondermarge en duidelijke layout (add_axes = figuurfracties)
    fig.subplots_adjust(left=0.06, right=0.98, bottom=0.16, top=0.94)

    # --- Rechter plot (statische assen) -------------------------------------
    ax = fig.add_axes([0.40, 0.22, 0.58, 0.70])
    ax.set_title("Calibration: RSSI (dBm) vs distance (m)")
    ax.set_xlabel("distance d (m)")
    ax.set_ylabel("RSSI (dBm)")
    ax.grid(True, alpha=0.25)
    ax.set_xlim(0.0, 10.0)
    ax.set_ylim(-100.0, -30.0)
    scat = ax.scatter([], [], label="points")
    fit_line, = ax.plot([], [], lw=1.8, label="fit")
    ax.legend(loc="lower right")

    # a,b,n,R² in hoek van de grafiek (zodat het nooit botst met de x-as)
    metrics_txt = ax.text(
        0.02, 0.98, "Add \u2265 2 points with d>0 to compute a, b, n, R\u00b2",
        transform=ax.transAxes, va="top", ha="left",
        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="0.8", alpha=0.9)
    )

    # --- Linker bediening (Pi, afstand, acties) -----------------------------
    ax_radio = fig.add_axes([0.06, 0.78, 0.26, 0.12]); ax_radio.set_title("Select Pi")
    radio = RadioButtons(ax_radio, ANC_ORDER, active=0)
    def on_radio(label):
        state["selected_key"] = label
        for k in ANC_ORDER: fill_on[k] = False
        clear_buffer(label)
    radio.on_clicked(on_radio)

    ax_dist = fig.add_axes([0.06, 0.70, 0.26, 0.05])
    sl_dist = Slider(ax_dist, "Distance (m)", 0.0, 10.0, valinit=state["DIST"], valstep=0.5)
    # Label binnen de slider-as houden
    sl_dist.label.set_horizontalalignment("left"); sl_dist.label.set_x(0.02)
    sl_dist.on_changed(lambda v: state.update(DIST=float(v)))

    # Knoppen: buffer, puntenbeheer, opname
    ax_start = fig.add_axes([0.06, 0.58, 0.12, 0.07]); btn_start = Button(ax_start, "Start buffer")
    ax_fix   = fig.add_axes([0.20, 0.58, 0.12, 0.07]); btn_fix   = Button(ax_fix,   "Fix point")
    ax_undo  = fig.add_axes([0.06, 0.49, 0.12, 0.07]); btn_undo  = Button(ax_undo,  "Undo")
    ax_clear = fig.add_axes([0.20, 0.49, 0.12, 0.07]); btn_clear = Button(ax_clear, "Clear")

    ax_rec_start = fig.add_axes([0.06, 0.33, 0.12, 0.07]); btn_rec_start = Button(ax_rec_start, "Start rec")
    ax_rec_stop  = fig.add_axes([0.20, 0.33, 0.12, 0.07]); btn_rec_stop  = Button(ax_rec_stop,  "Stop+Export")

    # Statusregel (rec/rows/bufferstand)
    ax_status = fig.add_axes([0.06, 0.22, 0.26, 0.07]); ax_status.axis("off")
    status_txt = ax_status.text(0.0, 0.5, "Rec: OFF | rows=0", va="center", family="monospace")

    def _status(extra=""):
        """Werk statusregel bij: opname, aantal rijen, bufferstand/size."""
        with _rec_lock: n = len(_rec_rows)
        k = state["selected_key"]; _, cnt = current_median(k)
        s = f"Rec: {'ON' if rec_active else 'OFF'} | rows={n} | Buffer[{k}]: {'FILL' if fill_on[k] else 'PAUSE'} {cnt}/{MED_WINDOW}"
        if extra: s += f" | {extra}"
        status_txt.set_text(s)

    # --- Button handlers -----------------------------------------------------
    def on_start(_):
        """Start vullen van de mediane buffer voor de huidige Pi."""
        k = state["selected_key"]; clear_buffer(k)
        for kk in ANC_ORDER: fill_on[kk] = False
        fill_on[k] = True; _status("buffer started")

    def on_fix(_):
        """Leg punt vast met (afstand, mediane RSSI, #samples) en pauzeer buffer."""
        k = state["selected_key"]; med, cnt = current_median(k)
        if med is None: _status("no samples"); return
        d = float(state["DIST"])
        points.append({"key": k, "dist": d, "rssi": med, "ts": time.time(), "samples": cnt})
        _rec_add({
            "event":"LEG_VAST","host_time":f"{time.time():.3f}","key":k,"pi_name":pi_name.get(k,""),
            "payload_ts":"","rssi_dbm":"","agg_mode":"median","agg_N":str(MED_WINDOW),
            "dist_m":f"{d:.3f}","rssi_value":f"{med:.2f}","samples_in_buffer":str(cnt)
        })
        clear_buffer(k); fill_on[k] = False; _status("point fixed")

    def on_undo(_):
        if points: points.pop(); _status("undo")

    def on_clear(_):
        points.clear(); _status("cleared")

    def on_rec_start(_):
        """Start nieuwe CSV-opnamesessie (reset buffer met rijen)."""
        global rec_active, _rec_rows
        with _rec_lock: _rec_rows = []
        rec_active = True; _status("rec started")

    def on_rec_stop(_):
        """Stop opname en exporteer CSV (indien data)."""
        global rec_active
        rec_active = False
        path = _rec_export()
        _status("CSV saved" if path else "no data")

    # Buttons koppelen
    btn_start.on_clicked(on_start); btn_fix.on_clicked(on_fix)
    btn_undo.on_clicked(on_undo);   btn_clear.on_clicked(on_clear)
    btn_rec_start.on_clicked(on_rec_start); btn_rec_stop.on_clicked(on_rec_stop)

    # -----------------------------
    # Render-loop (punten + fit)
    # -----------------------------
    while True:
        # Update scatter met vaste punten
        xs = [p["dist"] for p in points]; ys = [p["rssi"] for p in points]
        scat.set_offsets(np.c_[xs, ys] if xs else np.empty((0, 2)))

        # Trek/refresh fitlijn zodra ≥2 punten met d>0
        if len(xs) >= 2 and np.sum(np.asarray(xs) > 0) >= 2:
            try:
                a, b, n, r2 = fit_log_model(xs, ys)
                xfit = np.linspace(0.1, 10.0, 200)  # 0.1 om log10(0) te vermijden
                fit_line.set_data(xfit, a + b * np.log10(xfit))
                metrics_txt.set_text(f"a={a:.2f} dBm   b={b:.3f}   n={n:.3f}   R\u00b2={r2:.3f}")
            except Exception as e:
                fit_line.set_data([], []); metrics_txt.set_text(f"Fit error: {e}")
        else:
            fit_line.set_data([], [])
            metrics_txt.set_text("Add \u2265 2 points with d>0 to compute a, b, n, R\u00b2")

        _status()
        fig.canvas.draw_idle()
        plt.pause(0.05)

if __name__ == "__main__":
    main()
