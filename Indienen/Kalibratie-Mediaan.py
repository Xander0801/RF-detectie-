# rssi_calibrator_with_histogram_layout.py
# Doel:
# - Ontvangt RAW RSSI-metingen via UDP (JSON) van meerdere Raspberry Pi's (of andere zenders).
# - Buffert RSSI-samples per Pi om een stabiele mediaan te nemen.
# - Laat je kalibratiepunten “vastzetten” (distance, median RSSI) en fit een log-distance padloss model.
# - Kan alle RAW-signalen van de geselecteerde Pi opslaan naar CSV (met actuele afstand).
# - Toont tegelijk: (1) kalibratiepunten + fitcurve, en (2) histogram van de buffer (met mean/median/p5/p95).

# CSV-velden per RAW-signaal: host_ip, rssi_dbm, dist_m

import matplotlib
# Matplotlib backend op TkAgg zetten zodat een interactieve GUI-window werkt (buttons/sliders/radio).
matplotlib.use("TkAgg")

# socket/json: UDP + JSON parsing
# time: timestamps, bestandsnaam tijdstempel, UI loop timing
# threading: UDP listener in aparte thread + lock voor CSV buffer
# collections: deque voor rolling buffer
# csv/os: wegschrijven CSV + pad
import socket, json, time, threading, collections, csv, os

# NumPy: median/mean/percentielen, histogram, least squares fit
import numpy as np

# Matplotlib plotting + widgets (Button/RadioButtons/Slider) voor bediening
import matplotlib.pyplot as plt
from matplotlib.widgets import Button, RadioButtons, Slider

# ----------------------------- Instellingen -----------------------------
# UDP-poort waarop de calibrator luistert.
PORT        = 5006

# Aantal RSSI-samples in de buffer per Pi.
# "freeze bij 500": zodra buffer vol is, stopt het automatisch vullen zodat histogram stabiel blijft.
MED_WINDOW  = 500

# Verwachte/ondersteunde “anker”-volgorde (Pi's worden dynamisch aan A/B/C gekoppeld op basis van IP).
ANC_ORDER   = ["A", "B", "C"]

# ----------------------------- State ------------------------------------
# Mapping van IP-adres (zender) naar sleutel ("A"/"B"/"C").
ip_to_key, unused_keys = {}, ANC_ORDER.copy()

# Laatst ontvangen timestamp per key (uit het UDP JSON-veld "ts").
last_ts  = {k: 0.0 for k in ANC_ORDER}

# Optionele naam van de Pi (uit JSON-veld "pi") om later te tonen/loggen indien gewenst.
pi_name  = {k: ""  for k in ANC_ORDER}

# RSSI buffers per key: deque met maxlen = MED_WINDOW (rolling buffer).
buffers  = {k: collections.deque(maxlen=MED_WINDOW) for k in ANC_ORDER}

# Per key: boolean die bepaalt of we momenteel samples in de buffer aan het vullen zijn.
fill_on  = {k: False for k in ANC_ORDER}

# Lijst met vaste kalibratiepunten (elk punt bevat key, dist, rssi, timestamp, aantal samples).
points = []

# Globale GUI/state:
# - selected_key: welke Pi (A/B/C) momenteel geselecteerd is in de GUI
# - DIST: actuele afstand (m) gekozen met slider
state  = {"selected_key": "A", "DIST": 1.0}

# ----------------------------- CSV (RAW) --------------------------------
# rec_active:
# - True: elk binnenkomend RAW-signaal van de geselecteerde Pi wordt gelogd naar _rec_rows
# - False: niet loggen
rec_active = False

# _rec_rows bevat te exporteren CSV-rijen; _rec_lock beschermt toegang tussen UI thread en listener thread.
_rec_rows, _rec_lock = [], threading.Lock()

# CSV kolomnamen (en exacte sleutelvolgorde) voor export.
CSV_HEADER = ["host_ip", "rssi_dbm", "dist_m"]   # exact: host-ip, rssi_dbm, dist_m

def _rec_add(row):
    # Voeg één log-rij toe aan de in-memory CSV buffer, maar enkel als opname actief is.
    if not rec_active:
        return
    # Lock voorkomt race conditions wanneer UI thread en listener thread tegelijk lezen/schrijven.
    with _rec_lock:
        # Zorgt dat enkel keys uit CSV_HEADER aanwezig zijn (consistent CSV-formaat).
        _rec_rows.append({k: row.get(k, "") for k in CSV_HEADER})

