#!/bin/bash
# =============================================================================
# Plex & Remote Storage Mount Watchdog
# Verifica a integridade dos pontos de montagem remotos (SSHFS / NFS / CIFS)
# e reinicia os serviços systemd e o container do Plex caso ocorra timeout.
# Executado via Cron ou Systemd Timer a cada minuto.
# =============================================================================

MOUNT_FILMES="${REMOTE_FILMES:-/mnt/remote_filmes}"
MOUNT_SERIES="${REMOTE_SERIES:-/mnt/remote_series}"
COMPOSE_DIR="${MEDIA_COMPOSE_DIR:-/opt/media-stack}"

check_mount() {
    local mount_point=$1
    # Timeout de 5s para prevenir travamento de I/O em caso de desconexão de rede
    if ! timeout 5 stat "$mount_point" > /dev/null 2>&1; then
        return 1
    fi
    return 0
}

needs_restart=0

if ! check_mount "$MOUNT_FILMES" || ! check_mount "$MOUNT_SERIES"; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Um ou mais pontos de montagem remotos estão inacessíveis. Remontando..."
    # Força a desmontagem lazy caso estejam travados
    umount -l "$MOUNT_FILMES" "$MOUNT_SERIES" 2>/dev/null
    
    # Reinicia unidades automount do systemd
    systemctl restart mnt-remote_filmes.automount 2>/dev/null
    systemctl restart mnt-remote_series.automount 2>/dev/null
    
    needs_restart=1
fi

# Verifica estado do container Plex
PLEX_STATUS=$(docker inspect -f '{{.State.Status}}' plex 2>/dev/null)
if [ "$PLEX_STATUS" != "running" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Plex não está em execução (status: $PLEX_STATUS)."
    needs_restart=1
fi

if [ "$needs_restart" -eq 1 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restabelecendo stack do Plex..."
    if [ -d "$COMPOSE_DIR" ]; then
        cd "$COMPOSE_DIR" && docker compose up -d plex
    fi
fi
