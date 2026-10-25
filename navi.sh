#!/usr/bin/env bash
# Lanzador de NAVI: ./navi.sh  (o «navi» si ejecutaste instalar.sh)
cd "$(dirname "$(readlink -f "$0")")" || exit 1
# Al abrirse desde el menú o al iniciar sesión, el PATH puede venir recortado
export PATH="$HOME/.deno/bin:$HOME/.local/bin:$PATH"
exec .venv/bin/python -m navi "$@"
