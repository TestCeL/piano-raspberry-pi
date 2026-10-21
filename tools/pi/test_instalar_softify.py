"""Pruebas de instalar_softify.py con zips de prueba (sin el Softify real)."""
import hashlib
import io
import os
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import instalar_softify as s  # noqa: E402


def crear_zip(ruta, entradas):
    with zipfile.ZipFile(ruta, "w") as z:
        for nombre, datos in entradas.items():
            z.writestr(nombre, datos)
    with open(ruta, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


NORMAL = {"SFZ/Softify Piano Vol 1 V1.1.sfz": "<region> sample=Samples/a.wav\n", "SFZ/Samples/a.wav": b"\x00" * 3000,
          "Readme.txt": "lee esto", "Kontakt/Softify.nki": b"kontakt", "Kontakt/Samples/a.ncw": b"x"}


class TestInstalarSoftify(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.zip = os.path.join(self.d.name, "Softify Piano Vol 1 v1.1.zip")
        self.sha = crear_zip(self.zip, NORMAL)
        self.destino = os.path.join(self.d.name, "inst")
        self.sf = os.path.join(self.destino, "softify")

    def tearDown(self):
        self.d.cleanup()

    def instalar(self, **kw):
        return s.instalar(self.zip, self.destino, sha_esperado=kw.pop("sha", self.sha), salida=lambda *_: None, **kw)

    def archivos(self):
        return sorted(os.path.relpath(os.path.join(r, a), self.sf) for r, _, l in os.walk(self.sf) for a in l)

    def test_solo_la_version_sfz_y_el_readme(self):
        self.assertEqual(self.instalar(), 3)
        self.assertEqual(self.archivos(), sorted(["Softify Piano Vol 1 V1.1.sfz", os.path.join("Samples", "a.wav"),
                                                  "Readme.txt"]), "sin la parte de Kontakt; SFZ/ sin el prefijo")
        with open(os.path.join(self.sf, "Samples", "a.wav"), "rb") as f:
            self.assertEqual(f.read(), b"\x00" * 3000)
        with open(os.path.join(self.destino, "MANIFIESTO-descargas.txt"), encoding="utf-8") as f:
            linea = f.read().strip()
        self.assertRegex(linea, rf"^softify pianobook:Softify_Piano_Vol_1_v1.1.zip \d+ {self.sha} \d{{4}}-")
        self.assertFalse(os.path.exists(self.sf + ".part"))

    def test_reemplaza_y_conserva_el_resto_del_manifiesto(self):
        os.makedirs(self.sf)
        open(os.path.join(self.sf, "viejo.txt"), "w").close()
        with open(os.path.join(self.destino, "MANIFIESTO-descargas.txt"), "w", encoding="utf-8") as f:
            f.write("salamander freepats:x 1 abc 2026\nsoftify pianobook:viejo 1 def 2026\n")
        self.instalar()
        self.assertNotIn("viejo.txt", self.archivos())
        with open(os.path.join(self.destino, "MANIFIESTO-descargas.txt"), encoding="utf-8") as f:
            lineas = f.read().splitlines()
        self.assertEqual(lineas[0], "salamander freepats:x 1 abc 2026")
        self.assertEqual(sum(l.startswith("softify ") for l in lineas), 1)

    def test_otra_version_del_zip(self):
        os.makedirs(self.sf)
        open(os.path.join(self.sf, "instalado.txt"), "w").close()
        with self.assertRaises(ValueError) as cm:
            self.instalar(sha="0" * 64)
        self.assertIn("--otra-version", str(cm.exception))
        self.assertEqual(self.archivos(), ["instalado.txt"], "no toca lo instalado")
        avisos = []
        s.instalar(self.zip, self.destino, sha_esperado="0" * 64, otra_version=True, salida=avisos.append)
        self.assertIn("AVISO", avisos[0])
        self.assertIn("Readme.txt", self.archivos())

    def test_rutas_sospechosas(self):
        for nombre in ("SFZ/../../fuera.txt", "SFZ/a\\..\\b.txt"):
            with self.subTest(nombre):
                sha = crear_zip(self.zip, dict(NORMAL, **{nombre: "x"}))
                with self.assertRaises(ValueError) as cm:
                    self.instalar(sha=sha)
                self.assertIn("sospechosa", str(cm.exception))
                self.assertFalse(os.path.exists(os.path.join(self.d.name, "fuera.txt")))
                self.assertFalse(os.path.exists(self.sf + ".part"), "sin restos")

    def test_sin_version_sfz(self):
        sha = crear_zip(self.zip, {"Kontakt/x.nki": "x", "Readme.txt": "x"})
        with self.assertRaises(ValueError) as cm:
            self.instalar(sha=sha)
        self.assertIn("versión SFZ", str(cm.exception))

    def test_linea_de_ordenes(self):
        def correr(*args):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = s.main(list(args))
            return rc, out.getvalue() + err.getvalue()
        rc, texto = correr()
        self.assertEqual(rc, 2)
        self.assertIn("pianobook.co.uk", texto, "dice dónde descargarlo")
        rc, texto = correr(os.path.join(self.d.name, "no-existe.zip"))
        self.assertEqual(rc, 2)
        os.environ["PIANO_INSTRUMENTOS"] = self.destino
        try:
            rc, texto = correr(self.zip)
            self.assertEqual(rc, 1, "el zip de prueba no es el real: SHA-256 distinto")
            self.assertIn("--otra-version", texto)
            rc, texto = correr(self.zip, "--otra-version")
            self.assertEqual(rc, 0, texto)
            self.assertIn("3 archivos verificados", texto)
        finally:
            del os.environ["PIANO_INSTRUMENTOS"]

    def test_el_sfz_del_catalogo(self):
        import json
        ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instrumentos.json")
        with open(ruta, encoding="utf-8") as f:
            sfz = next(i["sfz"] for i in json.load(f)["instrumentos"] if i["id"] == "softify")
        self.assertEqual(sfz, f"{s.CARPETA}/{s.SFZ}", "el catálogo apunta a lo que instala este script")


if __name__ == "__main__":
    unittest.main()
