import requests


def fetch_profile(user_id):
    response = requests.get(f"https://api.example.com/users/{user_id}")
    return response.json()


def load_config(path):
    try:
        with open(path) as fh:
            return fh.read()
    except:
        return None


def parse_payload(raw):
    try:
        return int(raw)
    except ValueError:
        pass
