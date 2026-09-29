import json
import requests


NTFY_TOPIC = "PHBsS109"

NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}/json"


def listen_for_news():

    with requests.get(
        NTFY_URL,
        stream=True,
        timeout=None
    ) as response:

        response.raise_for_status()

        print("Connected to ntfy.")

        for line in response.iter_lines():

            if not line:
                continue

            data = json.loads(
                line.decode("utf-8")
            )

            # ntfy also sends connection events
            if data.get("event") != "message":
                continue

            message = data.get(
                "message",
                ""
            )

            title = data.get(
                "title",
                ""
            )

            if title:
                headline = f"{title}: {message}"
            else:
                headline = message

            if headline:
                yield headline
