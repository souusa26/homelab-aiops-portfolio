#!/bin/bash
# =============================================================================
# Homelab Quick Healthcheck Script
# Avalia rapidamente saturação de hardware, status dos containers e conectividade.
# =============================================================================

echo "========================================="
echo "   HOMELAB HEALTHCHECK - $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================="

echo -e "\n[+] UPTIME & LOAD:"
uptime

echo -e "\n[+] MEMÓRIA RAM:"
free -h

echo -e "\n[+] ARMAZENAMENTO DISCO:"
df -h -x tmpfs -x devtmpfs -x squashfs

echo -e "\n[+] DOCKER CONTAINERS (STATUS):"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "Docker indisponível"

echo -e "\n[+] TESTE DE RESOLUÇÃO DNS LOCAL:"
dig @127.0.0.1 +short google.com 2>/dev/null && echo "DNS Local OK" || echo "Falha no DNS Local"

echo -e "\n========================================="
