import sqlite3

DB_PASSWORD = "sup3r-secret-value"


def find_user(cursor, name):
    cursor.execute("SELECT * FROM users WHERE name = '" + name + "'")
    return cursor.fetchone()


def find_by_id(cursor, user_id):
    cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
    return cursor.fetchone()


def run_user_formula(formula):
    return eval(formula)