def _rec_export():
    # Schrijf de opgenomen RAW-data weg naar een CSV-bestand.
    # Return: absolute filepath (str) of None bij fout/geen data.
    if not _rec_rows:
        return None

    # Afstand in bestandsnaam op moment van export (state["DIST"] kan later wijzigen).
    d = float(state["DIST"])
    fname = f"rssi_session_{time.strftime('%Y%m%d_%H%M%S')}_d{d:.2f}m.csv"

    try:
        # Kopieer eerst de data onder lock, zodat we consistent exporteren.
        with _rec_lock:
            rows = list(_rec_rows)

        # newline="" voor correcte CSV-regelafsluiting op Windows.
        with open(fname, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_HEADER)
            w.writeheader()
            w.writerows(rows)

        return os.path.abspath(fname)
    except OSError:
        # OSError: bv. geen schrijfrechten of padproblemen.
        return None

# ----------------------------- Helpers ----------------------------------
def current_median(key):
    # Berekent de mediaan van de huidige buffer voor 'key'.
    # Return: (median_value, count)
    buf = buffers[key]
    if not buf:
        return None, 0
    arr = np.asarray(buf, float)
    return float(np.median(arr)), len(arr)

def fit_log_model(distances, rssi_values):
    # Fit log-distance path loss model:
    # RSSI(d) = a + b * log10(d)
    #
    # In klassieke vorm: RSSI(d) = RSSI(d0) - 10*n*log10(d/d0)
    # Hier komt n overeen met (-b/10) wanneer d0 = 1m impliciet is.
    #
    # Input:
    # - distances: lijst/array met afstanden (m)
    # - rssi_values: lijst/array met RSSI (dBm)
    #
    # Output:
    # - a, b: fitcoëfficiënten
    # - n: path-loss exponent (= -b/10)
    # - r2: determinatiecoëfficiënt als fit-kwaliteit
    ds = np.asarray(distances, float)
    ys = np.asarray(rssi_values, float)

    # Alleen d > 0 is geldig voor log10(d).
    mask = ds > 0
    if np.sum(mask) < 2:
        raise ValueError("min. 2 punten met d>0 nodig")

    x = np.log10(ds[mask])
    y = ys[mask]

    # Lineaire regressie y = a + b*x via least squares:
    # X = [1, x] => coef[0]=a, coef[1]=b
    X = np.vstack([np.ones_like(x), x]).T
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)

    a, b = float(coef[0]), float(coef[1])

    # R^2 berekenen:
    yhat = X @ coef
    ss_res = float(np.sum((y - yhat)**2))
    ss_tot = float(np.sum((y - np.mean(y))**2))
    r2 = 1.0 - ss_res/ss_tot if ss_tot > 0 else 1.0

    # n = -b/10 (uit RSSI = a + b log10(d) ↔ RSSI = A - 10n log10(d))
    return a, b, (-b/10.0), r2

def clear_buffer(key):
    # Leegt de RSSI-buffer voor een bepaalde Pi-key.
    buffers[key].clear()

# ----------------------------- UDP listener ------------------------------
def listener():
    # UDP server-thread:
    # - bindt op PORT
    # - ontvangt JSON messages met minimaal: rssi_dbm, ts (en optioneel pi)
    # - koppelt IP's automatisch aan A/B/C (eerste 3 unieke IP’s)
    # - vult buffers wanneer fill_on[key] True is tot MED_WINDOW vol is
    # - logt RAW-data naar _rec_rows wanneer rec_active en selected_key overeenkomt
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", PORT))
    print(f"[CAL] listening UDP :{PORT}")

    while True:
        # Wacht op UDP-pakket (blocking)
        data, addr = sock.recvfrom(65535)
        ip, _ = addr

        # Parse JSON payload
        try:
            m = json.loads(data.decode("utf-8", errors="replace").strip())
        except json.JSONDecodeError:
            # Onleesbaar JSON: overslaan
            continue

        # Bepaal welke key ("A"/"B"/"C") bij dit IP hoort, of wijs er een toe als nog beschikbaar.
        key = ip_to_key.get(ip)
        if key is None and unused_keys:
            key = unused_keys.pop(0)
            ip_to_key[ip] = key
            print(f"[assign] {ip} → {key}")

        # Als we al 3 Pi’s toegewezen hebben, negeer extra IP’s.
        if key is None:
            continue

        # Extract rssi_dbm en ts (vereist) en valideer types.
        try:
            rssi = float(m["rssi_dbm"])
            ts = float(m["ts"])
        except (KeyError, TypeError, ValueError):
            continue

        # Optioneel: store pi-naam, indien aanwezig.
        if m.get("pi"):
            pi_name[key] = str(m["pi"])

        # Update "last seen" timestamp voor deze Pi.
        last_ts[key] = ts

        # Vullen tot vol; daarna automatisch pauzeren (freeze histogram).
        # fill_on[key] wordt door GUI bediend (Start buffer knop).
        if fill_on.get(key, False) and (len(buffers[key]) < MED_WINDOW):
            buffers[key].append(rssi)

            # Zodra buffer vol is, zet fill_on uit zodat histogram niet meer wijzigt.
            if len(buffers[key]) >= MED_WINDOW:
                fill_on[key] = False  # stop bij vol

        # CSV: log elk RAW-signaal van de geselecteerde Pi (state["selected_key"]).
        # De afstand die we loggen is de actuele slider-waarde (state["DIST"]).
        if rec_active and key == state["selected_key"]:
            _rec_add({
                "host_ip": ip,
                "rssi_dbm": f"{rssi:.2f}",
                "dist_m":  f"{float(state['DIST']):.3f}",
            })

