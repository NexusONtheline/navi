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
# Si el principal se satura (pasa a veces), NAVI usa este un rato. Vacío = no usar reserva
GEMINI_MODELO_RESERVA = os.environ.get("GEMINI_MODELO_RESERVA", "gemini-3.5-flash").strip()

# Groq (opcional): otra IA gratis y muy rápida. Clave en https://console.groq.com/keys
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODELO = os.environ.get("GROQ_MODELO", "openai/gpt-oss-120b").strip()
# Cuál usar primero: "gemini" o "groq". El otro (si tiene clave) queda de reserva
IA = os.environ.get("NAVI_IA", "gemini").strip().lower()
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
    global GEMINI_API_KEY, GROQ_API_KEY
    if GEMINI_API_KEY.startswith("pega-aqui"):
        GEMINI_API_KEY = ""
    if GROQ_API_KEY.startswith("pega-aqui"):
        GROQ_API_KEY = ""
    if not GEMINI_API_KEY and not GROQ_API_KEY:
        sys.exit(
            "Falta una API key (GEMINI_API_KEY o GROQ_API_KEY).\n"
            "1. Consigue una gratis en https://aistudio.google.com/apikey\n"
            "   o en https://console.groq.com/keys\n"
            "2. Copia .env.example a .env y pégala ahí."
        )
