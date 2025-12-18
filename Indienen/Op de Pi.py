# pi_rssi_sender_raw.py
# Doel:
# - Meet periodiek de Wi-Fi RSSI (signaalsterkte) op een Raspberry Pi.
# - Verstuurt elke meting als JSON via UDP naar een “collector” (bv. de laptop met kalibratie-/lokalisatietool).
# - De collector kan deze RSSI-data gebruiken voor kalibratie (model fit) of lokalisatie (trilateratie).

import subprocess, time, socket, json, shutil, re, sys, os  # standaardmodules die we in dit script nodig hebben

# --- Instellingen (env-override mogelijk) ------------------------------------
# COLLECTOR_IP:
# - IP-adres van de ontvangende machine (bv. laptop) die de UDP-pakketten binnenhaalt.
# - Kan overschreven worden via environment variable COLLECTOR_IP.
COLLECTOR_IP   = os.environ.get("COLLECTOR_IP", "10.0.0.1")

# COLLECTOR_PORT:
# - UDP-poort waarop de collector luistert.
# - Kan overschreven worden via environment variable COLLECTOR_PORT.
COLLECTOR_PORT = int(os.environ.get("COLLECTOR_PORT", "5006"))

# POLL_HZ:
# - Hoe vaak per seconde we RSSI willen meten.
# - Standaard 20 Hz (ongeveer elke 0.05 s).
# - Kan overschreven worden via environment variable POLL_HZ.
POLL_HZ        = float(os.environ.get("POLL_HZ", "20"))   # 20 Hz → elke 0.05 s

# POLL_DT:
# - De gewenste periode tussen twee metingen (in seconden).
# - POLL_DT = 1 / POLL_HZ.
POLL_DT        = 1.0 / POLL_HZ

# Tools & interface
# DEFAULT_IFACE:
# - Fallback netwerkinterface als we geen “connected” interface kunnen detecteren.
DEFAULT_IFACE  = "wlan0"

# IW:
# - Pad naar de tool 'iw' (Linux wifi tool).
# - shutil.which zoekt het commando in PATH; anders fallback naar /sbin/iw.
IW             = shutil.which("iw") or "/sbin/iw"

# WPA_CLI:
# - Pad naar 'wpa_cli' (tool om info op te vragen uit wpa_supplicant).
WPA_CLI        = shutil.which("wpa_cli") or "wpa_cli"

# --- Interface zoeken --------------------------------------------------------
def get_connected_iface():
    # Doel:
    # - Zoek automatisch welke wifi-interface effectief verbonden is.
    # Werking:
    # - Roept 'iw dev' op om interfaces te vinden.
    # - Voor elke gevonden interface: check 'iw dev <if> link' en kijk of “Connected” voorkomt.
    # - Als niets gevonden: fallback naar DEFAULT_IFACE.
    try:
        # 'iw dev' geeft o.a. een lijst interfaces (wlan0, wlan1, ...)
        out = subprocess.check_output([IW, "dev"], text=True, stderr=subprocess.DEVNULL)

        # Regex zoekt alle regels van de vorm "Interface <naam>"
        for ifn in re.findall(r"Interface\s+(\S+)", out):
            try:
                # 'iw dev <ifn> link' geeft link-status (Connected / Not connected)
                link = subprocess.check_output([IW, "dev", ifn, "link"], text=True)
                if "Connected" in link:
                    return ifn
            except subprocess.CalledProcessError:
                # Als 'iw ... link' faalt voor een interface, negeren we die en proberen we de volgende
                pass
    except Exception:
        # Alle onverwachte errors negeren en later fallback gebruiken
        pass

    # Geen connected interface gevonden → gebruik default
    return DEFAULT_IFACE

# --- RSSI polling ------------------------------------------------------------
def poll_rssi_wpacli(iface):
    # Doel:
    # - Probeer RSSI te lezen via 'wpa_cli signal_poll' (meestal beschikbaar wanneer wpa_supplicant draait).
    # Werking:
    # - output bevat lijnen zoals: "RSSI=-55"
    # - We zoeken de lijn die start met "RSSI=" en parsen het getal.
    try:
        out = subprocess.check_output([WPA_CLI, "-i", iface, "signal_poll"], text=True)
        for ln in out.splitlines():
            if ln.startswith("RSSI="):
                return float(ln.split("=", 1)[1].strip())
    except Exception:
        # Als wpa_cli niet werkt of geen RSSI teruggeeft: None → later fallback naar iw
        pass
    return None

