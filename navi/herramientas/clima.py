"""Herramienta de clima con Open-Meteo: gratis, sin registro y sin API key.

Solo se envía el nombre de la ciudad (y sus coordenadas) a open-meteo.com.
"""

import json
import urllib.parse
import urllib.request

from .. import config

_GEOCODIFICAR = "https://geocoding-api.open-meteo.com/v1/search"
_PRONOSTICO = "https://api.open-meteo.com/v1/forecast"

# Códigos de tiempo de la Organización Meteorológica Mundial (WMO)
_CIELO = {
    0: "despejado", 1: "mayormente despejado", 2: "parcialmente nublado", 3: "nublado",
    45: "niebla", 48: "niebla con escarcha",
    51: "llovizna débil", 53: "llovizna", 55: "llovizna intensa",
    56: "llovizna helada", 57: "llovizna helada intensa",
    61: "lluvia débil", 63: "lluvia", 65: "lluvia fuerte",
    66: "lluvia helada", 67: "lluvia helada fuerte",
    71: "nevada débil", 73: "nevada", 75: "nevada fuerte", 77: "granizo fino",
    80: "chubascos débiles", 81: "chubascos", 82: "chubascos violentos",
    85: "chubascos de nieve", 86: "chubascos de nieve fuertes",
    95: "tormenta", 96: "tormenta con granizo", 99: "tormenta con granizo fuerte",
}


def _pedir(url: str, parametros: dict) -> dict:
    direccion = f"{url}?{urllib.parse.urlencode(parametros)}"
    with urllib.request.urlopen(direccion, timeout=10) as r:
        return json.load(r)


def clima(ciudad: str = "", dias: int = 1) -> str:
    """Consulta el clima actual y el pronóstico de una ciudad.

    Args:
        ciudad: Nombre de la ciudad, por ejemplo "Madrid" o "Santiago, Chile".
            Dejar vacío para usar la ciudad del usuario.
        dias: Días de pronóstico, de 1 (solo hoy) a 7.
    """
    ciudad = ciudad.strip() or config.CIUDAD
    if not ciudad:
        return ("No sé en qué ciudad está el usuario. Pregúntale, y sugiérele "
                "poner NAVI_CIUDAD en su archivo .env.")
    dias = max(1, min(int(dias), 7))

    try:
        nombre, _, pais = ciudad.partition(",")
        lugares = _pedir(_GEOCODIFICAR, {"name": nombre.strip(), "count": 10,
                                         "language": "es"}).get("results", [])
        if pais.strip():
            filtrados = [l for l in lugares if pais.strip().lower() in
                         (l.get("country", "") + l.get("admin1", "")).lower()]
            lugares = filtrados or lugares
        if not lugares:
            return f"No encontré la ciudad '{ciudad}'."
        lugar = lugares[0]

        datos = _pedir(_PRONOSTICO, {
            "latitude": lugar["latitude"], "longitude": lugar["longitude"],
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                       "weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                     "precipitation_probability_max",
            "timezone": "auto", "forecast_days": dias,
        })
    except OSError as e:
        return f"No pude conectarme al servicio del clima: {e}"

    actual = datos["current"]
    lineas = [
        f"{lugar['name']}, {lugar.get('admin1', '')}, {lugar.get('country', '')}".replace(", ,", ","),
        f"Ahora: {_CIELO.get(actual['weather_code'], 'desconocido')}, "
        f"{actual['temperature_2m']:.0f} °C (sensación {actual['apparent_temperature']:.0f} °C), "
        f"humedad {actual['relative_humidity_2m']}%, viento {actual['wind_speed_10m']:.0f} km/h",
    ]
    diario = datos["daily"]
    for i, fecha in enumerate(diario["time"]):
        lluvia = diario["precipitation_probability_max"][i]
        lineas.append(
            f"{fecha}: {_CIELO.get(diario['weather_code'][i], 'desconocido')}, "
            f"mín {diario['temperature_2m_min'][i]:.0f} °C, máx {diario['temperature_2m_max'][i]:.0f} °C"
            + (f", {lluvia}% probabilidad de lluvia" if lluvia is not None else "")
        )
    return "\n".join(lineas)


HERRAMIENTAS = [clima]
