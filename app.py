import os
from flask import Flask, jsonify
from scanner import run_scan

app = Flask(__name__)

@app.get("/")
def home():
    return jsonify({
        "name": "Ariella Tours",
        "status": "online",
        "message": "Ariella is running"
    })

@app.get("/health")
def health():
    return jsonify({"status": "ok"})

@app.post("/scan")
def scan():
    return jsonify(run_scan())

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
