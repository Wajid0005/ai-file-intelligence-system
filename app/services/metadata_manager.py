import json
import os

METADATA_FILE = "metadata/files.json"
os.makedirs("metadata", exist_ok=True)


def save_metadata(data):
    if not os.path.exists(METADATA_FILE):

        with open(METADATA_FILE, "w") as f:
            json.dump([],f)

    with open(METADATA_FILE, "r") as f:
        existing_data = json.load(f)
    existing_data.append(data)

    with open(METADATA_FILE,"w") as f:
        json.dump(existing_data, f, indent=4)


def load_metadata():
    if not os.path.exists(METADATA_FILE):
        return []

    with open(METADATA_FILE, "r") as f:
        return json.load(f)