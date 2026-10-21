#!/usr/bin/env python3
"""Instala en la Pi el «Softify Piano Vol 1» (Pianobook, Dore Mark) desde el zip que el usuario descarga de Pianobook
(requiere una cuenta; la licencia no permite redistribuir las muestras, por eso no se descarga solo).

Uso: instalar_softify.py ARCHIVO.zip [--otra-version]
  - comprueba que el zip es la versión medida en el proyecto (v1.1, por su SHA-256); --otra-version instala otra
    avisando de que el catálogo puede no encontrar su SFZ (el nombre del archivo lleva la versión);
  - extrae SOLO la versión SFZ (SFZ/ -> softify/) y Readme.txt, sin la parte de Kontakt; rechaza rutas sospechosas;
  - verifica cada archivo extraído contra el contenido del zip (SHA-256);
  - reemplaza la instalación anterior solo al final (se extrae en softify.part) y lo anota en el manifiesto.
Destino: $PIANO_INSTRUMENTOS (por defecto ~/piano/instrumentos)/softify. Códigos: 0 bien, 1 error, 2 uso.
"""
import hashlib
import os
import shutil
import sys
import time
import zipfile

SHA_ZIP = "dc01c625dd5c560ffda88573ba79ce9bb50cd10979679a3fc2386609ed9c5b2c"   # Softify Piano Vol 1 v1.1.zip
CARPETA = "softify"
SFZ = "Softify Piano Vol 1 V1.1.sfz"


def sha256_de(lector):
    h = hashlib.sha256()
    for bloque in iter(lambda: lector.read(1 << 20), b""):
        h.update(bloque)
    return h.hexdigest()


def elegidos(z):
    """[(entrada del zip, ruta relativa de destino)]: SFZ/... sin el prefijo y Readme.txt. ValueError si una ruta
    es sospechosa (absoluta, con «..» o con barras invertidas)."""
    lista = []
    for i in z.infolist():
        nombre = i.filename
        if i.is_dir() or not (nombre.startswith("SFZ/") or nombre == "Readme.txt"):
            continue
        partes = nombre.split("/")
        if nombre.startswith("/") or "\\" in nombre or ".." in partes or ":" in partes[0]:
            raise ValueError(f"ruta sospechosa en el zip: {nombre}")
        relativa = nombre[len("SFZ/"):] if nombre.startswith("SFZ/") else nombre
        if relativa:
            lista.append((i, relativa))
    if not any(e.filename.startswith("SFZ/") for e, _ in lista):    # el Readme solo no es un instrumento
        raise ValueError("el zip no tiene la versión SFZ (carpeta SFZ/)")
    return lista


def instalar(zip_ruta, destino, sha_esperado=SHA_ZIP, otra_version=False, salida=print):
    """Instala y devuelve el número de archivos. ValueError (sin tocar nada instalado) si algo no cuadra."""
    with open(zip_ruta, "rb") as f:
        suma = sha256_de(f)
    if suma != sha_esperado:
        if not otra_version:
            raise ValueError(f"el zip no es la versión medida en el proyecto (SHA-256 {suma}); "
                             "si es otra versión del Softify, usar --otra-version")
        salida("AVISO: otra versión del zip: el catálogo espera «" + SFZ + "»")
    if not zipfile.is_zipfile(zip_ruta):
        raise ValueError(f"{zip_ruta} no es un zip")
    os.makedirs(destino, exist_ok=True)
    final = os.path.join(destino, CARPETA)
    parte = final + ".part"
    shutil.rmtree(parte, ignore_errors=True)
    try:
        with zipfile.ZipFile(zip_ruta) as z:
            lista = elegidos(z)
            for entrada, relativa in lista:
                ruta = os.path.join(parte, *relativa.split("/"))
                os.makedirs(os.path.dirname(ruta), exist_ok=True)
                with z.open(entrada) as origen, open(ruta, "wb") as copia:
                    shutil.copyfileobj(origen, copia, 1 << 20)
            for entrada, relativa in lista:                 # verificación: lo escrito = lo que hay en el zip
                with z.open(entrada) as origen, open(os.path.join(parte, *relativa.split("/")), "rb") as copia:
                    if sha256_de(origen) != sha256_de(copia):
                        raise ValueError(f"el archivo extraído no coincide con el zip: {relativa}")
    except BaseException:
        shutil.rmtree(parte, ignore_errors=True)
        raise
    shutil.rmtree(final, ignore_errors=True)
    os.rename(parte, final)
    manifiesto = os.path.join(destino, "MANIFIESTO-descargas.txt")
    lineas = []
    if os.path.exists(manifiesto):
        with open(manifiesto, encoding="utf-8") as f:
            lineas = [l for l in f.read().splitlines() if not l.startswith(CARPETA + " ")]
    lineas.append(f"{CARPETA} pianobook:{os.path.basename(zip_ruta).replace(' ', '_')} {os.path.getsize(zip_ruta)} "
                  f"{suma} {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    with open(manifiesto, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")
    return len(lista)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    otra = "--otra-version" in argv
    resto = [a for a in argv if a != "--otra-version"]
    if len(resto) != 1 or not os.path.isfile(resto[0]):
        print(__doc__.split("\n\n")[1].split("\n")[0], file=sys.stderr)
        print("ERROR: falta el zip del Softify (descárgalo de https://www.pianobook.co.uk/packs/softify-piano-vol-1/)",
              file=sys.stderr)
        return 2
    destino = os.environ.get("PIANO_INSTRUMENTOS", os.path.expanduser("~/piano/instrumentos"))
    try:
        n = instalar(resto[0], destino, otra_version=otra)
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"Softify instalado en {os.path.join(destino, CARPETA)}: {n} archivos verificados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
