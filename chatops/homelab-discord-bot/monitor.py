import subprocess
import psutil
import requests
import logging
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple
from config import (
    DOCKER_CONTAINERS, SYSTEM_SERVICES, 
    DISK_ALERT, CPU_ALERT, RAM_ALERT, TEMP_ALERT,
    ALERT_COOLDOWN, COMMAND_TIMEOUT, ALERT_HISTORY_FILE, MAX_ALERTS_HISTORY
)

logger = logging.getLogger(__name__)

# ========================
# ALERT COOLDOWN TRACKING
# ========================
last_alerts: Dict[str, datetime] = {}

def should_alert(alert_key: str) -> bool:
    """Evita spam de alertas com cooldown em minutos"""
    now = datetime.now()
    last_time = last_alerts.get(alert_key)
    
    if last_time is None:
        last_alerts[alert_key] = now
        return True
    
    if now - last_time >= timedelta(minutes=ALERT_COOLDOWN):
        last_alerts[alert_key] = now
        return True
    
    logger.debug(f"Alert {alert_key} em cooldown")
    return False

# ========================
# ALERT HISTORY
# ========================

def load_alert_history() -> List[Dict]:
    """Carrega histórico de alertas do arquivo"""
    try:
        if Path(ALERT_HISTORY_FILE).exists():
            with open(ALERT_HISTORY_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Erro ao carregar histórico de alertas: {e}")
    return []

def save_alert_history(alerts: List[Dict]) -> None:
    """Salva histórico de alertas, mantendo apenas os mais recentes"""
    try:
        alerts = alerts[-MAX_ALERTS_HISTORY:]
        with open(ALERT_HISTORY_FILE, 'w') as f:
            json.dump(alerts, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Erro ao salvar histórico de alertas: {e}")

def add_alert_to_history(alert_message: str) -> None:
    """Adiciona novo alerta ao histórico"""
    try:
        alerts = load_alert_history()
        alerts.append({
            "timestamp": datetime.now().isoformat(),
            "message": alert_message
        })
        save_alert_history(alerts)
    except Exception as e:
        logger.error(f"Erro ao adicionar alerta ao histórico: {e}")

# ========================
# SYSTEM COMMANDS
# ========================

def run_command(command: List[str]) -> str:
    """Executa comando com segurança, timeout e tratamento de erro"""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT
        )
        
        if result.returncode != 0:
            logger.warning(f"Comando retornou erro: {' '.join(command)} - {result.stderr}")
            return ""
        
        return result.stdout.strip()
    
    except subprocess.TimeoutExpired:
        logger.error(f"Comando expirou (timeout {COMMAND_TIMEOUT}s): {' '.join(command)}")
        return ""
    except Exception as e:
        logger.error(f"Erro ao executar comando {' '.join(command)}: {e}")
        return ""

# ========================
# TEMPERATURE (ROBUSTO)
# ========================

def get_temperature() -> float | str:
    """
    Obtém temperatura do CPU de forma robusta.
    Tenta psutil primeiro, depois fallback para 'sensors'
    """
    try:
        temps = psutil.sensors_temperatures()
        
        if temps:
            for name, entries in temps.items():
                if 'coretemp' in name.lower() or 'k10temp' in name.lower():
                    for entry in entries:
                        if 'package' in entry.label.lower() or entry.label == '':
                            return round(entry.current, 1)
            
            for name, entries in temps.items():
                if entries:
                    return round(entries[0].current, 1)
        
        output = run_command(["sensors"])
        if output:
            for line in output.splitlines():
                if "Package id 0" in line or "Tctl" in line:
                    try:
                        start = line.find("+") + 1
                        end = line.find("°")
                        if start > 0 and end > start:
                            temp_str = line[start:end].strip()
                            return float(temp_str)
                    except (ValueError, IndexError):
                        continue
        
        logger.warning("Não foi possível obter temperatura")
        return "N/A"
    
    except Exception as e:
        logger.error(f"Erro ao obter temperatura: {e}")
        return "N/A"

# ========================
# INTERNET CHECK
# ========================

def internet_online(retries: int = 2) -> bool:
    """Verifica conexão de internet com retry logic"""
    urls = [
        "https://1.1.1.1",
        "https://8.8.8.8",
        "https://google.com"
    ]
    
    for url in urls:
        for attempt in range(retries):
            try:
                requests.head(url, timeout=5)
                return True
            except Exception as e:
                logger.debug(f"Tentativa {attempt + 1} falhou para {url}: {e}")
                continue
    
    logger.warning("Internet offline - todas as tentativas falharam")
    return False

# ========================
# SYSTEM METRICS
# ========================

def get_system_stats() -> Dict:
    """Retorna estatísticas do sistema"""
    try:
        return {
            "cpu": psutil.cpu_percent(interval=1),
            "ram": psutil.virtual_memory().percent,
            "disk": psutil.disk_usage('/').percent,
            "temp": get_temperature(),
            "uptime": run_command(["uptime", "-p"]),
            "internet": internet_online()
        }
    except Exception as e:
        logger.error(f"Erro ao obter stats: {e}")
        return {
            "cpu": 0, "ram": 0, "disk": 0, "temp": "N/A",
            "uptime": "N/A", "internet": False
        }

# ========================
# SERVICE MONITORING
# ========================

def check_docker_container(name: str) -> Tuple[bool, str]:
    """
    Verifica se container Docker está rodando.
    Retorna (status, mensagem_erro)
    """
    container = DOCKER_CONTAINERS.get(name)
    if not container:
        return False, "Container não encontrado na config"
    
    try:
        status = run_command([
            "docker", "inspect", "-f", "{{.State.Status}}", container
        ])
        is_running = (status == "running")
        error_msg = "" if is_running else f"Status: {status or 'N/A'}"
        return is_running, error_msg
    except Exception as e:
        logger.error(f"Erro ao verificar container {name}: {e}")
        return False, str(e)

def check_system_service(name: str) -> Tuple[bool, str]:
    """
    Verifica se serviço systemd está ativo.
    Retorna (status, mensagem_erro)
    """
    service = SYSTEM_SERVICES.get(name)
    if not service:
        return False, "Serviço não encontrado na config"
    
    try:
        status = run_command(["systemctl", "is-active", service])
        is_active = (status == "active")
        error_msg = "" if is_active else f"Status: {status or 'N/A'}"
        return is_active, error_msg
    except Exception as e:
        logger.error(f"Erro ao verificar serviço {name}: {e}")
        return False, str(e)

def get_offline_services() -> List[str]:
    """Retorna lista de serviços offline"""
    offline = []
    
    for name in DOCKER_CONTAINERS.keys():
        is_running, _ = check_docker_container(name)
        if not is_running:
            offline.append(name)
    
    for name in SYSTEM_SERVICES.keys():
        is_active, _ = check_system_service(name)
        if not is_active:
            offline.append(name)
    
    return offline

# ========================
# HEALTH CHECKS
# ========================

def check_health() -> Dict:
    """Executa verificação completa de saúde"""
    stats = get_system_stats()
    offline = get_offline_services()
    
    return {
        **stats,
        "offline_services": offline
    }

def generate_alerts() -> List[str]:
    """
    Gera lista de alertas baseado em thresholds.
    Implementa cooldown para evitar spam.
    """
    alerts = []
    stats = get_system_stats()
    
    if stats["cpu"] >= CPU_ALERT and should_alert("cpu"):
        msg = f"🔴 CPU ALTA: {stats['cpu']}%"
        alerts.append(msg)
        add_alert_to_history(msg)
        logger.warning(f"Alert: {msg}")
    
    if stats["ram"] >= RAM_ALERT and should_alert("ram"):
        msg = f"🔴 RAM ALTA: {stats['ram']}%"
        alerts.append(msg)
        add_alert_to_history(msg)
        logger.warning(f"Alert: {msg}")
    
    if stats["disk"] >= DISK_ALERT and should_alert("disk"):
        msg = f"🔴 DISCO CHEIO: {stats['disk']}%"
        alerts.append(msg)
        add_alert_to_history(msg)
        logger.warning(f"Alert: {msg}")
    
    if stats["temp"] != "N/A" and isinstance(stats["temp"], (int, float)):
        if stats["temp"] >= TEMP_ALERT and should_alert("temp"):
            msg = f"🔴 TEMPERATURA ALTA: {stats['temp']}°C"
            alerts.append(msg)
            add_alert_to_history(msg)
            logger.warning(f"Alert: {msg}")
    
    for container in DOCKER_CONTAINERS.keys():
        is_running, error = check_docker_container(container)
        if not is_running and should_alert(f"docker_{container}"):
            msg = f"🔴 CONTAINER OFFLINE: {container} ({error})"
            alerts.append(msg)
            add_alert_to_history(msg)
            logger.warning(f"Alert: {msg}")
    
    for service in SYSTEM_SERVICES.keys():
        is_active, error = check_system_service(service)
        if not is_active and should_alert(f"service_{service}"):
            msg = f"🔴 SERVIÇO OFFLINE: {service} ({error})"
            alerts.append(msg)
            add_alert_to_history(msg)
            logger.warning(f"Alert: {msg}")
    
    if not stats["internet"] and should_alert("internet"):
        msg = "🔴 INTERNET OFFLINE"
        alerts.append(msg)
        add_alert_to_history(msg)
        logger.warning(f"Alert: {msg}")
    
    return alerts
