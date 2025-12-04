import matplotlib
matplotlib.use("TkAgg")  # Forceer TkAgg-backend voor interactieve GUI

import socket, json, time, threading, collections
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from matplotlib.widgets import Slider, TextBox

# =============================
# Kalibratie: 5e/95e percentielen per host_ip en afstand
# =============================

CALIBRATION_STATS = {
    '172.20.10.2': {
        0.000: {'count': 592, 'median': -33.000, 'p5': -34.000, 'p95': -32.000},
        0.250: {'count': 1017, 'median': -38.000, 'p5': -39.000, 'p95': -37.000},
        0.500: {'count': 942, 'median': -50.000, 'p5': -52.000, 'p95': -49.000},
        0.750: {'count': 675, 'median': -61.000, 'p5': -63.000, 'p95': -60.000},
        1.000: {'count': 634, 'median': -58.000, 'p5': -59.000, 'p95': -56.000},
        1.500: {'count': 560, 'median': -58.000, 'p5': -60.000, 'p95': -57.000},
        2.000: {'count': 546, 'median': -63.000, 'p5': -65.000, 'p95': -60.000},
        2.500: {'count': 557, 'median': -63.000, 'p5': -65.000, 'p95': -61.000},
        3.000: {'count': 593, 'median': -75.000, 'p5': -77.000, 'p95': -72.000},
        3.500: {'count': 557, 'median': -69.000, 'p5': -72.000, 'p95': -68.000},
        4.000: {'count': 576, 'median': -67.000, 'p5': -69.000, 'p95': -64.000},
        4.500: {'count': 562, 'median': -66.000, 'p5': -67.000, 'p95': -65.000},
        5.000: {'count': 559, 'median': -64.000, 'p5': -65.000, 'p95': -63.000},
        6.000: {'count': 547, 'median': -65.000, 'p5': -67.000, 'p95': -64.000},
        7.000: {'count': 551, 'median': -76.000, 'p5': -79.000, 'p95': -70.000},
        8.000: {'count': 548, 'median': -68.000, 'p5': -69.000, 'p95': -67.000},
        9.000: {'count': 565, 'median': -73.000, 'p5': -75.000, 'p95': -70.000},
        10.000: {'count': 551, 'median': -73.000, 'p5': -75.000, 'p95': -71.000},
    },
    '172.20.10.3': {
        0.000: {'count': 502, 'median': -30.000, 'p5': -30.000, 'p95': -29.000},
        0.250: {'count': 512, 'median': -43.000, 'p5': -44.000, 'p95': -42.000},
        0.500: {'count': 513, 'median': -51.000, 'p5': -54.000, 'p95': -49.000},
        0.750: {'count': 531, 'median': -55.000, 'p5': -58.000, 'p95': -53.000},
        1.000: {'count': 533, 'median': -58.000, 'p5': -60.400, 'p95': -55.000},
        1.500: {'count': 530, 'median': -61.000, 'p5': -62.000, 'p95': -59.000},
        2.000: {'count': 509, 'median': -66.000, 'p5': -68.000, 'p95': -63.000},
        2.500: {'count': 527, 'median': -66.000, 'p5': -69.000, 'p95': -65.000},
        3.000: {'count': 540, 'median': -65.000, 'p5': -67.000, 'p95': -63.000},
        3.500: {'count': 523, 'median': -70.000, 'p5': -72.000, 'p95': -69.000},
        4.000: {'count': 527, 'median': -70.000, 'p5': -73.000, 'p95': -68.000},
        4.500: {'count': 525, 'median': -69.000, 'p5': -70.000, 'p95': -66.000},
        5.000: {'count': 527, 'median': -71.000, 'p5': -74.000, 'p95': -69.000},
        6.000: {'count': 534, 'median': -67.000, 'p5': -68.000, 'p95': -66.000},
        7.000: {'count': 528, 'median': -76.000, 'p5': -77.000, 'p95': -74.000},
        8.000: {'count': 528, 'median': -70.000, 'p5': -72.000, 'p95': -69.000},
        9.000: {'count': 613, 'median': -72.000, 'p5': -74.000, 'p95': -71.000},
        10.000: {'count': 544, 'median': -74.000, 'p5': -77.000, 'p95': -73.000},
    },
    '172.20.10.4': {
        0.000: {'count': 511, 'median': -28.000, 'p5': -29.000, 'p95': -27.000},
        0.250: {'count': 528, 'median': -36.000, 'p5': -37.000, 'p95': -34.000},
        0.500: {'count': 515, 'median': -45.000, 'p5': -47.000, 'p95': -44.000},
        0.750: {'count': 529, 'median': -49.000, 'p5': -50.000, 'p95': -49.000},
        1.000: {'count': 532, 'median': -53.000, 'p5': -54.000, 'p95': -52.000},
        1.500: {'count': 525, 'median': -57.000, 'p5': -59.000, 'p95': -56.000},
        2.000: {'count': 528, 'median': -60.000, 'p5': -62.000, 'p95': -59.000},
        2.500: {'count': 529, 'median': -62.000, 'p5': -63.000, 'p95': -60.000},
        3.000: {'count': 531, 'median': -59.000, 'p5': -60.000, 'p95': -57.000},
        3.500: {'count': 526, 'median': -65.000, 'p5': -67.000, 'p95': -61.000},
        4.000: {'count': 530, 'median': -67.000, 'p5': -69.000, 'p95': -63.000},
        4.500: {'count': 528, 'median': -69.000, 'p5': -71.000, 'p95': -66.000},
        5.000: {'count': 527, 'median': -68.000, 'p5': -69.000, 'p95': -63.000},
        6.000: {'count': 526, 'median': -67.000, 'p5': -68.000, 'p95': -64.000},
        7.000: {'count': 533, 'median': -68.000, 'p5': -70.000, 'p95': -67.000},
        8.000: {'count': 532, 'median': -72.000, 'p5': -73.000, 'p95': -69.000},
        9.000: {'count': 526, 'median': -73.000, 'p5': -75.000, 'p95': -72.000},
        10.000: {'count': 532, 'median': -73.000, 'p5': -75.000, 'p95': -71.000},
    },
}

