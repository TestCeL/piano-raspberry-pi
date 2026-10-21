#!/bin/bash
# Prepara en el PC el "Softify Piano Vol 1" (Pianobook, Dore Mark) y lo copia a la Raspberry (fase 08).
# Pianobook exige una cuenta para descargarlo, así que el usuario baja el .zip y este script lo procesa:
# extrae SOLO la versión SFZ y el Readme (sin la parte de Kontakt), lo envía a la Pi como tar por SSH y compara
# el SHA-256 de CADA archivo con el del zip original. Las sumas se calculan con Python en ambos lados y en el
# mismo formato: el sha256sum de Git Bash en Windows escribe las líneas distinto ("*./archivo") que el de Linux.
# Si la Pi ya tiene una copia completa y correcta (carpeta .part de un intento anterior), no se vuelve a copiar.
# Uso (en el PC, Git Bash): tools/instrumentos/preparar-softify.sh [ARCHIVO.zip] usuario@ip-de-la-pi   (o con PIANO_PI)
set -euo pipefail

ZIP="${1:-$HOME/Downloads/Softify Piano Vol 1 v1.1.zip}"
PI="${2:-${PIANO_PI:-}}"          # la Pi por SSH: argumento o variable PIANO_PI
[ -n "$PI" ] || { echo "Uso: $0 ARCHIVO.zip usuario@ip-de-la-pi   (o define PIANO_PI=usuario@ip-de-la-pi)" >&2; exit 2; }
DESTINO='piano/instrumentos/softify'
[ -s "$ZIP" ] || { echo "ERROR: no se encuentra $ZIP" >&2; exit 1; }
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Lista "sha256  ruta" ordenada por ruta (bytes), calculada desde el zip sin extraer: SFZ/x -> ./x, Readme.txt.
# (tr quita los retornos de carro (CR) que pone Python en Windows: las líneas deben ser idénticas byte a byte a las de la Pi.)
python -I - "$ZIP" <<'EOF' | tr -d '\r' > "$TMP/sumas-zip.txt"
import hashlib, sys, zipfile
filas = []
with zipfile.ZipFile(sys.argv[1]) as z:
    for i in z.infolist():
        if i.is_dir() or not (i.filename.startswith("SFZ/") or i.filename == "Readme.txt"):
            continue
        h = hashlib.sha256()
        with z.open(i) as f:
            for bloque in iter(lambda: f.read(1 << 20), b""):
                h.update(bloque)
        ruta = "./" + (i.filename[4:] if i.filename.startswith("SFZ/") else i.filename)
        filas.append((ruta.encode("utf-8"), h.hexdigest()))
for ruta, h in sorted(filas):
    print(f"{h}  {ruta.decode('utf-8')}")
EOF
SUMAS_PI='import hashlib, os, sys
raiz = os.path.expanduser(sys.argv[1])
filas = []
for d, _, archivos in os.walk(raiz):
    for a in archivos:
        p = os.path.join(d, a)
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for bloque in iter(lambda: f.read(1 << 20), b""):
                h.update(bloque)
        filas.append((("./" + os.path.relpath(p, raiz)).encode("utf-8"), h.hexdigest()))
for ruta, h in sorted(filas):
    print(f"{h}  {ruta.decode()}")'
sumas_pi() { ssh -n -o BatchMode=yes "$PI" "python3 -c '$SUMAS_PI' '~/$DESTINO.part' 2>/dev/null" > "$TMP/sumas-pi.txt" || true; }
echo "== $(wc -l < "$TMP/sumas-zip.txt") archivos en la versión SFZ del zip ($(du -h "$ZIP" | cut -f1))"

sumas_pi
if cmp -s "$TMP/sumas-zip.txt" "$TMP/sumas-pi.txt"; then
    echo "== La Pi ya tiene una copia completa y correcta: no se vuelve a copiar"
else
    echo "== Extracción de la versión SFZ"
    # Extracción con Python en modo aislado (-I): solo SFZ/ y Readme.txt, rechazando rutas absolutas o con "..".
    python -I - "$ZIP" "$TMP/softify" <<'EOF'
import os, sys, zipfile
origen, destino = sys.argv[1], sys.argv[2]
n = 0
with zipfile.ZipFile(origen) as z:
    for i in z.infolist():
        nombre = i.filename
        if not (nombre.startswith("SFZ/") or nombre == "Readme.txt") or i.is_dir():
            continue
        partes = nombre.replace("\\", "/").split("/")
        if nombre.startswith("/") or ".." in partes:
            sys.exit(f"ruta sospechosa en el zip: {nombre}")
        relativa = nombre[len("SFZ/"):] if nombre.startswith("SFZ/") else nombre
        ruta = os.path.join(destino, *relativa.split("/"))
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with z.open(i) as f, open(ruta, "wb") as g:
            for bloque in iter(lambda: f.read(1 << 20), b""):
                g.write(bloque)
        n += 1
print(f"   {n} archivos extraídos")
EOF
    echo "== Copia a $PI:~/$DESTINO"
    ssh -n -o BatchMode=yes "$PI" "rm -rf ~/$DESTINO.part && mkdir -p ~/$DESTINO.part"
    tar -C "$TMP/softify" -cf - . | ssh -o BatchMode=yes "$PI" "tar -xf - -C ~/$DESTINO.part"
    sumas_pi
fi

echo "== Verificación archivo por archivo (SHA-256 del zip frente a la Pi)"
if ! cmp -s "$TMP/sumas-zip.txt" "$TMP/sumas-pi.txt"; then
    echo "ERROR: los archivos de la Pi no coinciden con el zip:" >&2
    diff "$TMP/sumas-zip.txt" "$TMP/sumas-pi.txt" | head -10 >&2
    exit 1
fi
TAM="$(stat -c %s "$ZIP")"
SUMA="$(sha256sum "$ZIP" | cut -d' ' -f1)"
ssh -n -o BatchMode=yes "$PI" "set -e; rm -rf ~/$DESTINO; mv ~/$DESTINO.part ~/$DESTINO
    m=~/piano/instrumentos/MANIFIESTO-descargas.txt; touch \$m; sed -i '/^softify /d' \$m
    echo \"softify pianobook:Softify_Piano_Vol_1_v1.1.zip $TAM $SUMA \$(date -u +%Y-%m-%dT%H:%M:%SZ)\" >> \$m
    du -sh ~/$DESTINO"
echo "== Listo: Softify Piano en $PI:~/$DESTINO ($(wc -l < "$TMP/sumas-zip.txt") archivos verificados; zip SHA-256 $SUMA)"
