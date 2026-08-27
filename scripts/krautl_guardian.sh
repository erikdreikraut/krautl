#!/bin/sh
set -eu

# Läuft auf dem Docker-Host per systemd-Timer. Ein Container kann durch seine
# Restart-Policy nur nach einem Absturz neu gestartet werden. Wurde er entfernt
# oder beim Deployment nie angelegt, stellt dieser Wächter den vollständigen
# Compose-Verbund wieder her.
KRAUTL_DIR="${KRAUTL_DIR:-/opt/app/krautl}"
cd "$KRAUTL_DIR"

reparatur_noetig=0

for dienst in db app worker frontend; do
    container_id="$(docker compose ps -q "$dienst" 2>/dev/null || true)"
    if [ -z "$container_id" ]; then
        echo "Krautl-Wächter: $dienst fehlt und wird wiederhergestellt."
        reparatur_noetig=1
        continue
    fi

    status="$(docker inspect --format '{{.State.Status}}' "$container_id" 2>/dev/null || echo missing)"
    if [ "$status" != "running" ]; then
        echo "Krautl-Wächter: $dienst ist $status und wird wieder gestartet."
        reparatur_noetig=1
        continue
    fi

    gesundheit="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id" 2>/dev/null || echo missing)"
    if [ "$gesundheit" = "unhealthy" ]; then
        echo "Krautl-Wächter: $dienst ist unhealthy und wird neu gestartet."
        docker compose restart "$dienst"
    fi
done

if [ "$reparatur_noetig" -eq 1 ]; then
    # Normalerweise existieren die Images bereits. Falls auch ein Image fehlt,
    # baut der zweite Versuch es aus dem aktuellen, ausgecheckten Stand neu.
    docker compose up -d --no-build || docker compose up -d --build
fi
