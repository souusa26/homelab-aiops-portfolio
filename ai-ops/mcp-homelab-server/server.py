#!/usr/bin/env python3
"""
Homelab AIOps MCP Server (Model Context Protocol)
Permite que LLMs e agentes de IA (Claude, Gemini, Antigravity) inspecionem métricas de host,
consultem telemetria de containers Docker, monitorem alertas Prometheus e atuem na infraestrutura
com privilégios mínimos e validação rigorosa.
"""

import os
import subprocess
import json
import psutil
import requests
from typing import Dict, Any, List, Optional
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("homelab-aiops-server")

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://127.0.0.1:9090")
ALLOWED_SERVICES = {
    "plex", "qbittorrent", "sonarr", "radarr", "prowlarr",
    "minecraft", "mc-monitor", "telas_livres_api", "telas_livres_db",
    "telas_livres_caddy", "telas_livres_tunnel", "homeassistant", "go2rtc"
}


@mcp.tool()
def get_host_telemetry() -> Dict[str, Any]:
    """Retorna métricas em tempo real de hardware do servidor host (CPU, RAM, Disco, Load, Bateria/UPS)."""
    cpu_pct = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    load = os.getloadavg()
    
    battery_info = None
    if hasattr(psutil, "sensors_battery"):
        b = psutil.sensors_battery()
        if b:
            battery_info = {
                "percent": b.percent,
                "power_plugged": b.power_plugged,
                "is_ups_mode": not b.power_plugged
            }

    return {
        "cpu_usage_percent": cpu_pct,
        "memory": {
            "total_gb": round(mem.total / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "free_gb": round(mem.free / (1024**3), 2),
            "used_percent": mem.percent
        },
        "disk_root": {
            "total_gb": round(disk.total / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
            "used_percent": disk.percent
        },
        "load_average_1_5_15m": load,
        "ups_battery": battery_info
    }


@mcp.tool()
def list_docker_containers() -> List[Dict[str, str]]:
    """Lista todos os containers Docker em execução no host com seus respectivos estados e imagens."""
    try:
        cmd = ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Image}}\t{{.State}}\t{{.Status}}"]
        output = subprocess.check_output(cmd, text=True, timeout=5).strip()
        containers = []
        if output:
            for line in output.splitlines():
                parts = line.split("\t")
                if len(parts) >= 4:
                    containers.append({
                        "name": parts[0],
                        "image": parts[1],
                        "state": parts[2],
                        "status": parts[3]
                    })
        return containers
    except Exception as e:
        return [{"error": f"Falha ao listar containers: {str(e)}"}]


@mcp.tool()
def restart_docker_service(service_name: str) -> Dict[str, Any]:
    """Reinicia com segurança um serviço/container Docker previamente autorizado na lista de controle."""
    clean_name = service_name.strip().lower()
    if clean_name not in ALLOWED_SERVICES:
        return {
            "success": False,
            "error": f"Serviço '{service_name}' não está na lista de permissões autorizadas para automação."
        }

    try:
        subprocess.check_call(["docker", "restart", clean_name], timeout=30)
        return {"success": True, "message": f"Serviço {clean_name} reiniciado com sucesso."}
    except Exception as e:
        return {"success": False, "error": f"Erro durante reinício do serviço: {str(e)}"}


@mcp.tool()
def get_prometheus_active_alerts() -> Dict[str, Any]:
    """Consulta o servidor Prometheus e retorna alertas em estado 'firing' ou 'pending'."""
    try:
        url = f"{PROMETHEUS_URL}/api/v1/alerts"
        res = requests.get(url, timeout=5)
        if res.status_code != 200:
            return {"error": f"Prometheus respondeu com status {res.status_code}"}
        
        data = res.json().get("data", {}).get("alerts", [])
        firing = [a for a in data if a.get("state") == "firing"]
        pending = [a for a in data if a.get("state") == "pending"]

        return {
            "total_firing": len(firing),
            "total_pending": len(pending),
            "firing_alerts": firing,
            "pending_alerts": pending
        }
    except Exception as e:
        return {"error": f"Falha ao conectar no Prometheus em {PROMETHEUS_URL}: {str(e)}"}


if __name__ == "__main__":
    mcp.run()
