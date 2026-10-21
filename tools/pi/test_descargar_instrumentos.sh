#!/bin/bash
# Pruebas de descargar-instrumentos.sh con orígenes FALSOS locales (file://, repositorios git y archivos creados aquí):
# sin internet y sin tocar los instrumentos reales. Uso: bash test_descargar_instrumentos.sh
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
FALLOS=0
ok()    { echo "ok    - $1"; }
fallo() { echo "FALLO - $1"; FALLOS=$((FALLOS + 1)); }
comprobar() { if eval "$2"; then ok "$1"; else fallo "$1"; fi; }   # comprobar DESCRIPCION CONDICION

# El script se prueba desde una copia junto a un generar_cuerdas.py FALSO: deja una marca dentro de la carpeta que
# recibe (y falla si existe $T/romper-cuerdas), para comprobar que se llama con la carpeta de vsco2.
mkdir -p "$T/bin" "$T/srv" "$T/codeload"
cp "$DIR/descargar-instrumentos.sh" "$T/bin/"
cat > "$T/bin/generar_cuerdas.py" <<'EOF'
import os, sys
if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "romper-cuerdas")):
    sys.exit("fallo simulado")
open(os.path.join(sys.argv[1], "ensemble-falso.sfz"), "w").write("<region> sample=uno/a.wav\n")
EOF
export PIANO_DESCARGAS="$T/descargas" PIANO_INSTRUMENTOS="$T/inst" PIANO_CODELOAD="file://$T/codeload"
export PIANO_ORIGENES="$T/origenes.txt"
I="$T/inst"; D="$T/descargas"
git_q() { git -c init.defaultBranch=main -c user.name=prueba -c user.email=prueba@ejemplo "$@" >/dev/null 2>&1; }

# --- Orígenes falsos
# tar (repositorio de sfzinstruments): dos commits; el archivo de cada uno, como lo sirve GitHub (con el commit dentro)
git_q init "$T/repoA"
echo "<region> sample=a.wav" > "$T/repoA/Piano A.sfz"
head -c 65536 /dev/urandom > "$T/repoA/a.wav"          # muestras que no se comprimen: un archivo truncado se nota
git_q -C "$T/repoA" add -A; git_q -C "$T/repoA" commit -m uno
C1="$(git -C "$T/repoA" rev-parse HEAD)"
echo "cambio" >> "$T/repoA/Piano A.sfz"; git_q -C "$T/repoA" commit -am dos
C2="$(git -C "$T/repoA" rev-parse HEAD)"
mkdir -p "$T/codeload/repoA/tar.gz"
git -C "$T/repoA" archive --format=tar.gz --prefix="repoA-$C1/" "$C1" -o "$T/codeload/repoA/tar.gz/$C1"
# txz (FreePats): carpeta de primer nivel que se quita al extraer
mkdir -p "$T/fuente-txz/TxzTop"; echo "<region> sample=x.wav" > "$T/fuente-txz/TxzTop/x.sfz"
tar -cJf "$T/srv/t.tar.xz" -C "$T/fuente-txz" TxzTop
SHA_T="$(sha256sum "$T/srv/t.tar.xz" | cut -d' ' -f1)"
# 7z (si está disponible): se extrae tal cual, con su carpeta
HAY_7Z=0
if command -v 7z >/dev/null; then
    HAY_7Z=1
    mkdir -p "$T/fuente-7z/SevenTop"; echo "<region> sample=y.wav" > "$T/fuente-7z/SevenTop/y.sfz"
    (cd "$T/fuente-7z" && 7z a -bd "$T/srv/s.7z" SevenTop >/dev/null)
    SHA_S="$(sha256sum "$T/srv/s.7z" | cut -d' ' -f1)"
