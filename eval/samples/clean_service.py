import hashlib
import os
import re

import requests

DB_PASSWORD = os.environ["DB_PASSWORD"]
TOKEN_PATTERN = re.compile(r"\b\d{6}\b")


def find_user(cursor, user_id):
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    return cursor.fetchone()


def fetch_profile(user_id):
    try:
        response = requests.get(
            f"https://api.example.com/users/{user_id}", timeout=5
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None


def fingerprint(data):
    return hashlib.sha256(data).hexdigest()


def join_words(words):
    return " ".join(words)


def has_token(text):
    return TOKEN_PATTERN.search(text) is not None
