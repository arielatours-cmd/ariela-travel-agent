from datetime import datetime
from config_loader import load_config

def run_scan():
    config = load_config()

    # This starter version verifies that the agent is running.
    # In the next step we will connect a live flight-search provider
    # and WhatsApp alerts.
    return {
        "status": "ready",
        "checked_at": datetime.utcnow().isoformat() + "Z",
        "airports": config["departure_airports"],
        "checked_bag_required": config["checked_bag_required"],
        "alert_rule": config["alert_rule"],
        "message": "Ariella is ready for the flight-search connection."
    }