fi
# git (repositorio grande): solo dos de tres carpetas, rama sfz fijada a un commit
git_q init "$T/big"; git -C "$T/big" config uploadpack.allowFilter true
for c in "A/uno" "B/dos" "C/tres"; do mkdir -p "$T/big/$c"; echo "<region> sample=z.wav" > "$T/big/$c/i.sfz"; done
git_q -C "$T/big" checkout -b sfz; git_q -C "$T/big" add -A; git_q -C "$T/big" commit -m fijo
CB="$(git -C "$T/big" rev-parse HEAD)"

origenes() {   # origenes [LÍNEAS EXTRA]: el conjunto normal de orígenes de prueba
    {
        echo "tar|ta|repoA|$C1|"
        echo "txz|tx|file://$T/srv/t.tar.xz|$SHA_T|carpetaTx"
        [ "$HAY_7Z" = 0 ] || echo "7z|sz|file://$T/srv/s.7z|$SHA_S|"
        echo "git|gi|file://$T/big|sfz@$CB:A/uno;B/dos|"
        echo "git|vsco2|file://$T/big|sfz@$CB:A/uno|"
    } > "$PIANO_ORIGENES"
}
correr() { SALIDA="$(bash "$T/bin/descargar-instrumentos.sh" "$@" 2>&1)"; RC=$?; }
sin_partes() { [ -z "$(find "$I" "$D" -name '*.part' 2>/dev/null)" ]; }

# 1) Instalación completa
origenes
correr
comprobar "1: termina bien" '[ "$RC" -eq 0 ] || { echo "$SALIDA"; false; }'
comprobar "1: tar de GitHub por commit, sin la carpeta de primer nivel" '[ -f "$I/ta/Piano A.sfz" ]'
comprobar "1: txz en su carpeta propia (no la del id)" '[ -f "$I/carpetaTx/x.sfz" ] && [ ! -e "$I/tx" ]'
[ "$HAY_7Z" = 0 ] || comprobar "1: 7z extraído con su carpeta" '[ -f "$I/sz/SevenTop/y.sfz" ]'
comprobar "1: git solo con las carpetas pedidas y sin .git" \
    '[ -f "$I/gi/A/uno/i.sfz" ] && [ -f "$I/gi/B/dos/i.sfz" ] && [ ! -e "$I/gi/C" ] && [ ! -e "$I/gi/.git" ]'
comprobar "1: tras vsco2 se genera el ensemble de cuerdas dentro de su carpeta" '[ -f "$I/vsco2/ensemble-falso.sfz" ]'
comprobar "1: manifiesto con el commit y el SHA-256" \
    'grep -q "^ta repoA@$C1 " "$I/MANIFIESTO-descargas.txt" && grep -q "^tx freepats:t.tar.xz [0-9]* $SHA_T " "$I/MANIFIESTO-descargas.txt"'
comprobar "1: no quedan carpetas ni descargas a medias (.part)" sin_partes

# 2) Reutiliza lo descargado: sin los orígenes de archivos, vuelve a instalar igual
mv "$T/srv" "$T/srv-guardado"; mv "$T/codeload" "$T/codeload-guardado"
correr --forzar ta tx
comprobar "2: sin red (orígenes de archivos borrados) reinstala desde las descargas" \
    '[ "$RC" -eq 0 ] && [ -f "$I/ta/Piano A.sfz" ] && [ -f "$I/carpetaTx/x.sfz" ]'
# 3) Una descarga antigua por rama (versión anterior del script) sirve si lleva el commit fijado
mv "$D/repoA-$C1.tar.gz" "$D/repoA-master.tar.gz"
correr --forzar ta
comprobar "3: reutiliza repoA-master.tar.gz del commit fijado (lo renombra)" \
    '[ "$RC" -eq 0 ] && [ -s "$D/repoA-$C1.tar.gz" ] && [ ! -e "$D/repoA-master.tar.gz" ]'
mv "$T/srv-guardado" "$T/srv"; mv "$T/codeload-guardado" "$T/codeload"

