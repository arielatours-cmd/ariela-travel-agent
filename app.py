import os
from flask import Flask, jsonify, request
from scanner import search_flights, scan_configured_routes

app = Flask(__name__)

@app.get("/")
def home():
    return jsonify({
        "name": "Ariella Tours",
        "version": "2.0",
        "status": "online",
        "serpapi_configured": bool(os.getenv("SERPAPI_API_KEY")),
        "manual_search_example": "/search?departure=TLV&arrival=ATH&outbound=2026-09-10&return_date=2026-09-15",
        "configured_scan": "/scan"
    })

@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "serpapi_configured": bool(os.getenv("SERPAPI_API_KEY"))
    })

@app.get("/search")
def search():
    departure = request.args.get("departure", "TLV").upper()
    arrival = request.args.get("arrival", "").upper()
    outbound = request.args.get("outbound", "")
    return_date = request.args.get("return_date", "")
    adults = request.args.get("adults", "1")
    children = request.args.get("children", "0")
    carry_on_bags = request.args.get("carry_on_bags", "0")

    if not arrival or not outbound:
        return jsonify({
            "status": "error",
            "message": "Missing required parameters: arrival and outbound"
        }), 400

    try:
        return jsonify(search_flights(
            departure=departure,
            arrival=arrival,
            outbound_date=outbound,
            return_date=return_date or None,
            adults=adults,
            children=children,
            carry_on_bags=carry_on_bags
        ))
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500

@app.get("/scan")
@app.post("/scan")
def scan():
    try:
        return jsonify(scan_configured_routes())
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
