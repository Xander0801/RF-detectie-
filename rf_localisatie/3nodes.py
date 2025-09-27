import socket, json, time, random

CENTRAL_IP = "192.168.1.100"   # IP van de centrale Pi
CENTRAL_PORT = 5005
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# vaste locatie van deze Pi
pi_position = (0, 0)   # pas aan voor elke Pi
pi_id = 1              # maak 1, 2, 3 afhankelijk van Pi

while True:
    # hier zou je echte RSSI meten, voorlopig random
    rssi = -30 - random.uniform(0, 20)
    
    packet = {
        "id": pi_id,
        "pos": pi_position,
        "rssi": rssi
    }
    sock.sendto(json.dumps(packet).encode(), (CENTRAL_IP, CENTRAL_PORT))
    time.sleep(1)

