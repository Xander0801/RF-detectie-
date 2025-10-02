import math, time, socket, json, random

UDP_IP, UDP_PORT = "127.0.0.1", 5005
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# startposities Pi's
pi_positions = [
    [0.0, 0.0],   # Pi1
    [10.0, 0.0],  # Pi2
    [5.0, 8.0]    # Pi3
]

def distance(p1, p2): 
    return ((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2) ** 0.5

def simulate_rssi(dist): 
    return -30 - 2 * dist + random.uniform(-2, 2)

angle, radius, center = 0.0, 4.5, (6, 4)

while True:
    # beweeg phone in cirkel
    phone_pos = (
        center[0] + radius * math.cos(angle),
        center[1] + radius * math.sin(angle)
    )
    angle += 0.2

    # laat Pi’s random wandelen
    for pos in pi_positions:
        pos[0] += random.uniform(-0.1, 0.1)  # kleine verschuiving x
        pos[1] += random.uniform(-0.1, 0.1)  # kleine verschuiving y

    # bouw het pakket
    pis = []
    for i, pi in enumerate(pi_positions):
        d = distance(phone_pos, pi)
        pis.append({
            "id": i+1,
            "pos": pi,
            "rssi": simulate_rssi(d)
        })

    packet = {"phone": phone_pos, "pis": pis}

    print("SIM phone ->", tuple(round(v, 2) for v in phone_pos))
    for pi in pis:
        print(f" Pi{pi['id']} -> pos={tuple(round(v,2) for v in pi['pos'])}, rssi={pi['rssi']:.2f}")

    # verstuur naar server
    sock.sendto(json.dumps(packet).encode(), (UDP_IP, UDP_PORT))
    time.sleep(1)
