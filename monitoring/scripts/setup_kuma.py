import sqlite3
import json

db_path = '/var/lib/docker/volumes/monitoring_uptime_kuma_data/_data/kuma.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 1. Insert notification
config = {
    "telegramBotToken": "${TELEGRAM_BOT_TOKEN}",
    "telegramChatID": "${TELEGRAM_CHAT_ID}",
    "telegramSendSilently": False,
    "telegramProtectContent": False,
    "type": "telegram"
}

cursor.execute("INSERT INTO notification (name, active, user_id, is_default, config) VALUES (?, 1, 1, 1, ?)", 
               ("Telegram Alerta", json.dumps(config)))
notification_id = cursor.lastrowid

# 2. Insert monitor
cursor.execute("INSERT INTO monitor (name, type, url, user_id, interval, maxretries, retry_interval, method, accepted_statuscodes_json) VALUES (?, 'http', ?, 1, 60, 3, 60, 'GET', '[\"200-299\"]')", 
               ("AppMonitor", "https://app.example.com"))
monitor_id = cursor.lastrowid

# 3. Link them
cursor.execute("INSERT INTO monitor_notification (monitor_id, notification_id) VALUES (?, ?)", (monitor_id, notification_id))

conn.commit()
conn.close()
print("Success")