# ----------------------------- GUI --------------------------------------
def main():
    # Start UDP listener in een daemon thread zodat het programma afsluit als de GUI sluit.
    threading.Thread(target=listener, daemon=True).start()

    # Algemene plot styling.
    plt.rcParams.update({"font.size": 10})

    # Hoofdfiguur aanmaken en layoutmarges instellen.
    fig = plt.figure(figsize=(12.0, 7.2))
    fig.subplots_adjust(left=0.06, right=0.98, bottom=0.08, top=0.94)

    # ----------------- Rechter hoofdplot: RSSI vs afstand -----------------
    # ax: hoofdas voor kalibratiepunten en fitcurve
    ax = fig.add_axes([0.40, 0.16, 0.58, 0.76])
    ax.set_title("Calibration: RSSI (dBm) vs distance (m)")
    ax.set_xlabel("distance d (m)")
    ax.set_ylabel("RSSI (dBm)")
    ax.grid(True, alpha=0.25)

    # Assenlimieten: afstand 0..10m, RSSI -100..-30 dBm
    ax.set_xlim(0.0, 10.0)
    ax.set_ylim(-100.0, -30.0)

    # Scatter voor punten (wordt later geüpdatet met set_offsets).
    scat = ax.scatter([], [], label="points")

    # Fit-lijn (Line2D object) die later set_data krijgt.
    fit_line, = ax.plot([], [], lw=1.8, label="fit")

    # Legende en tekstvak met fit/metrics.
    ax.legend(loc="lower right")
    metrics_txt = ax.text(
        0.02, 0.98,
        "Add \u2265 2 points with d>0 to compute a, b, n, R\u00b2",
        transform=ax.transAxes, va="top", ha="left",
        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="0.8", alpha=0.9)
    )

    # ----------------- Bedieningspanelen links -----------------
    # Radiobuttons: selecteer Pi-key (A/B/C)
    ax_radio = fig.add_axes([0.06, 0.82, 0.26, 0.12])
    ax_radio.set_title("Select Pi")
    radio = RadioButtons(ax_radio, ANC_ORDER, active=0)

    def on_radio(label):
        # Wanneer andere Pi gekozen wordt:
        # - update selected_key
        # - stop filling van alle buffers (veiligheid)
        # - clear buffer van de geselecteerde Pi zodat je “clean” start
        state["selected_key"] = label
        for k in ANC_ORDER:
            fill_on[k] = False
        clear_buffer(label)

    radio.on_clicked(on_radio)

    # Slider: afstand in meters (0..10 in stappen van 0.25m)
    ax_dist = fig.add_axes([0.06, 0.74, 0.26, 0.05])
    sl_dist = Slider(
        ax_dist,
        "Distance (m)",
        0.0,
        10.0,
        valinit=state["DIST"],
        valstep=0.25
    )
    # Layout-tweak: label iets naar links uitlijnen.
    sl_dist.label.set_horizontalalignment("left")
    sl_dist.label.set_x(0.02)

    # Bij slider wijziging: update state["DIST"].
    sl_dist.on_changed(lambda v: state.update(DIST=float(v)))

    # Buttons: buffer vullen, punt vastzetten, undo, clear, CSV record start/stop+export
    ax_start = fig.add_axes([0.06, 0.66, 0.12, 0.07])
    btn_start = Button(ax_start, "Start buffer")

    ax_fix   = fig.add_axes([0.20, 0.66, 0.12, 0.07])
    btn_fix   = Button(ax_fix,   "Fix point")

    ax_undo  = fig.add_axes([0.06, 0.58, 0.12, 0.07])
    btn_undo  = Button(ax_undo,  "Undo")

    ax_clear = fig.add_axes([0.20, 0.58, 0.12, 0.07])
    btn_clear = Button(ax_clear, "Clear")

    ax_rec_start = fig.add_axes([0.06, 0.46, 0.12, 0.07])
    btn_rec_start = Button(ax_rec_start, "Start rec")

    ax_rec_stop  = fig.add_axes([0.20, 0.46, 0.12, 0.07])
    btn_rec_stop  = Button(ax_rec_stop,  "Stop+Export")

    # Statusregel (monospace): toont opname/rijen en bufferstatus voor selected_key.
    ax_status = fig.add_axes([0.06, 0.38, 0.32, 0.06])
    ax_status.axis("off")
    status_txt = ax_status.text(0.0, 0.5, "Rec: OFF | rows=0", va="center", family="monospace")

    # ----------------- Histogram links-onder -----------------
    # Histogram toont verdeling RSSI-samples in buffer van de geselecteerde Pi.
    ax_hist = fig.add_axes([0.06, 0.10, 0.33, 0.26])
    ax_hist.set_title("Buffer histogram (selected Pi)")
    ax_hist.set_xlabel("RSSI (dBm)")
    ax_hist.set_ylabel("count")

    # Histogram-aslimieten: RSSI van -80 tot -10 dBm (focus op typische bereik)
    ax_hist.set_xlim(-80, -10)
    ax_hist.set_ylim(0, 1)

    # Bin edges per 1 dB stap.
    bin_edges = np.arange(-80, -10 + 1, 1)

    # Initialiseer bars met nul hoogtes.
    bars = ax_hist.bar(
        bin_edges[:-1],
        np.zeros(len(bin_edges)-1),
        width=1.0,
        align="edge",
        edgecolor="none"
    )

    # Verticale lijnen voor mean/median en percentielen.
    mean_line,   = ax_hist.plot([], [], linewidth=2, label="mean")
    median_line, = ax_hist.plot([], [], linestyle="--", linewidth=2, label="median")
    p05_line,    = ax_hist.plot([], [], linestyle=":", linewidth=2, label="p5")
    p95_line,    = ax_hist.plot([], [], linestyle=":", linewidth=2, label="p95")
    ax_hist.legend(loc="upper right", fontsize=8)

    # Tekst onder histogram met numerieke statistiek.
    ax_hist_info = fig.add_axes([0.06, 0.06, 0.33, 0.03])
    ax_hist_info.axis("off")
    hist_info_txt = ax_hist_info.text(0.0, 0.5, "", va="center", family="monospace", fontsize=9)

    # ----------------- Handlers (GUI callbacks) -----------------
    def _status(extra=""):
        # Update de statusregel:
        # - Rec ON/OFF
        # - aantal gelogde CSV rijen
        # - bufferstatus van selected_key (FILL/PAUSE + aantal samples)
        with _rec_lock:
            n = len(_rec_rows)

        k = state["selected_key"]
        _, cnt = current_median(k)

        s = f"Rec: {'ON' if rec_active else 'OFF'} | rows={n} | Buffer[{k}]: {'FILL' if fill_on[k] else 'PAUSE'} {cnt}/{MED_WINDOW}"
        if extra:
            s += f" | {extra}"
        status_txt.set_text(s)

    def on_start(_):
        # Start buffer vullen voor de geselecteerde Pi:
        # - clear buffer zodat er geen oude samples inzitten
        # - zet fill_on voor alle Pi’s uit en enkel voor selected_key aan
        k = state["selected_key"]
        clear_buffer(k)
        for kk in ANC_ORDER:
            fill_on[kk] = False
        fill_on[k] = True
        _status("buffer started")

    def on_fix(_):
        # Fixeer (kalibratie)punt:
        # - neem median van buffer (stabiele RSSI schatting)
        # - sla punt op met (key, dist, rssi, ts, samples)
        # - clear buffer en stop filling
        k = state["selected_key"]
        med, cnt = current_median(k)
        if med is None:
            _status("no samples")
            return

        d = float(state["DIST"])
        points.append({"key": k, "dist": d, "rssi": med, "ts": time.time(), "samples": cnt})

        clear_buffer(k)
        fill_on[k] = False
        _status("point fixed")

    def on_undo(_):
        # Verwijder laatst toegevoegde kalibratiepunt (indien bestaat).
        if points:
            points.pop()
            _status("undo")

    def on_clear(_):
        # Verwijder alle kalibratiepunten.
        points.clear()
        _status("cleared")

    def on_rec_start(_):
        # Start RAW opname:
        # - reset _rec_rows
        # - zet rec_active True zodat listener thread gaat loggen
        global rec_active, _rec_rows
        with _rec_lock:
            _rec_rows = []
        rec_active = True
        _status("rec started")

    def on_rec_stop(_):
        # Stop RAW opname en exporteer naar CSV:
        # - zet rec_active False
        # - exporteer _rec_rows naar bestand
        global rec_active
        rec_active = False
        path = _rec_export()
        _status("CSV saved" if path else "no data")

    # Koppel callbacks aan buttons.
    btn_start.on_clicked(on_start)
    btn_fix.on_clicked(on_fix)
    btn_undo.on_clicked(on_undo)
    btn_clear.on_clicked(on_clear)
    btn_rec_start.on_clicked(on_rec_start)
    btn_rec_stop.on_clicked(on_rec_stop)

    # ----------------------------- Render-loop -----------------------------
    # Continue update loop:
    # - update scatter + fitcurve op basis van 'points'
    # - update histogram op basis van buffers[selected_key]
    # - update status text
    # - refresh figuur met kleine pauze (0.05s)
    while True:
        # ---- Kalibratiepunten + fit ----
        xs = [p["dist"] for p in points]
        ys = [p["rssi"] for p in points]

        # Update scatter offsets (of leeg indien geen punten).
        scat.set_offsets(np.c_[xs, ys] if xs else np.empty((0, 2)))

        # Fit enkel als er minstens 2 punten met d>0 zijn (log10 vereist d>0).
        if len(xs) >= 2 and np.sum(np.asarray(xs) > 0) >= 2:
            try:
                # Fit parameters + fitcurve op 0.1..10m
                a, b, n, r2 = fit_log_model(xs, ys)
                xfit = np.linspace(0.1, 10.0, 200)
                fit_line.set_data(xfit, a + b * np.log10(xfit))
                metrics_txt.set_text(f"a={a:.2f} dBm   b={b:.3f}   n={n:.3f}   R\u00b2={r2:.3f}")
            except Exception as e:
                # Bij fitfout: toon error in metrics, en verberg fitlijn.
                fit_line.set_data([], [])
                metrics_txt.set_text(f"Fit error: {e}")
        else:
            # Niet genoeg punten: verberg fitlijn en toon instructie.
            fit_line.set_data([], [])
            metrics_txt.set_text("Add \u2265 2 points with d>0 to compute a, b, n, R\u00b2")

        # ---- Histogram ----
        # Histogram updaten op basis van de geselecteerde Pi-buffer.
        k = state["selected_key"]
        if buffers[k]:
            arr = np.asarray(buffers[k], float)

            # Histogram counts per bin.
            counts, _ = np.histogram(arr, bins=bin_edges)

            # Update bar hoogtes.
            for bar, h in zip(bars, counts):
                bar.set_height(h)

            # Dynamische y-limiet zodat histogram schaalt met data.
            ymax = max(1, int(counts.max() * 1.2))
            ax_hist.set_ylim(0, ymax)

            # Statistiek: mean/median/p5/p95.
            mu  = float(np.mean(arr))
            med = float(np.median(arr))
            p05 = float(np.percentile(arr, 5))
            p95 = float(np.percentile(arr, 95))

            # Update verticale lijnen.
            for line, x in ((mean_line, mu), (median_line, med), (p05_line, p05), (p95_line, p95)):
                line.set_data([x, x], [0, ymax])

            # Tekst met statistiekwaarden.
            hist_info_txt.set_text(f"mean={mu:.2f}  median={med:.2f}  p5={p05:.2f}  p95={p95:.2f}")
        else:
            # Geen samples: bars en lijnen leegmaken.
            for bar in bars:
                bar.set_height(0)
            for line in (mean_line, median_line, p05_line, p95_line):
                line.set_data([], [])
            hist_info_txt.set_text("")

        # Statusregel updaten.
        _status()

        # Render updates (non-blocking) + korte pauze om GUI responsive te houden.
        fig.canvas.draw_idle()
        plt.pause(0.05)

# Script-entrypoint: alleen uitvoeren wanneer dit bestand direct wordt gestart (niet bij import).
if __name__ == "__main__":
    main()