# =============================
# Instellingen (poorten/vensters)
# =============================
PORT          = 5006
WINDOW_S      = 6.0
CHUNK_N       = 100
RAW_KEEP      = 40

ANC_ORDER   = ["A", "B", "C"]
ANCHOR_INIT = {"A": (0.0, 0.0), "B": (2.0, 0.0), "C": (1.0, 2.0)}
CAL_INIT    = {k: {"rssi1m": -55.0, "n": 2.2} for k in ANC_ORDER}

# =============================
# State
# =============================
ip_to_key   = {}
seen_ips    = set()
rssi_buf    = {k: collections.deque(maxlen=CHUNK_N) for k in ANC_ORDER}
chunk_med   = {k: None for k in ANC_ORDER}
last_ts     = {k: 0.0 for k in ANC_ORDER}
anchors     = {k: [*ANCHOR_INIT[k]] for k in ANC_ORDER}
cal         = {k: dict(CAL_INIT[k]) for k in ANC_ORDER}
circles     = {k: [] for k in ANC_ORDER}
raw_log     = collections.deque(maxlen=RAW_KEEP)

# =============================
# Helpers
# =============================
def fmt_raw(ip, port, key, m):
    try:
        r = float(m.get("rssi_dbm", 0.0)); ts = float(m.get("ts", time.time()))
    except Exception:
        r, ts = 0.0, time.time()
    t = time.strftime("%H:%M:%S", time.localtime(ts))
    k = key if key else "?"
    return f"{t} {ip}:{port} [{k}] rssi={r:.1f}"[:70]

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

def ip_for_key(key):
    for ip, k in ip_to_key.items():
        if k == key:
            return ip
    return None

def estimate_dist_band(host_ip, rssi_med, rssi1m, n):
    stats_ip = CALIBRATION_STATS.get(host_ip)
    if stats_ip is None:
        return None, None, None

    d_est = rssi_to_dist(rssi_med, rssi1m, n)

    cal_dists = [d for d in stats_ip.keys() if d > 0.0]
    if not cal_dists:
        cal_dists = list(stats_ip.keys())
    nearest = min(cal_dists, key=lambda d: abs(d - d_est))

    row = stats_ip[nearest]
    med_cal = row['median']
    p5_cal  = row['p5']
    p95_cal = row['p95']

    drssi_low  = abs(med_cal - p5_cal)
    drssi_high = abs(p95_cal - med_cal)

    d_inner = rssi_to_dist(rssi_med + drssi_high, rssi1m, n)
    d_outer = rssi_to_dist(rssi_med - drssi_low,  rssi1m, n)

    d_min = min(d_inner, d_outer)
    d_max = max(d_inner, d_outer)

    return d_est, d_min, d_max