# 4) SHA-256 que no cuadra: la descarga se borra, se detiene y lo instalado no se toca
rm -f "$D/t.tar.xz"; cp "$T/srv/t.tar.xz" "$T/t.tar.xz.bueno"
echo "basura" > "$T/fuente-txz/TxzTop/otro.sfz"; tar -cJf "$T/srv/t.tar.xz" -C "$T/fuente-txz" TxzTop
correr --forzar tx
comprobar "4: SHA-256 distinto: error" '[ "$RC" -ne 0 ] && grep -q "SHA-256" <<<"$SALIDA"'
comprobar "4: la descarga mala se borra" '[ ! -e "$D/t.tar.xz" ]'
comprobar "4: lo instalado sigue intacto" '[ -f "$I/carpetaTx/x.sfz" ] && [ ! -e "$I/carpetaTx/otro.sfz" ] && sin_partes'
mv "$T/t.tar.xz.bueno" "$T/srv/t.tar.xz"                 # origen sano otra vez

# 5) tar de otro commit servido como el fijado: error, se borra, no se instala
git -C "$T/repoA" archive --format=tar.gz --prefix="repoA-$C1/" "$C1" -o "$T/codeload/repoA/tar.gz/$C2"
echo "tar|ta|repoA|$C2|" > "$PIANO_ORIGENES"
correr ta
comprobar "5: commit distinto dentro del archivo: error" '[ "$RC" -ne 0 ] && grep -q "no del fijado" <<<"$SALIDA"'
comprobar "5: se borra y lo instalado sigue" '[ ! -e "$D/repoA-$C2.tar.gz" ] && grep -q "^<region> sample=a.wav$" "$I/ta/Piano A.sfz" && sin_partes'

# 6) Archivo dañado (el commit se lee, pero no se puede extraer): error sin dejar nada a medias, y la descarga se
#    borra (si no, cada intento volvería a fallar con el mismo archivo)
head -c 20000 "$D/repoA-$C1.tar.gz" > "$T/codeload/repoA/tar.gz/$C1"; rm -f "$D/repoA-$C1.tar.gz"
comprobar "6: (preparación) el archivo truncado conserva el commit" \
    '[ "$(gzip -dc "$T/codeload/repoA/tar.gz/$C1" 2>/dev/null | git get-tar-commit-id)" = "$C1" ]'
echo "tar|ta|repoA|$C1|" > "$PIANO_ORIGENES"
correr --forzar ta
comprobar "6: archivo truncado: error, nada a medias, lo instalado sigue" \
    '[ "$RC" -ne 0 ] && grep -q "dañado" <<<"$SALIDA" && sin_partes && [ -f "$I/ta/Piano A.sfz" ]'
comprobar "6: la descarga dañada se borra" '[ ! -e "$D/repoA-$C1.tar.gz" ]'
git -C "$T/repoA" archive --format=tar.gz --prefix="repoA-$C1/" "$C1" -o "$T/codeload/repoA/tar.gz/$C1"   # origen sano otra vez

# 7) Rama de git que ya no apunta al commit fijado: error, lo instalado sigue
echo "git|gi|file://$T/big|sfz@$C1:A/uno|" > "$PIANO_ORIGENES"
correr gi
comprobar "7: git en otro commit: error" '[ "$RC" -ne 0 ] && grep -q "no en el commit fijado" <<<"$SALIDA"'
comprobar "7: lo instalado sigue y sin restos" '[ -f "$I/gi/B/dos/i.sfz" ] && sin_partes'

# 8) Falla la generación de las cuerdas: error y vsco2 sigue como estaba
origenes; touch "$T/romper-cuerdas"
correr --forzar vsco2
comprobar "8: si no se puede generar el ensemble: error, vsco2 intacto, sin restos" \
    '[ "$RC" -ne 0 ] && grep -q "ensemble de cuerdas" <<<"$SALIDA" && [ -f "$I/vsco2/ensemble-falso.sfz" ] && sin_partes'
rm -f "$T/romper-cuerdas"

