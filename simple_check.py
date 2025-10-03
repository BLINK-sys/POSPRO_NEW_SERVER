#!/usr/bin/env python3
import sqlite3

# Подключаемся к базе данных
conn = sqlite3.connect('pospro.db')
cursor = conn.cursor()

# Получаем список таблиц
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = cursor.fetchall()

print("Tables in database:")
for table in tables:
    print(f"  {table[0]}")

# Проверяем структуру homepage_blocks если существует
if any('homepage_blocks' in table[0] for table in tables):
    print("\nColumns in homepage_blocks:")
    cursor.execute("PRAGMA table_info(homepage_blocks)")
    columns = cursor.fetchall()
    for column in columns:
        print(f"  {column[1]} ({column[2]})")
else:
    print("\nhomepage_blocks table not found")

conn.close()
