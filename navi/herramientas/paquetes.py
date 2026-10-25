"""Instalar y desinstalar programas (pacman/yay en Arch, apt en Mint/Ubuntu/Debian).

La contraseña nunca pasa por NAVI: tras confirmar con el usuario, NAVI abre una
terminal con el comando ya escrito y es él quien la teclea ahí. Al terminar,
la propia terminal avisa con una notificación.
"""

import re
import shlex
import shutil
import subprocess

from .. import confirmaciones, escritorio, senales

# Solo nombres de paquete simples: evita que la IA meta cosas como "obs; rm -rf ~"
_NOMBRE_PAQUETE_VALIDO = re.compile(r"^[a-z0-9@._+-]+$")

# Quitar cualquiera de estos deja el sistema sin arrancar o sin poder instalar nada
_INTOCABLES = {
    "base", "linux", "linux-lts", "linux-zen", "linux-firmware", "glibc", "systemd",
    "sudo", "pacman", "yay", "bash", "coreutils", "grub", "mkinitcpio", "sway",
    "networkmanager", "iwd", "pipewire", "wireplumber", "python", "git",
    "apt", "dpkg", "libc6", "linux-image-generic", "network-manager",
    "cinnamon", "mint-meta-core", "ubuntu-minimal",
}


def _en_arch() -> bool:
    return shutil.which("pacman") is not None


def _en_debian() -> bool:
    return shutil.which("apt-get") is not None


def _salida(comando: list[str]) -> str:
    try:
        return subprocess.run(comando, capture_output=True, text=True, timeout=60).stdout
    except (subprocess.TimeoutExpired, OSError):
        return ""


def _ordenar(resultados: list[tuple[str, str]], buscado: str, limite: int) -> list[str]:
    """Primero los que se llaman igual, luego los que empiezan o contienen lo buscado
    en el nombre, y al final los que solo lo mencionan en la descripción."""
    def relevancia(resultado: tuple[str, str]) -> tuple[int, int]:
        nombre = resultado[0].split("/")[-1].split(" ")[0]
        if nombre == buscado:
            return 0, 0
        if nombre.startswith(buscado):
            return 1, len(nombre)
        if buscado in nombre:
            return 2, len(nombre)
        return 3, 0
    return [f"{nombre}: {descripcion}"
            for nombre, descripcion in sorted(resultados, key=relevancia)[:limite]]


def _resultados_pacman(texto: str) -> list[tuple[str, str]]:
    """pacman -Ss / yay -Ss: «repo/nombre versión [installed]» y la descripción debajo."""
    lineas = texto.splitlines()
    resultados = []
    for cabecera, descripcion in zip(lineas[::2], lineas[1::2]):
        repo_nombre = cabecera.split()[0]
        instalado = " (ya instalado)" if "[installed" in cabecera or "[instalado" in cabecera else ""
        resultados.append((f"{repo_nombre}{instalado}", descripcion.strip()))
    return resultados


def buscar_programa(nombre: str) -> str:
    """Busca un programa en los repositorios para saber el nombre exacto de su paquete.
    Úsala antes de instalar_programa si no estás segura del nombre
    (por ejemplo "OBS" → paquete "obs-studio").

    Args:
        nombre: Lo que dijo el usuario, por ejemplo "obs", "gimp" o "steam".
    """
    nombre = nombre.strip().lower()
    if not nombre or len(nombre) > 50:
        return "Dime qué programa buscar."
    if _en_arch():
        resultados = _ordenar(_resultados_pacman(_salida(["pacman", "-Ss", "--", nombre])),
                              nombre, 8)
        # Si en los repos oficiales no hay ninguno con ese nombre, miramos el AUR
        if shutil.which("yay") and not any(nombre in r.split(":")[0] for r in resultados):
            resultados += _ordenar(_resultados_pacman(
                _salida(["yay", "-Ss", "--aur", "--", nombre])), nombre, 5)
    elif _en_debian():
        texto = _salida(["apt-cache", "search", "--names-only", "--", nombre])
        resultados = _ordenar([tuple(linea.split(" - ", 1)) for linea in texto.splitlines()
                               if " - " in linea], nombre, 10)
    else:
        return "No sé instalar programas en esta distribución (solo Arch y Mint/Ubuntu/Debian)."
    if not resultados:
        return f"No encontré ningún paquete que se llame como «{nombre}»."
    return ("Paquetes encontrados (los «aur/» son del AUR, hechos por la comunidad):\n"
            + "\n".join(resultados))


def _info_paquete(paquete: str) -> bool | None:
    """Si el paquete existe: True si es del AUR, False si es de los repos. None si no existe."""
    if _en_arch():
        texto, aur = _salida(["pacman", "-Si", "--", paquete]), False
        if not texto and shutil.which("yay"):
            texto, aur = _salida(["yay", "-Si", "--aur", "--", paquete]), True
    else:
        texto, aur = _salida(["apt-cache", "show", "--", paquete]), False
    return aur if texto else None


def _esta_instalado(paquete: str) -> bool:
    if _en_arch():
        comando = ["pacman", "-Q", "--", paquete]
    else:
        comando = ["dpkg-query", "-W", "-f=${Status}", "--", paquete]
    r = subprocess.run(comando, capture_output=True, text=True)
    return r.returncode == 0 and ("installed" in r.stdout or _en_arch())


