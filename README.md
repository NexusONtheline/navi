# NAVI

> *En la actualidad. En este momento.*
AVISO> NAVI esta en beta y se puede actualizar constantemente recuerda actualiar tu navi con git pull

Asistente personal para Linux inspirado en NAVI de **Serial Experiments Lain**.
Vive en tu terminal, te habla, te escucha y controla tu PC/Laptop. *uso vibecoding con claude*

**100% gratis**: usa la capa gratuita de la API de Gemini (cada persona pone su propia key, por ahora solo esta para key de gemini)
y todo lo de voz funciona en tu PC, sin internet.

```
> NAVI, actívate          (suena un pitido y te escucha)
> pon Duvet de Bôa
> recuérdame mañana a las 9 llamar al dentista
> ¿qué noticias hay?
> busca una serie sobre podólogos y mándasela a mi mamá por correo
> ayúdame con el error que sale en la terminal
> apágate en 30 minutos
```

## Instalación

En **Linux Mint / Ubuntu / Debian** o **Arch / LainOS**:

```bash
git clone https://github.com/NexusONtheline/navi.git
cd navi
./instalar.sh
```

El instalador:

1. Instala los programas que necesita (te pide tu contraseña una vez).
2. Te pide una **API key gratis de Gemini** → sácala en https://aistudio.google.com/apikey
3. Descarga la voz y los oídos de NAVI (unos 650 MB, solo la primera vez).
4. Crea el comando `navi` y un acceso en el menú de aplicaciones.
5. Te pregunta si quieres «NAVI, actívate», el saludo al encender y el atajo **Super+N**.

Después, abre una terminal y escribe:

```bash
navi
```

Dentro de NAVI: **escribe**, o pulsa **Enter vacío** para hablarle. `salir` para cerrarla.

## Qué sabe hacer

**Voz** (todo local, sin internet)
- Te habla (Piper, voz femenina de España) y te escucha (Whisper)
- Se despierta cuando dices **«NAVI, actívate»** (Vosk)
- Te saluda al encender el PC: hora, clima y recordatorios

**Tu PC**
- Abrir apps, volumen, brillo, Bluetooth (batería, conectar, emparejar)
- Estado del PC (CPU, RAM, temperatura, batería) y actualizaciones pendientes
- Apagar, reiniciar o suspender (ahora o programado), siempre preguntándote antes
- Ventanas y workspaces *(solo en Sway)*

**Día a día**
- Recordatorios y temporizadores que suenan aunque NAVI esté cerrada
- Memoria: «recuerda que mi hermano se llama Pablo»
- Clima y pronóstico (Open-Meteo, sin registro)
- Noticias a tu medida (anime, Linux, videojuegos, IA, curiosidades, series,
  ciberseguridad, Ecuador...), sin bolsa ni criptomonedas

**Internet**
- Buscar en internet (DuckDuckGo) y abrir enlaces
- Preparar correos en Gmail (NAVI escribe el borrador, tú pulsas Enviar) y abrir tu bandeja
- Música de YouTube sin abrir el navegador, y controlar cualquier reproductor

**Ayudas**
- Portapapeles: resumir, traducir o corregir lo que copiaste
- Ver tu pantalla: «ayúdame con este error» (con tu permiso)

## Compatibilidad

| | Sway / LainOS | Linux Mint (Cinnamon) |
|---|---|---|
| Conversar, voz, oído, «NAVI, actívate» | ✅ | ✅ |
| Recordatorios, memoria, clima, noticias, correo, música | ✅ | ✅ |
| Volumen, brillo, Bluetooth, apagar | ✅ | ✅ |
| Portapapeles | ✅ (wl-clipboard) | ✅ (xclip) |
| Ver la pantalla | ✅ una ventana | ✅ pantalla completa |
| Controlar ventanas y workspaces | ✅ | ❌ por ahora |

> Probado a fondo en LainOS + Sway. En Linux Mint todavía está **en pruebas**:
> si algo falla, avisa con el mensaje de error.

## Privacidad

- Tu `.env` (con tu API key) **nunca** se sube a GitHub: está en `.gitignore`.
- Tu voz se procesa **en tu PC**. A Gemini solo le llega el texto.
- «NAVI, actívate» escucha **solo** esa frase, en tu PC y sin guardar nada.
  `navi --privado` apaga el micrófono; `navi --no-privado` lo vuelve a encender.
- NAVI **nunca** guarda contraseñas: su memoria y el portapapeles rechazan contraseñas,
  PINs y números de tarjeta.
- La memoria vive en `~/.local/share/navi/` (fuera del proyecto), pero se envía a Gemini
  al abrir NAVI para que te conozca.
- **Acciones delicadas** (apagar, ver la pantalla): la propia interfaz te pregunta y espera
  tu sí o no; la IA no puede saltarse la pregunta ni contestarla por ti. Las capturas
  de pantalla se envían a Google y se borran enseguida.
- Ojo: en la capa gratuita de Gemini, Google puede usar las conversaciones para mejorar
  sus modelos. No le cuentes a NAVI nada que no quieras que Google lea.

## Configuración

Todo está en el archivo `.env` (las opciones están explicadas en `.env.example`):
tu nombre, tu ciudad, la voz (tono, velocidad, filtro robótico), el micrófono, etc.

Comandos útiles:

```
navi               abre NAVI
navi --saludo      NAVI te saluda (como al encender el PC)
navi --privado     el vigilante suelta el micrófono
navi --no-privado  vuelve a escuchar «NAVI, actívate»
```

## Si algo falla

- **No me escucha**: revisa que el micrófono no esté silenciado. Mide el volumen con
  `cd navi && .venv/bin/python -m navi.oido`.
- **«Límite gratuito de Gemini»**: el plan gratis permite unas 15 peticiones por minuto.
  Espera un poco.
- **La música no suena**: YouTube a veces bloquea un rato si se le pide mucho seguido.
  Revisa que esté instalado `deno`.
- **Qué hizo NAVI**: las herramientas que usó quedan en
  `$XDG_RUNTIME_DIR/navi/herramientas.log` y el vigilante en `vigilante.log`.

## Agregar habilidades

Cada habilidad es una función de Python en `navi/herramientas/`. Gemini lee el
docstring para saber cuándo usarla. Crea tu módulo y regístralo en
`navi/herramientas/__init__.py`. (o puedes dejar un comentario dando ideas de que habilidades le podemos meter!)

