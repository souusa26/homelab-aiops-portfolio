# Homelab AIOps MCP Server 🧠⚡

Servidor baseado no protocolo **Model Context Protocol (MCP)** que conecta assistentes de inteligência artificial (Claude Desktop, Claude Opus, Gemini, Antigravity CLI) diretamente ao ciclo de vida e sustentação operacional do homelab.

---

## 🛠️ Ferramentas Expostas (Tools)

| Ferramenta | Descrição |
| :--- | :--- |
| `get_host_telemetry` | Coleta métricas de CPU, memória RAM, I/O de disco, load average e status da bateria (UPS). |
| `list_docker_containers` | Inspeciona containers Docker ativos, parados ou com falha. |
| `restart_docker_service` | Reinício seguro de containers com verificação estrita em allowlist. |
| `get_prometheus_active_alerts` | Consulta endpoints de alertas do Prometheus em tempo real. |

---

## ⚙️ Configuração do Cliente MCP

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "homelab": {
      "command": "python3",
      "args": [
        "/caminho/para/homelab-aiops-portfolio/ai-ops/mcp-homelab-server/server.py"
      ],
      "env": {
        "PROMETHEUS_URL": "http://127.0.0.1:9090"
      }
    }
  }
}
```

### Antigravity CLI / Gemini (`~/.gemini/config/mcp_config.json`)

```json
{
  "mcpServers": {
    "homelab": {
      "command": "python3",
      "args": [
        "/home/tiago2609/homelab-aiops-portfolio/ai-ops/mcp-homelab-server/server.py"
      ]
    }
  }
}
```
