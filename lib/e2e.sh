#!/usr/bin/env bash
# ============================================================
#  e2e.sh — unica via del agente e2e-tester para apps, navegador y emulador
#
#  Nunca contra produccion: apunta las apps SOLO al backend local (E2E_API), el navegador no
#  resuelve hosts que no sean locales y el emulador no tiene DNS. Detalle: e2e.py --help.
#
#  uso: e2e.sh api <copia-e2e> <web|android> [<backend>]
#       e2e.sh app <copia-e2e> -- fvm flutter build web|drive|test ...
#       e2e.sh servir <copia-e2e>/build/web
#       e2e.sh web <copia-e2e> <prueba.spec.js> [--project web-movil|web-escritorio]
#       e2e.sh emulador arrancar <copia-e2e> | parar <serial> | estado
#       e2e.sh adb <args>            e2e.sh cuentas <copia-e2e>            e2e.sh doctor
# ============================================================
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$DIR/e2e.py" "$@"
