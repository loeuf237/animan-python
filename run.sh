#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=== Lancement de AnimeLab (Python / FastAPI) ==="

# Normalisation automatique des proxys SOCKS (socks:// -> socks5:// pour httpx / GNOME)
for var in all_proxy ALL_PROXY socks_proxy SOCKS_PROXY; do
    val="${!var:-}"
    if [[ "$val" == socks://* ]]; then
        export "$var"="socks5://${val#socks://}"
    fi
done

export ANIMAN_RELOAD="${ANIMAN_RELOAD:-true}"
python3 run.py "$@"

