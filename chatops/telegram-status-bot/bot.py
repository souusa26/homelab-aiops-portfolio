"""
Telegram Status Bot — bot leve de status do servidor (long polling, sem framework).

Comandos: /status (CPU/RAM/disco), /docker (estado dos containers), /ping (healthcheck HTTP
do endpoint público). Em paralelo roda um loop de alerta com thresholds 80%/90% e cooldown de 1h.
"""
import os
import requests
import time
import subprocess
import threading

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
HEALTHCHECK_URL = os.getenv("HEALTHCHECK_URL", "https://app.example.com")
HEALTHCHECK_NAME = os.getenv("HEALTHCHECK_NAME", "app")
URL = f"https://api.telegram.org/bot{TOKEN}/"

def get_status():
    try:
        cpu = float(subprocess.check_output("top -bn1 | grep 'Cpu(s)' | awk '{print $2 + $4}'", shell=True).decode().strip())
        mem = float(subprocess.check_output("free -m | awk 'NR==2{printf \"%.2f\", $3*100/$2 }'", shell=True).decode().strip())
        mem_gb = subprocess.check_output("free -h | awk 'NR==2{printf \"%s / %s\", $3, $2 }'", shell=True).decode().strip()
        disk = float(subprocess.check_output("df -h / | awk '$NF==\"/\"{print $5}' | sed 's/%//'", shell=True).decode().strip())
        disk_str = subprocess.check_output("df -h / | awk '$NF==\"/\"{printf \"%s%% (Usado: %s, Livre: %s)\", $5, $3, $4}'", shell=True).decode().strip()
        dockers = subprocess.check_output("docker ps -q | wc -l", shell=True).decode().strip()
        
        msg = f"🖥 *Status da Máquina (Notebook)*\n\n"
        msg += f"🧠 *CPU:* {cpu}%\n"
        msg += f"🐏 *RAM:* {mem}% ({mem_gb})\n"
        msg += f"💾 *Disco:* {disk_str}\n"
        msg += f"🐳 *Contêineres Ativos:* {dockers}"
        return msg, cpu, mem, disk
    except Exception as e:
        return f"Erro ao obter status: {e}", 0, 0, 0

def get_ping():
    try:
        start_time = time.time()
        r = requests.get(HEALTHCHECK_URL, timeout=10)
        elapsed = round((time.time() - start_time) * 1000)
        if r.status_code == 200:
            return f"🌐 *{HEALTHCHECK_NAME} está ONLINE!*\n✅ Status HTTP: 200 OK\n⏱️ Tempo de resposta: {elapsed}ms"
        else:
            return f"⚠️ *{HEALTHCHECK_NAME} retornou erro!*\n❌ Status HTTP: {r.status_code}\n⏱️ Tempo de resposta: {elapsed}ms"
    except requests.exceptions.RequestException as e:
        return f"🔴 *{HEALTHCHECK_NAME} está OFFLINE!*\nErro: Falha na conexão ou Timeout."

def get_docker_status():
    try:
        output = subprocess.check_output("docker ps -a --format '{{.Names}}|{{.State}}|{{.Status}}'", shell=True).decode().strip()
        if not output:
            return "Nenhum contêiner encontrado."
        
        lines = output.split('\n')
        msg = "🐳 *Status dos Contêineres:*\n\n"
        
        for line in lines:
            parts = line.split('|')
            if len(parts) >= 3:
                name = parts[0]
                state = parts[1]
                status = parts[2]
                
                if state == "running":
                    icon = "🟢"
                elif state == "exited":
                    icon = "🔴"
                elif state == "paused":
                    icon = "⏸️"
                else:
                    icon = "🟡"
                    
                msg += f"{icon} *{name}*\n└ {status}\n\n"
        
        # Split message if it's too long for Telegram (limit is 4096 chars)
        return msg[:4000]
    except Exception as e:
        return f"Erro ao obter dockers: {e}"

def alert_monitor():
    last_alert = {"cpu": 0, "mem": 0, "disk": 0}
    while True:
        try:
            _, cpu, mem, disk = get_status()
            
            # Check thresholds (90% Critical, 80% Warning)
            for name, val in [("CPU", cpu), ("RAM", mem), ("Disco", disk)]:
                if val >= 90 and (time.time() - last_alert[name.lower()] > 3600):
                    requests.post(URL + "sendMessage", json={"chat_id": CHAT_ID, "text": f"🚨 *ALERTA CRÍTICO* 🚨\n{name} atingiu *{val}%*!", "parse_mode": "Markdown"})
                    last_alert[name.lower()] = time.time()
                elif val >= 80 and val < 90 and (time.time() - last_alert[name.lower()] > 3600):
                    requests.post(URL + "sendMessage", json={"chat_id": CHAT_ID, "text": f"⚠️ *ATENÇÃO* ⚠️\n{name} atingiu *{val}%*!", "parse_mode": "Markdown"})
                    last_alert[name.lower()] = time.time()
        except:
            pass
        time.sleep(60)

# Start alert monitor in background
t = threading.Thread(target=alert_monitor, daemon=True)
t.start()

offset = None
print("Iniciando bot...")
while True:
    try:
        r = requests.get(URL + "getUpdates", params={"offset": offset, "timeout": 30}).json()
        for update in r.get("result", []):
            offset = update["update_id"] + 1
            if "message" in update and "text" in update["message"]:
                text = update["message"]["text"]
                chat_id = update["message"]["chat"]["id"]

                # Só responde ao chat do dono — o bot expõe estado interno do servidor.
                if str(chat_id) != str(CHAT_ID):
                    continue
                
                if text.startswith("/status"):
                    msg, _, _, _ = get_status()
                    requests.post(URL + "sendMessage", json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})
                elif text.startswith("/ping"):
                    msg = get_ping()
                    requests.post(URL + "sendMessage", json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})
                elif text.startswith("/docker"):
                    msg = get_docker_status()
                    requests.post(URL + "sendMessage", json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})
                elif text.startswith("/start"):
                    help_text = f"Olá! Aqui estão os comandos disponíveis:\n\n`/status` - Ver CPU, RAM e Disco.\n`/docker` - Ver status de todos os contêineres.\n`/ping` - Testar se o {HEALTHCHECK_NAME} está no ar."
                    requests.post(URL + "sendMessage", json={"chat_id": chat_id, "text": help_text, "parse_mode": "Markdown"})
    except Exception as e:
        time.sleep(5)
