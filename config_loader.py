import json
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("config.json")

def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)