# 9) Sin 7z: pedido a propósito es error (con el paquete a instalar); en «todos», se omite con aviso
if [ "$HAY_7Z" = 1 ]; then
    mkdir -p "$T/sin7z"
    for f in /usr/local/bin/* /usr/bin/* /bin/*; do
        n="$(basename "$f")"; [ "$n" = 7z ] || [ -e "$T/sin7z/$n" ] || ln -s "$f" "$T/sin7z/$n"
    done
    SALIDA="$(PATH="$T/sin7z" bash "$T/bin/descargar-instrumentos.sh" --forzar sz 2>&1)"; RC=$?
    comprobar "9: sin 7z, pedirlo es error y dice qué instalar" '[ "$RC" -ne 0 ] && grep -q "p7zip-full" <<<"$SALIDA"'
    SALIDA="$(PATH="$T/sin7z" bash "$T/bin/descargar-instrumentos.sh" --forzar 2>&1)"; RC=$?
    comprobar "9: sin 7z, en «todos» se omite con aviso y lo demás se instala" \
        '[ "$RC" -eq 0 ] && grep -q "Omitidos (falta 7z): sz" <<<"$SALIDA" && [ -f "$I/ta/Piano A.sfz" ]'
else
    echo "(sin 7z en este sistema: se omiten las pruebas de 7z)"
fi

# 12) Conexión que se cuelga (visto en la instalación desde cero: 70 min parada a 0 KB/s). Servidor HTTP local que
#     entrega la mitad y se cuelga en la primera petición; con rangos, la siguiente petición reanuda (206); sin rangos,
#     se descarga de nuevo desde el principio. Umbrales cortos para la prueba.
cat > "$T/servidor.py" <<'EOF'
import http.server, os, sys, time
datos = open(sys.argv[1], "rb").read()
registro, modo = sys.argv[2], sys.argv[3]
con_rangos = modo == "con-rangos"
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def do_GET(self):
        with open(registro, "a") as f:
            f.write((self.headers.get("Range") or "-") + "\n")
        with open(registro) as f:
            n = len(f.read().splitlines())
        rango = self.headers.get("Range")
        if n == 1 or modo == "siempre-colgado":      # la primera (o todas): la mitad y se cuelga
            self.send_response(200); self.send_header("Content-Length", str(len(datos))); self.end_headers()
            self.wfile.write(datos[:len(datos) // 2]); self.wfile.flush()
            time.sleep(60)
            return
        if rango and con_rangos:
            ini = int(rango.split("=")[1].split("-")[0])
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {ini}-{len(datos) - 1}/{len(datos)}")
            self.send_header("Content-Length", str(len(datos) - ini)); self.end_headers()
            self.wfile.write(datos[ini:])
        else:
            self.send_response(200); self.send_header("Content-Length", str(len(datos))); self.end_headers()
            self.wfile.write(datos)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
print(srv.server_address[1], flush=True)
srv.serve_forever()
EOF
mkdir -p "$T/fuente-lenta/Lento"; head -c 400000 /dev/urandom > "$T/fuente-lenta/Lento/a.wav"
echo "<region> sample=a.wav" > "$T/fuente-lenta/Lento/l.sfz"
tar -cJf "$T/lento.tar.xz" -C "$T/fuente-lenta" Lento
SHA_L="$(sha256sum "$T/lento.tar.xz" | cut -d' ' -f1)"
for modo in con-rangos sin-rangos siempre-colgado; do
    rm -rf "$T/peticiones-$modo" "$D/lento.tar.xz" "$D/lento.tar.xz.part" "$I/lento"
    python3 "$T/servidor.py" "$T/lento.tar.xz" "$T/peticiones-$modo" "$modo" > "$T/puerto-$modo" &
    SRV=$!
    for _ in $(seq 50); do [ -s "$T/puerto-$modo" ] && break; sleep 0.1; done
    echo "txz|lento|http://127.0.0.1:$(cat "$T/puerto-$modo")/lento.tar.xz|$SHA_L|" > "$PIANO_ORIGENES"
    t0=$(date +%s)
    SALIDA="$(PIANO_CURL_VELOCIDAD_MIN=1000 PIANO_CURL_ESPERA_S=2 PIANO_CURL_REINTENTOS=3 PIANO_CURL_PAUSA_S=0 \
              bash "$T/bin/descargar-instrumentos.sh" lento 2>&1)"; RC=$?
    dur=$(( $(date +%s) - t0 ))
    kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null
    if [ "$modo" = siempre-colgado ]; then
        comprobar "12 (siempre-colgado): tras los intentos, error claro en tiempo acotado ($dur s)" \
            '[ "$RC" -ne 0 ] && [ "$dur" -lt 40 ] && grep -q "tras 3 intentos" <<<"$SALIDA"'
        comprobar "12 (siempre-colgado): conserva lo bajado (.part) para continuar después" '[ -s "$D/lento.tar.xz.part" ]'
        continue
    fi
    comprobar "12 ($modo): la descarga colgada no espera para siempre ($dur s) y termina bien" \
        '[ "$RC" -eq 0 ] && [ "$dur" -lt 40 ] && [ -f "$I/lento/l.sfz" ] || { echo "$SALIDA" | tail -5; false; }'
    if [ "$modo" = con-rangos ]; then
        comprobar "12 (con-rangos): el reintento reanuda desde lo bajado (pide un rango)" \
            'grep -q "^bytes=[1-9][0-9]*-$" "$T/peticiones-$modo" && grep -q "reanudando desde" <<<"$SALIDA"'
    else
        comprobar "12 (sin-rangos): no puede reanudar, avisa y baja de nuevo entera" \
            'grep -q "no admite reanudar" <<<"$SALIDA" && [ "$(grep -c . "$T/peticiones-$modo")" -ge 3 ]'
    fi
done
# Y una descarga a medias de una ejecución anterior (.part) se reanuda al volver a ejecutar
rm -rf "$I/lento" "$D/lento.tar.xz"; head -c 100000 "$T/lento.tar.xz" > "$D/lento.tar.xz.part"
echo "txz|lento|file://$T/lento.tar.xz|$SHA_L|" > "$PIANO_ORIGENES"
correr lento
comprobar "12: un .part de una ejecución anterior se reanuda (y el SHA-256 confirma el resultado)" \
    '[ "$RC" -eq 0 ] && grep -q "reanudando desde" <<<"$SALIDA" && [ -f "$I/lento/l.sfz" ]'
origenes

# 13) git con cortes de red: un git FALSO falla la primera vez que se pide clone y la primera reset (bajar los
#     archivos); el script reintenta y termina. Si el corte es permanente, error claro sin restos.
mkdir -p "$T/shim-git" "$T/estado-git"
cat > "$T/shim-git/git" <<'EOF'
#!/bin/bash
for a in "$@"; do
    case "$a" in
        clone|reset)
            if [ "${SHIM_GIT_SIEMPRE:-}" = "$a" ] || [ ! -e "$SHIM_GIT_DIR/$a" ]; then
                touch "$SHIM_GIT_DIR/$a"; echo "fatal: corte de red simulado ($a)" >&2; exit 128
            fi
            break ;;
    esac
done
exec /usr/bin/git "$@"
EOF
chmod +x "$T/shim-git/git"
echo "git|gi|file://$T/big|sfz@$CB:A/uno;B/dos|" > "$PIANO_ORIGENES"
rm -rf "$I/gi"
SALIDA="$(SHIM_GIT_DIR="$T/estado-git" PATH="$T/shim-git:$PATH" PIANO_CURL_PAUSA_S=0 PIANO_CURL_REINTENTOS=3 \
          bash "$T/bin/descargar-instrumentos.sh" gi 2>&1)"; RC=$?
comprobar "13: un corte al clonar y otro al bajar los archivos: reintenta y termina" \
    '[ "$RC" -eq 0 ] && grep -q "clon interrumpido" <<<"$SALIDA" && grep -q "descarga de archivos interrumpida" <<<"$SALIDA" || { echo "$SALIDA" | tail -5; false; }'
comprobar "13: y el resultado está completo (las carpetas pedidas, del commit fijado)" \
    '[ -f "$I/gi/A/uno/i.sfz" ] && [ -f "$I/gi/B/dos/i.sfz" ] && [ ! -e "$I/gi/C" ] && sin_partes'
SALIDA="$(SHIM_GIT_DIR="$T/estado-git" SHIM_GIT_SIEMPRE=clone PATH="$T/shim-git:$PATH" PIANO_CURL_PAUSA_S=0 \
          PIANO_CURL_REINTENTOS=3 bash "$T/bin/descargar-instrumentos.sh" --forzar gi 2>&1)"; RC=$?
comprobar "13: corte permanente: error tras 3 intentos, sin restos y lo instalado sigue" \
    '[ "$RC" -ne 0 ] && grep -q "no se pudo clonar .* tras 3 intentos" <<<"$SALIDA" && sin_partes && [ -f "$I/gi/A/uno/i.sfz" ]'
origenes

# 14) Actualizar no reinstala lo que ya está (mismo origen fijado, según el manifiesto); --forzar sí
origenes
correr
touch "$I/ta/marca-de-prueba" "$I/carpetaTx/marca-de-prueba" "$I/gi/marca-de-prueba"
correr
comprobar "14: otra ejecución salta todo lo instalado (sin descargar ni extraer)" \
    '[ "$RC" -eq 0 ] && [ "$(grep -c "ya instalado" <<<"$SALIDA")" -ge 4 ] && [ -e "$I/ta/marca-de-prueba" ] && [ -e "$I/carpetaTx/marca-de-prueba" ] && [ -e "$I/gi/marca-de-prueba" ]'
correr --forzar ta
comprobar "14: --forzar reinstala (la carpeta se reemplaza)" '[ "$RC" -eq 0 ] && [ ! -e "$I/ta/marca-de-prueba" ] && [ -f "$I/ta/Piano A.sfz" ]'
rm -rf "$I/carpetaTx"
correr tx
comprobar "14: si falta la carpeta, se instala aunque el manifiesto la registre" '[ "$RC" -eq 0 ] && [ -f "$I/carpetaTx/x.sfz" ]'

# 10) Un id que no existe
correr no-existe
comprobar "10: id desconocido: código 2 y mensaje" '[ "$RC" -eq 2 ] && grep -q "no hay ningún instrumento" <<<"$SALIDA"'

# 11) Los orígenes reales: todos fijados (commit de 40 cifras o SHA-256) y cubren cada carpeta del catálogo
python3 - "$DIR" <<'EOF' && ok "11: orígenes reales fijados y cubren todo el catálogo salvo el Softify" || fallo "11: orígenes reales"
import json, re, subprocess, sys
d = sys.argv[1]
texto = open(f"{d}/descargar-instrumentos.sh", encoding="utf-8").read()
bloque = texto.split('ORIGENES="', 1)[1].split('"\n', 1)[0]
carpetas = set()
for linea in bloque.strip().splitlines():
    tipo, iid, origen, fijado, carpeta = linea.split("|")
    if tipo == "tar":
        assert re.fullmatch(r"[0-9a-f]{40}", fijado), linea
    elif tipo in ("txz", "7z"):
        assert re.fullmatch(r"[0-9a-f]{64}", fijado) and origen.startswith("https://"), linea
    elif tipo == "git":
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}:.+", fijado) and origen.startswith("https://"), linea
    else:
        raise AssertionError(linea)
    carpetas.add(carpeta or iid)
cat = json.load(open(f"{d}/instrumentos.json", encoding="utf-8"))
necesarias = {i["sfz"].split("/")[0] for i in cat["instrumentos"]} - {"softify"}
faltan = necesarias - carpetas
assert not faltan, f"sin origen de descarga: {faltan}"
EOF

echo
[ "$FALLOS" -eq 0 ] && echo "TODAS LAS PRUEBAS PASAN" || { echo "$FALLOS FALLO(S)"; exit 1; }
