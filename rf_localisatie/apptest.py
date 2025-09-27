from flask import Flask, render_template, jsonify
import socket, threading, json

#http://127.0.0.1:5000/
#pip install Flask-Twilio

app = Flask(__name__)

pi_positions = [(0, 0), (10, 0), (5, 8)]
latest_packet = None   # zal dict zijn met 'phone' en 'pis'

def udp_server():
    global latest_packet
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 5005))
    while True:
        data, _ = sock.recvfrom(4096)
        pkt = json.loads(data.decode())

        # Altijd opslaan als dict met phone & pis
        if isinstance(pkt, dict):
            latest_packet = pkt
        else:
            latest_packet = {"phone": (0,0), "pis": pkt}

        print("SERVER received:", latest_packet)  # debug

threading.Thread(target=udp_server, daemon=True).start()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/data")
def data():
    global latest_packet
    if not latest_packet:
        return jsonify({"pis": [], "phone": (0, 0)})

    phone = latest_packet.get("phone", (0,0))
    # haal de posities van de Pi’s uit het pakket
    pis = [pi["pos"] for pi in latest_packet["pis"]]

    return jsonify({
        "pis": pis,
        "phone": phone
    })

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