# =============================
# UDP-listener
# =============================
def listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", PORT))
    print(f"[GUI] UDP listening on :{PORT}")
    while True:
        data, addr = sock.recvfrom(65535)
        ip, sport = addr
        seen_ips.add(ip)

        try:
            m = json.loads(data.decode("utf-8", errors="replace").strip())
        except Exception as e:
            raw_log.appendleft(f"{ip}:{sport} <bad JSON> {e}")
            continue

        key = ip_to_key.get(ip)

        raw_log.appendleft(fmt_raw(ip, sport, key, m))

        if key is None:
            continue

        try:
            rssi = float(m["rssi_dbm"]); ts = float(m["ts"])
        except Exception:
            continue

        rssi_buf[key].append(rssi)
        last_ts[key] = ts

        if len(rssi_buf[key]) >= CHUNK_N:
            arr = np.asarray(rssi_buf[key], float)
            chunk_med[key] = float(np.median(arr))
            rssi_buf[key].clear()

# =============================
# GUI
# =============================
def main():
    threading.Thread(target=listener, daemon=True).start()

    plt.rcParams.update({"font.size": 10})
    fig = plt.figure(figsize=(12.6, 7.0))
    fig.subplots_adjust(left=0.02, right=0.98, bottom=0.06, top=0.95)

    # Linkerkolom: IP→Key-overzicht
    ax_left = fig.add_axes([0.02, 0.50, 0.14, 0.46]); ax_left.axis("off")
    map_text = ax_left.text(0.0, 1.0, "IP→Key (wachten…)", va="top",
                            family="monospace", fontsize=9,
                            bbox=dict(boxstyle="round", fc="white", alpha=0.9))

    # Midden: kaart
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

    # RAW-log
    ax_raw = fig.add_axes([0.70, 0.64, 0.27, 0.30]); ax_raw.axis("off")
    raw_text = ax_raw.text(0.0, 1.0, "(no data)", va="top", family="monospace")

    # Sliders rssi@1m en n
    sliders = []
    x_sl, w_sl = 0.02, 0.14
    y0, dy, h = 0.47, 0.035, 0.028
    i = 0
    for k in ANC_ORDER:
        for (label, vmin, vmax, v0, fld) in (
            (f"{k} rssi@1m", -80.0, -30.0, cal[k]["rssi1m"], "rssi1m"),
            (f"{k} n",        1.6,    6,  cal[k]["n"],       "n"),
        ):
            a = fig.add_axes([x_sl, y0 - dy*i, w_sl, h])
            sl = Slider(a, label, vmin, vmax, valinit=v0, valfmt="%.2f")
            sl.on_changed(lambda _v, kk=k, f=fld, s=sl: cal[kk].__setitem__(f, float(s.val)))
            sliders.append(sl); i += 1

    # TextBoxen voor ankerposities
    def make_pos_boxes(k, x0):
        def _box(label, init, onsubmit):
            a = fig.add_axes([x0, 0.13 if "x" in label else 0.06, 0.08, 0.06])
            tb = TextBox(a, label, initial=str(init)); tb.on_submit(onsubmit); return tb
        def sx(txt):
            try:
                anchors[k][0] = float(txt)
                scatter[k].set_offsets([anchors[k][0], anchors[k][1]])
                labels[k].set_position((anchors[k][0]+0.12, anchors[k][1]+0.12))
                set_limits()
            except Exception:
                pass
        def sy(txt):
            try:
                anchors[k][1] = float(txt)
                scatter[k].set_offsets([anchors[k][0], anchors[k][1]])
                labels[k].set_position((anchors[k][0]+0.12, anchors[k][1]+0.12))
                set_limits()
            except Exception:
                pass
        _box(f"{k} x", anchors[k][0], sx)
        _box(f"{k} y", anchors[k][1], sy)

    fig.text(0.20, 0.22, "Ankerposities (m):", weight="bold")
    for k, x0 in zip(ANC_ORDER, [0.20, 0.36, 0.52]):
        make_pos_boxes(k, x0)

    # IP-toewijzing (onder de sliders, zodat niets overlapt)
    def make_ip_assign_box(label_key, x0, y0_box):
        def on_submit_ip(txt):
            ip = txt.strip()
            if not ip:
                to_del = [ip_ for ip_, k_ in ip_to_key.items() if k_ == label_key]
                for ip_ in to_del:
                    del ip_to_key[ip_]
                return
            to_del = [ip_ for ip_, k_ in ip_to_key.items() if k_ == label_key or ip_ == ip]
            for ip_ in to_del:
                del ip_to_key[ip_]
            ip_to_key[ip] = label_key

        a = fig.add_axes([x0, y0_box, 0.14, 0.05])
        tb = TextBox(a, f"IP {label_key}", initial="")
        tb.on_submit(on_submit_ip)
        return tb

    fig.text(0.02, 0.30, "IP-toewijzing:", weight="bold")
    ip_box_A = make_ip_assign_box("A", 0.02, 0.23)
    ip_box_B = make_ip_assign_box("B", 0.02, 0.16)
    ip_box_C = make_ip_assign_box("C", 0.02, 0.09)

    # Render-loop
    while True:
        now = time.time()
        for k in ANC_ORDER:
            if (now - last_ts[k]) > WINDOW_S:
                rssi_buf[k].clear()
                chunk_med[k] = None

        pts, dists, lines = [], [], []
        for k in ANC_ORDER:
            if chunk_med[k] is not None:
                med = chunk_med[k]

                host_ip = ip_for_key(k)
                if host_ip is not None:
                    d_med, d_min, d_max = estimate_dist_band(
                        host_ip,
                        med,
                        cal[k]["rssi1m"],
                        cal[k]["n"],
                    )
                else:
                    d_med = rssi_to_dist(med, cal[k]["rssi1m"], cal[k]["n"])
                    d_min = d_max = None

                if d_med is None:
                    d_med = rssi_to_dist(med, cal[k]["rssi1m"], cal[k]["n"])
                    d_min = d_max = None

                x, y = anchors[k]

                if circles[k]:
                    for c in circles[k]:
                        c.remove()
                    circles[k] = []

                if d_min is not None and d_max is not None:
                    c_outer = Circle((x, y), max(0.05, d_max),
                                     fill=False, alpha=0.25, linestyle="--")
                    c_inner = Circle((x, y), max(0.05, d_min),
                                     fill=False, alpha=0.25, linestyle="--")
                    ax.add_patch(c_outer)
                    ax.add_patch(c_inner)
                    circles[k] = [c_outer, c_inner]
                else:
                    c_med = Circle((x, y), max(0.05, d_med),
                                   fill=False, alpha=0.35)
                    ax.add_patch(c_med)
                    circles[k] = [c_med]

                pts.append((x, y))
                dists.append(d_med)

                if d_min is not None and d_max is not None:
                    lines.append(
                        f"{k}: d≈{d_med:.2f}m [{d_min:.2f}–{d_max:.2f}] • "
                        f"RSSI~{med:.1f} (1m={cal[k]['rssi1m']:.1f}, n={cal[k]['n']:.2f})"
                    )
                else:
                    lines.append(
                        f"{k}: d≈{d_med:.2f}m • "
                        f"RSSI~{med:.1f} (1m={cal[k]['rssi1m']:.1f}, n={cal[k]['n']:.2f})"
                    )
            elif circles[k]:
                for c in circles[k]:
                    c.remove()
                circles[k] = []

        if len(pts) >= 3:
            try:
                px, py = trilaterate(pts, dists)
                est_dot.set_data([px], [py])
                info_txt.set_text(" | ".join(lines) + f"\nEST ≈ ({px:.2f}, {py:.2f}) m")
            except Exception as e:
                est_dot.set_data([], [])
                info_txt.set_text(f"Trilateratie fout: {e}")
        else:
            est_dot.set_data([], [])
            info_txt.set_text((" | ".join(lines) if lines else "Wachten…") + "\n(≥3 ankers nodig)")

        if seen_ips:
            lines_map = ["IP → Key:"]
            for ip in sorted(seen_ips):
                k = ip_to_key.get(ip, "?")
                lines_map.append(f"  {ip:<15} → {k}")
            map_text.set_text("\n".join(lines_map))
        else:
            map_text.set_text("IP→Key (wachten…)")

        raw_text.set_text("\n".join(raw_log) if raw_log else "(no data)")

        fig.canvas.draw_idle()
        plt.pause(0.05)

if __name__ == "__main__":
    main()
