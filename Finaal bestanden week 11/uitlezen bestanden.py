import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

# ============================
# CONFIG – AANPASSEN
# ============================

# Zet hier je drie mappen met CSV-bestanden
INPUT_DIRS = [
    Path(r"C:\Users\audri\Desktop\Python programma's\pi4_v2"),
    Path(r"C:\Users\audri\Desktop\Python programma's\pi5rood_v2"),
    Path(r"C:\Users\audri\Desktop\Python programma's\pi5zwart_v2"),
]

# Outputmap voor figuren + txt
OUTPUT_DIR = Path("calibration_output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SUMMARY_TXT = OUTPUT_DIR / "calibration_summary.txt"

# CSV-kolommen worden verondersteld: host_ip, rssi_dbm, dist_m


# ============================
# HULPFUNCTIES
# ============================

def load_all_csv(input_dirs):
    """Lees alle CSV's uit de opgegeven mappen in één DataFrame."""
    files = []
    for d in input_dirs:
        if d.is_dir():
            files.extend(d.glob("*.csv"))
    if not files:
        raise FileNotFoundError("Geen CSV-bestanden gevonden in opgegeven mappen.")

    dfs = []
    for f in files:
        df = pd.read_csv(f)
        df["source_file"] = str(f)
        dfs.append(df)

    data = pd.concat(dfs, ignore_index=True)

    # Zorg dat types kloppen
    data["rssi_dbm"] = pd.to_numeric(data["rssi_dbm"], errors="coerce")
    data["dist_m"]   = pd.to_numeric(data["dist_m"], errors="coerce")

    return data


def make_hist_and_stats(data):
    """
    Maakt per host_ip en dist_m een histogram en berekent
    median/p5/p95. Geeft een lijst dictionaries terug voor de summary.
    """
    stats_list = []

    # Groepeer per Pi (host_ip) en per afstand
    grouped = data.groupby(["host_ip", "dist_m"])

    for (host_ip, dist), grp in grouped:
        # Neem alleen geldige RSSI’s
        vals = grp["rssi_dbm"].dropna().values
        if len(vals) == 0:
            continue

        median = float(np.median(vals))
        p5     = float(np.percentile(vals, 5))
        p95    = float(np.percentile(vals, 95))
        count  = int(len(vals))

        # Histogram + lijnen tekenen
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.hist(vals, bins="auto", alpha=0.7)
        ax.axvline(median, color="black", linestyle="--", linewidth=2, label=f"median={median:.2f}")
        ax.axvline(p5,     color="red",   linestyle=":",  linewidth=2, label=f"p5={p5:.2f}")
        ax.axvline(p95,    color="green", linestyle=":",  linewidth=2, label=f"p95={p95:.2f}")
        ax.set_title(f"host_ip={host_ip}  dist={dist:.2f} m (n={count})")
        ax.set_xlabel("RSSI (dBm)")
        ax.set_ylabel("Count")
        ax.legend()

        # Bestandsnaam voor figuur
        safe_ip = str(host_ip).replace(":", "_").replace(".", "_")
        fig_name = OUTPUT_DIR / f"hist_host_{safe_ip}_d{dist:.2f}m.png"
        fig.tight_layout()
        fig.savefig(fig_name, dpi=150)
        plt.close(fig)

        # Stats opslaan voor txt
        stats_list.append({
            "host_ip": host_ip,
            "dist_m": dist,
            "count": count,
            "median": median,
            "p5": p5,
            "p95": p95,
            "figure": str(fig_name),
        })

    # Sorteer mooi op host_ip en afstand
    stats_list.sort(key=lambda d: (d["host_ip"], d["dist_m"]))
    return stats_list


def write_summary_txt(stats_list, path):
    """
    Schrijft een tekstbestand met alle kalibratiestatistieken
    in een vorm die je zo in ChatGPT kunt plakken.
    """
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Calibration summary per host_ip en afstand\n")
        f.write("# Elke regel: host_ip, dist_m, aantal samples, median, p5, p95\n")
        f.write("# Dit kun je hierna in een ChatGPT-chat plakken om de lokalisatie-code\n")
        f.write("# aan te passen (bijv. cirkels tekenen op basis van p5/p95).\n\n")

        # eventueel ook een Python-achtige structuur erbij
        f.write("CALIBRATION_STATS = {\n")
        current_ip = None

        for s in stats_list:
            host = s["host_ip"]
            dist = s["dist_m"]
            cnt  = s["count"]
            med  = s["median"]
            p5   = s["p5"]
            p95  = s["p95"]

            # Comment-lijn voor menselijk lezen
            f.write(f"# host_ip={host}  dist={dist:.2f} m  n={cnt}  "
                    f"median={med:.2f} dBm  p5={p5:.2f} dBm  p95={p95:.2f} dBm\n")

            # Gestructureerde dict
            # Nieuwe host_ip-block openen
            if host != current_ip:
                if current_ip is not None:
                    f.write("    },\n")
                f.write(f"    '{host}': {{\n")
                current_ip = host

            f.write(
                f"        {dist:.3f}: {{'count': {cnt}, 'median': {med:.3f}, "
                f"'p5': {p5:.3f}, 'p95': {p95:.3f}}},\n"
            )

        if current_ip is not None:
            f.write("    },\n")
        f.write("}\n")

    print(f"Summary geschreven naar: {path}")


# ============================
# MAIN
# ============================

def main():
    # 1) Lees alle CSV’s
    data = load_all_csv(INPUT_DIRS)

    # 2) Maak histograms + stats
    stats_list = make_hist_and_stats(data)

    # 3) Schrijf txt-bestand
    write_summary_txt(stats_list, SUMMARY_TXT)


if __name__ == "__main__":
    main()
