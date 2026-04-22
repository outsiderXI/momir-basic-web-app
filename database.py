import sqlite3
from config import DB_FILE

def get_connection():
    return sqlite3.connect(DB_FILE)

def get_all_cards():

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT name,id FROM cards")
    rows = cur.fetchall()

    conn.close()
    return rows
