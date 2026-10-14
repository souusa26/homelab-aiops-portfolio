import os
from dotenv import load_dotenv

load_dotenv()

# ========================
# DISCORD
# ========================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
AUTHORIZED_USER_IDS = list(map(int, os.getenv("AUTHORIZED_USER_IDS", "").split(","))) if os.getenv("AUTHORIZED_USER_IDS") else []
ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID", "0"))

# ========================
# ALERT THRESHOLDS
# ========================
DISK_ALERT = int(os.getenv("DISK_ALERT", "90"))
CPU_ALERT = int(os.getenv("CPU_ALERT", "90"))
RAM_ALERT = int(os.getenv("RAM_ALERT", "90"))
TEMP_ALERT = int(os.getenv("TEMP_ALERT", "80"))

# ========================
# MONITOR
# ========================
MONITOR_INTERVAL = int(os.getenv("MONITOR_INTERVAL", "5"))
ALERT_COOLDOWN = int(os.getenv("ALERT_COOLDOWN", "60"))  # minutos entre alertas do mesmo tipo
COMMAND_TIMEOUT = int(os.getenv("COMMAND_TIMEOUT", "10"))  # segundos

# ========================
# LOGGING
# ========================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "homelab_bot.log")
MAX_LOG_SIZE = int(os.getenv("MAX_LOG_SIZE", "5242880"))  # 5MB
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "3"))

# ========================
# ALERT HISTORY
# ========================
ALERT_HISTORY_FILE = os.getenv("ALERT_HISTORY_FILE", "alert_history.json")
MAX_ALERTS_HISTORY = int(os.getenv("MAX_ALERTS_HISTORY", "100"))

# ========================
# SERVICES
# ========================
DOCKER_CONTAINERS = {
    "radarr": "radarr",
    "sonarr": "sonarr",
    "prowlarr": "prowlarr",
    "qbittorrent": "qbittorrent",
    "plex": "plex",
    "flaresolverr": "flaresolverr",
    "homeassistant": "homeassistant"
}

SYSTEM_SERVICES = {
    "adguard": "AdGuardHome" # Mantido caso ainda rode diretamente no SO
}

COMPOSE_PATHS = {
    "media-stack": "/root/media-stack",
    "homeassistant": "/root/homeassistant"
}

# ========================
# VALIDATION
# ========================
def validate_config():
    """Valida configurações essenciais"""
    errors = []
    
    if not DISCORD_TOKEN:
        errors.append("DISCORD_TOKEN não configurado no .env")
    if not AUTHORIZED_USER_IDS:
        errors.append("AUTHORIZED_USER_IDS não configurado no .env")
    if ALERT_CHANNEL_ID == 0:
        errors.append("ALERT_CHANNEL_ID não configurado no .env")
    
    if errors:
        raise ValueError("\n".join(errors))
