import json
import os

METADATA_FILE = "metadata/files.json"

os.makedirs("metadata", exist_ok=True)


# -----------------------------------
# LOAD METADATA
# -----------------------------------
def load_metadata():

    if not os.path.exists(METADATA_FILE):

        return []

    try:

        with open(
            METADATA_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except json.JSONDecodeError:

        return []


# -----------------------------------
# SAVE METADATA
# -----------------------------------
def save_metadata(data):

    existing_data = load_metadata()

    existing_data.append(data)

    with open(
        METADATA_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            existing_data,
            f,
            indent=4
        )


# -----------------------------------
# NORMALIZE TEXT
# -----------------------------------
def normalize_text(text):

    text = text.lower()

    text = " ".join(
        text.split()
    )

    return text


# -----------------------------------
# FIND DUPLICATES
# -----------------------------------
def find_duplicate(
    file_hash=None,
    content_hash=None,
    original_filename=None
):

    data = load_metadata()

    for item in data:

        # filename duplicate
        if (
            original_filename
            and item.get(
                "original_filename",
                ""
            ).lower()
            ==
            original_filename.lower()
        ):

            return item

        # exact file duplicate
        if (
            file_hash
            and item.get("file_hash")
            ==
            file_hash
        ):

            return item

        # content duplicate
        if (
            content_hash
            and item.get("content_hash")
            ==
            content_hash
        ):

            return item

    return None


# -----------------------------------
# SEARCH METADATA
# -----------------------------------
def search_metadata(query):

    data = load_metadata()

    results = []

    query = query.lower()

    for item in data:

        if (
            query in item.get(
                "new_filename",
                ""
            ).lower()

            or

            query in item.get(
                "category",
                ""
            ).lower()

            or

            query in item.get(
                "summary",
                ""
            ).lower()
        ):

            results.append(item)

    return results