def _abrir_terminal(comando: str, exito: str, titulo: str) -> bool:
    """Abre una terminal que ejecuta `comando` (ahí el usuario escribe su contraseña)
    y avisa con una notificación al terminar."""
    senales.CARPETA.mkdir(mode=0o700, parents=True, exist_ok=True)
    guion = senales.CARPETA / "paquetes.sh"
    guion.write_text(f"""#!/bin/bash
echo "NAVI: {titulo}"
echo "Escribe tu contraseña si te la pide (NAVI no la ve)."
echo
if {comando}; then
    notify-send -a NAVI NAVI {shlex.quote(exito)} 2>/dev/null
    echo; echo "Listo. Esta ventana se cierra sola."
    sleep 4
else
    notify-send -a NAVI NAVI "No se completó: {titulo}" 2>/dev/null
    echo; read -rp "No se completó. Pulsa Enter para cerrar."
fi
""")
    return escritorio.abrir_en_terminal(["bash", str(guion)], clase="navi-paquetes",
                                        titulo=f"NAVI: {titulo}")


def instalar_programa(paquete: str) -> str:
    """Instala un programa. Llámala directamente con el nombre exacto del paquete
    (si no lo sabes, usa antes buscar_programa). NAVI le preguntará al usuario si
    está seguro y abrirá una terminal donde él escribe su contraseña.

    Args:
        paquete: Nombre exacto del paquete, por ejemplo "obs-studio".
    """
    paquete = paquete.strip().lower()
    if not _NOMBRE_PAQUETE_VALIDO.match(paquete):
        return f"Nombre de paquete no válido: {paquete!r}"
    if not (_en_arch() or _en_debian()):
        return "No sé instalar programas en esta distribución (solo Arch y Mint/Ubuntu/Debian)."
    if _esta_instalado(paquete):
        return f"«{paquete}» ya está instalado."
    aur = _info_paquete(paquete)
    if aur is None:
        return f"No existe el paquete «{paquete}». Usa buscar_programa para dar con el nombre."

    aviso = (" Es del AUR: lo hizo la comunidad, no los mantenedores de Arch."
             if aur else "")
    # La descripción suele venir en inglés: la voz la leería mal, así que no la decimos
    if not confirmaciones.preguntar(f"¿Instalo {paquete}?{aviso}"):
        return ("Respondió que no, así que no instalé nada. Contéstale en una frase, "
                "sin volver a preguntar.")

    if aur:
        comando = f"yay -S --needed --answerdiff None --answerclean None {paquete}"
    elif _en_arch():
        comando = f"sudo pacman -S --needed --noconfirm {paquete}"
    else:
        comando = f"sudo apt-get install -y {paquete}"
    if not _abrir_terminal(comando, f"{paquete} instalado.", f"instalar {paquete}"):
        return f"No encontré ninguna terminal donde instalarlo. Que ejecute: {comando}"
    return ("Hecho (ya lo confirmó): abrí una terminal para instalarlo; tiene que escribir "
            "su contraseña ahí (tú no la ves). Le llegará una notificación al terminar. "
            "Díselo en una frase, sin volver a preguntar.")


def desinstalar_programa(paquete: str) -> str:
    """Desinstala un programa. Llámala directamente con el nombre exacto del paquete.
    NAVI le preguntará al usuario si está seguro y abrirá una terminal donde él
    escribe su contraseña y ve qué se va a quitar.

    Args:
        paquete: Nombre exacto del paquete instalado, por ejemplo "obs-studio".
    """
    paquete = paquete.strip().lower()
    if not _NOMBRE_PAQUETE_VALIDO.match(paquete):
        return f"Nombre de paquete no válido: {paquete!r}"
    if not (_en_arch() or _en_debian()):
        return "No sé desinstalar programas en esta distribución (solo Arch y Mint/Ubuntu/Debian)."
    if paquete in _INTOCABLES:
        return (f"«{paquete}» es parte esencial del sistema: quitarlo podría dejar el PC "
                "sin arrancar. No lo voy a desinstalar.")
    if not _esta_instalado(paquete):
        return f"«{paquete}» no está instalado."

    if not confirmaciones.preguntar(f"¿Desinstalo {paquete}?"):
        return ("Respondió que no, así que no desinstalé nada. Contéstale en una frase, "
                "sin volver a preguntar.")

    # Sin --noconfirm: que vea en la terminal qué más se va a quitar antes de aceptar
    if _en_arch():
        comando = f"sudo pacman -Rns {paquete}"
    else:
        comando = f"sudo apt-get remove {paquete}"
    if not _abrir_terminal(comando, f"{paquete} desinstalado.", f"desinstalar {paquete}"):
        return f"No encontré ninguna terminal donde desinstalarlo. Que ejecute: {comando}"
    return ("Hecho (ya lo confirmó): abrí una terminal para desinstalarlo; tiene que "
            "escribir su contraseña y aceptar ahí. Díselo en una frase, sin volver a preguntar.")


HERRAMIENTAS = [buscar_programa, instalar_programa, desinstalar_programa]
