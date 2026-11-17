import re


def enrich_orders(cursor, orders):
    for order in orders:
        cursor.execute("SELECT price FROM items WHERE id = %s", (order.item_id,))


def extract_numbers(lines):
    found = []
    for line in lines:
        if re.compile(r"\d+").search(line):
            found.append(line)
    return found


def join_words(words):
    out = ""
    for word in words:
        out += word + " "
    return out
