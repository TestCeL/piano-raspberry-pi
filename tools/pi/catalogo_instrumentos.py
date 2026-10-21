#!/usr/bin/env python3
"""Catálogo de instrumentos del piano (instrumentos.json): validación, disponibilidad y órdenes para sfizz_jack.

Uso (para el motor y para consultar):
  catalogo_instrumentos.py elegir [PREFERIDO]   -> "id<TAB>ruta.sfz<TAB>voces" del preferido si está disponible,
                                                   si no el primero disponible (código 1 si no hay ninguno)
  catalogo_instrumentos.py lista                -> tabla: id, disponible, ganancia, nombre
  catalogo_instrumentos.py creditos             -> autor, licencia, uso y fuente de cada instrumento
Opciones: --catalogo JSON (por defecto, el de esta carpeta), --base DIR (por defecto ~/piano/instrumentos o
$PIANO_INSTRUMENTOS).
"""
import argparse
import json
import os
import re
import sys
from dataclasses import dataclass

RUTA_CATALOGO = os.environ.get("PIANO_CATALOGO",
                               os.path.join(os.path.dirname(os.path.abspath(__file__)), "instrumentos.json"))
BASE_INSTRUMENTOS = os.environ.get("PIANO_INSTRUMENTOS", os.path.expanduser("~/piano/instrumentos"))
# Categorías (tipo) en el orden del menú de la interfaz (F9), con su nombre visible.
CATEGORIAS = (("cola", "Pianos de cola"), ("vertical", "Pianos verticales"), ("electrico", "Pianos eléctricos"),
              ("organo", "Órganos"), ("clavecin", "Clavecín"), ("cuerdas", "Cuerdas"), ("percusion", "Percusión"),
              ("viento", "Viento"))
TIPOS = tuple(t for t, _ in CATEGORIAS)
NOMBRE_CATEGORIA = dict(CATEGORIAS)
VOCES_DEFECTO = 32
CARGA_DEFECTO_S = 3.0        # estimación del tiempo de carga si el catálogo no la da (el enrutador la aprende)
GANANCIA_MIN, GANANCIA_MAX = -30.0, 24.0
ID_VALIDO = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")
NOMBRE_MAX = 28              # cabe en el panel SONIDO de la interfaz
USO_MAX = 40                 # condiciones en palabras simples: caben en dos filas del panel de la interfaz
DETALLE_MAX = 100            # autor, licencia y fuente: el menú F9 los muestra enteros en una fila


@dataclass(frozen=True)
class Instrumento:
    id: str
    nombre: str
    tipo: str
    sfz: str                 # ruta absoluta
    ganancia_db: float
    controles: tuple         # ((cc, valor), ...) en orden de cc
    voces: int
    autor: str
    licencia: str
    fuente: str
    uso: str                             # condiciones de la licencia en palabras simples («libre; citar al autor»)
    carga_s: float = CARGA_DEFECTO_S     # tiempo de carga estimado (barra de progreso de la interfaz)
    transposicion: int = 0               # semitonos que se suman a las notas enviadas (corrige un mapeo desplazado)
    restringido: bool = False            # hay una restricción más allá de citar al autor (la interfaz la resalta)


def _texto(d, clave, i, obligatorio=True):
    v = d.get(clave, "")
    if not isinstance(v, str) or (obligatorio and not v.strip()):
        raise ValueError(f"instrumento {i}: '{clave}' debe ser un texto no vacío")
    return v.strip()