def poll_rssi_iw(iface):
    # Doel:
    # - Probeer RSSI te lezen via 'iw dev <iface> link' als fallback.
    # Werking:
    # - output bevat vaak een lijn zoals: "signal: -55 dBm"
    # - We zoeken "signal:" en parsen het getal vóór "dBm".
    try:
        out = subprocess.check_output([IW, "dev", iface, "link"], text=True)
        for ln in out.splitlines():
            if "signal:" in ln:
                val = ln.split("signal:")[1].split("dBm")[0].strip()
                return float(val)
    except Exception:
        # Als iw niet werkt of format anders is: None
        pass
    return None

def poll_rssi(iface):
    # Doel:
    # - Centrale RSSI-leesfunctie met fallback:
    #   1) probeer wpa_cli (meestal direct RSSI-waarde)
    #   2) als dat None oplevert, probeer iw
    r = poll_rssi_wpacli(iface)
    return r if r is not None else poll_rssi_iw(iface)

# --- Main loop: meten en via UDP sturen --------------------------------------
def main():
    # Bepaal verbonden interface automatisch (of fallback naar wlan0)
    iface = get_connected_iface()

    # Hostnaam van de Raspberry Pi (wordt mee verstuurd in het JSON berichtveld "pi")
    host  = socket.gethostname()

    # Print éénmalig de configuratie zodat je in logs ziet waarheen er gestuurd wordt en aan welke snelheid
    print(
        f"[pi_rssi_sender_raw] {host} via {iface} → {COLLECTOR_IP}:{COLLECTOR_PORT} | {POLL_HZ:.1f} Hz",
        flush=True
    )

    # Maak een UDP socket aan (SOCK_DGRAM = UDP)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # UDP socket

    # Oneindige meet- en verzendlus
    while True:
        # t0 gebruiken we om de effectieve looptijd van de iteratie af te trekken van de sleep,
        # zodat we gemiddeld POLL_HZ blijven benaderen.
        t0 = time.monotonic()

        # Lees RSSI van de wifi-interface (float in dBm) of None als uitlezen faalt
        rssi = poll_rssi(iface)

        # Alleen versturen als we effectief een RSSI-waarde konden ophalen
        if rssi is not None:
            # Stel payload samen:
            # - "pi": identificatie van de zender (hostnaam)
            # - "ts": Unix timestamp (seconden sinds epoch) zodat ontvanger timing kan volgen
            # - "rssi_dbm": RSSI afgerond op 2 decimalen
            msg = {"pi": host, "ts": time.time(), "rssi_dbm": round(float(rssi), 2)}

            try:
                # UDP JSON versturen (socket.sendto):
                # - json.dumps(msg) maakt een JSON-string
                # - encode("utf-8") maakt bytes voor verzending
                # - (COLLECTOR_IP, COLLECTOR_PORT) is het doeladres
                sock.sendto(json.dumps(msg).encode("utf-8"), (COLLECTOR_IP, COLLECTOR_PORT))
            except Exception as e:
                # Bij verzendfout schrijven we een foutmelding naar stderr (handig bij systemd logs)
                print("[send-err]", e, file=sys.stderr)

        # Houd ongeveer POLL_HZ aan:
        # - Bepaal hoeveel tijd de iteratie al nam
        # - Slaap de resterende tijd (minstens 0) zodat de totale periode ongeveer POLL_DT wordt
        time.sleep(max(0.0, POLL_DT - (time.monotonic() - t0)))

# Script-entrypoint:
# - Zorgt dat main() enkel draait wanneer je dit bestand direct uitvoert,
#   en niet wanneer je het zou importeren als module.
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # Netjes afsluiten bij Ctrl+C zonder stacktrace
        sys.exit(0)
