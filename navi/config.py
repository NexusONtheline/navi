"""Configuración leída desde el archivo .env (nunca se sube a GitHub)."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
# Versión liviana: rápida y con buena cuota gratis
GEMINI_MODELO = os.environ.get("GEMINI_MODELO", "gemini-3.5-flash-lite").strip()
NOMBRE_USUARIO = os.environ.get("NAVI_USUARIO", "").strip()
CIUDAD = os.environ.get("NAVI_CIUDAD", "").strip()  # para el clima
# Dónde abrir los borradores de correo: "gmail" (web) o "predeterminado" (mailto:)
CORREO = os.environ.get("NAVI_CORREO", "gmail").strip().lower()

# YouTube: cliente con el que yt-dlp se presenta, y cookies opcionales del navegador
# (solo si YouTube bloquea; "firefox" usa tu sesión de YouTube de Firefox)
YOUTUBE_CLIENTE = os.environ.get("NAVI_YOUTUBE_CLIENTE", "").strip()  # vacío = el de yt-dlp
YOUTUBE_COOKIES = os.environ.get("NAVI_YOUTUBE_COOKIES", "").strip()
MPV_EXTRA = os.environ.get("NAVI_MPV_EXTRA", "").split()  # opciones extra para mpv

# Voz: "piper" (natural), "espeak" (robótica retro) o "ninguno"
VOZ_MOTOR = os.environ.get("NAVI_VOZ", "piper").strip().lower()
VOZ_PIPER_MODELO = os.environ.get("NAVI_VOZ_PIPER", "es_ES-sharvard-medium").strip()
_hablante = os.environ.get("NAVI_VOZ_PIPER_HABLANTE", "1").strip()  # sharvard: 1 = mujer
VOZ_PIPER_HABLANTE = int(_hablante) if _hablante else None
VOZ_ESPEAK = os.environ.get("NAVI_VOZ_ESPEAK", "es-419+f3").strip()
VOZ_VELOCIDAD = float(os.environ.get("NAVI_VOZ_VELOCIDAD", "1.0"))  # >1 más lento
VOZ_FILTRO = float(os.environ.get("NAVI_VOZ_FILTRO", "0.2"))  # 0 = sin filtro Wired
VOZ_TONO = float(os.environ.get("NAVI_VOZ_TONO", "3"))  # semitonos: +4 más aguda, -3 más grave
VOZ_ESPEAK_TONO = int(os.environ.get("NAVI_VOZ_ESPEAK_TONO", "50"))  # 0-99, tono base de espeak

# Oído (Whisper): "small" (entiende mejor), "base" (más rápido) o "ninguno"
OIDO_MODELO = os.environ.get("NAVI_OIDO", "small").strip().lower()
# Micrófono: "interno" (el del PC, recomendado con audífonos Bluetooth),
# vacío (el predeterminado del sistema) o el nombre exacto de PipeWire
OIDO_MICROFONO = os.environ.get("NAVI_MICROFONO", "interno").strip()


def validar() -> None:
    if not GEMINI_API_KEY or GEMINI_API_KEY.startswith("pega-aqui"):
        sys.exit(
            "Falta GEMINI_API_KEY.\n"
            "1. Consigue una gratis en https://aistudio.google.com/apikey\n"
            "2. Copia .env.example a .env y pégala ahí."
        )
