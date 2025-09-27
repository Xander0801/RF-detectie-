from flask import Flask, render_template, jsonify
import socket, threading, json

# http://127.0.0.1:5000/

app = Flask(__name__)

latest_data = {}   # hier verzamelen we de pakketten van de Pi's

def udp_server():
    global latest_data
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 5005))  # luistert op alle interfaces
    while True:
        data, addr = sock.recvfrom(1024)
        pkt = json.loads(data.decode())
        latest_data[pkt["id"]] = pkt   # opslaan per Pi
        print("Received:", pkt)

threading.Thread(target=udp_server, daemon=True).start()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/data")
def data():
    # bouw lijst met alle Pi-posities
    pis = [latest_data[i]["pos"] for i in sorted(latest_data)]
    phone = (0,0)  # later: berekenen uit RSSI of simuleren
    return jsonify({"pis": pis, "phone": phone})

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