def validar(datos, base=BASE_INSTRUMENTOS):
    """Convierte el JSON del catálogo en una lista de Instrumento. ValueError con el motivo si algo no cuadra."""
    if not isinstance(datos, dict) or not isinstance(datos.get("instrumentos"), list) or not datos["instrumentos"]:
        raise ValueError("el catálogo debe tener una lista 'instrumentos' no vacía")
    lista, vistos = [], set()
    for i, d in enumerate(datos["instrumentos"]):
        if not isinstance(d, dict):
            raise ValueError(f"instrumento {i}: debe ser un objeto")
        iid = _texto(d, "id", i)
        if not ID_VALIDO.match(iid):
            raise ValueError(f"instrumento {i}: id inválido '{iid}' (minúsculas, cifras y guiones)")
        if iid in vistos:
            raise ValueError(f"id repetido: {iid}")
        vistos.add(iid)
        nombre = _texto(d, "nombre", iid)
        if len(nombre) > NOMBRE_MAX:
            raise ValueError(f"{iid}: nombre de más de {NOMBRE_MAX} caracteres")
        tipo = _texto(d, "tipo", iid)
        if tipo not in TIPOS:
            raise ValueError(f"{iid}: tipo '{tipo}' no es uno de {TIPOS}")
        sfz = _texto(d, "sfz", iid)
        if os.path.isabs(sfz) or ".." in sfz.replace("\\", "/").split("/") or '"' in sfz or "\n" in sfz:
            raise ValueError(f"{iid}: 'sfz' debe ser una ruta relativa dentro de la carpeta de instrumentos")
        g = d.get("ganancia_db")
        if isinstance(g, bool) or not isinstance(g, (int, float)) or not GANANCIA_MIN <= g <= GANANCIA_MAX:
            raise ValueError(f"{iid}: ganancia_db debe ser un número entre {GANANCIA_MIN} y {GANANCIA_MAX}")
        ctl = d.get("controles", {})
        if not isinstance(ctl, dict):
            raise ValueError(f"{iid}: 'controles' debe ser un objeto {{\"cc\": valor}}")
        controles = []
        for k, v in ctl.items():
            if not (isinstance(k, str) and k.isdigit() and 0 <= int(k) <= 127
                    and isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 127):
                raise ValueError(f"{iid}: control inválido {k}={v} (CC y valor 0..127)")
            controles.append((int(k), v))
        voces = d.get("voces", VOCES_DEFECTO)
        if isinstance(voces, bool) or not isinstance(voces, int) or not 8 <= voces <= 256:
            raise ValueError(f"{iid}: voces debe ser un entero entre 8 y 256")
        carga = d.get("carga_s", CARGA_DEFECTO_S)
        if isinstance(carga, bool) or not isinstance(carga, (int, float)) or not 0.1 <= carga <= 300:
            raise ValueError(f"{iid}: carga_s debe ser un número entre 0,1 y 300 segundos")
        transp = d.get("transposicion", 0)
        if isinstance(transp, bool) or not isinstance(transp, int) or not -24 <= transp <= 24:
            raise ValueError(f"{iid}: transposicion debe ser un entero de semitonos entre -24 y 24")
        detalle = {clave: _texto(d, clave, iid) for clave in ("autor", "licencia", "fuente", "uso")}
        for clave, texto in detalle.items():
            maximo = USO_MAX if clave == "uso" else DETALLE_MAX
            if len(texto) > maximo:
                raise ValueError(f"{iid}: '{clave}' de más de {maximo} caracteres")
        restringido = d.get("restringido", False)
        if not isinstance(restringido, bool):
            raise ValueError(f"{iid}: restringido debe ser true o false")
        lista.append(Instrumento(id=iid, nombre=nombre, tipo=tipo, sfz=os.path.join(base, sfz), ganancia_db=float(g),
                                 controles=tuple(sorted(controles)), voces=voces, carga_s=float(carga),
                                 transposicion=transp, restringido=restringido, **detalle))
    return lista


def cargar(ruta=RUTA_CATALOGO, base=BASE_INSTRUMENTOS):
    with open(ruta, encoding="utf-8") as f:
        return validar(json.load(f), base)


def disponibles(instrumentos):
    """Los que tienen su archivo SFZ en disco (un instrumento borrado o sin descargar no se ofrece)."""
    return [i for i in instrumentos if os.path.isfile(i.sfz)]


def buscar(instrumentos, iid):
    return next((i for i in instrumentos if i.id == iid), None)


def vecino(instrumentos, iid, paso):
    """Siguiente (paso 1) o anterior (paso -1), circular. Si iid no está, el primero."""
    if not instrumentos:
        return None
    ids = [i.id for i in instrumentos]
    if iid not in ids:
        return instrumentos[0]
    return instrumentos[(ids.index(iid) + paso) % len(ids)]


def elegir(instrumentos, preferido):
    """El preferido si está entre los dados; si no, el primero. None si la lista está vacía."""
    return buscar(instrumentos, preferido) or (instrumentos[0] if instrumentos else None)


def ordenes_sfizz(inst, cargar_sfz=True):
    """Órdenes para la entrada estándar de sfizz_jack (parche 0002) que dejan sonando el instrumento con su
    voces, controles y ganancia. Los controles se envían DESPUÉS de cargar porque cada carga restablece los
    valores por defecto del SFZ. set_volume va la última: su confirmación indica que todo está aplicado."""
    ordenes = [f'load_instrument "{inst.sfz}"'] if cargar_sfz else []
    ordenes.append(f"set_voices {inst.voces}")
    ordenes += [f"set_cc {cc} {v}" for cc, v in inst.controles]
    ordenes.append(f"set_volume {inst.ganancia_db:g}")
    return ordenes


def main(argv=None):
    ap = argparse.ArgumentParser(description="Catálogo de instrumentos del piano.")
    ap.add_argument("--catalogo", default=RUTA_CATALOGO)
    ap.add_argument("--base", default=BASE_INSTRUMENTOS)
    ap.add_argument("accion", choices=("elegir", "lista", "creditos"))
    ap.add_argument("preferido", nargs="?", default="")
    args = ap.parse_args(argv)
    try:
        todos = cargar(args.catalogo, args.base)
    except (OSError, ValueError) as e:
        print(f"ERROR: catálogo {args.catalogo}: {e}", file=sys.stderr)
        return 2
    hay = disponibles(todos)
    if args.accion == "elegir":
        inst = elegir(hay, args.preferido)
        if inst is None:
            print("ERROR: no hay ningún instrumento disponible", file=sys.stderr)
            return 1
        print(f"{inst.id}\t{inst.sfz}\t{inst.voces}")
    elif args.accion == "lista":
        for i in todos:
            print(f"{i.id:12} {'sí' if i in hay else 'NO':3} {i.ganancia_db:+6.1f} dB  {i.nombre}")
    else:
        for i in todos:
            print(f"{i.nombre}\n  Autor: {i.autor}\n  Licencia: {i.licencia}\n"
                  f"  Uso: {i.uso}{' (RESTRINGIDO)' if i.restringido else ''}\n  Fuente: {i.fuente}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
