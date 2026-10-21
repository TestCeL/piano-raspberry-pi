"""Pruebas de los créditos del proyecto (CREDITOS.md y CREDITS.md, generados desde el catálogo de instrumentos)."""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import catalogo_instrumentos as cat  # noqa: E402
import generar_creditos as gc  # noqa: E402
import teclado_piano as tp  # noqa: E402

RUTA_REAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instrumentos.json")


class TestCreditos(unittest.TestCase):
    def setUp(self):
        self.lista = cat.cargar(RUTA_REAL, "/")
        self.archivos = gc.generar(self.lista)

    def test_autor_y_ayuda_de_claude_en_los_dos_idiomas(self):
        es, en = self.archivos["CREDITOS.md"], self.archivos["CREDITS.md"]
        self.assertIn("Creado por **Reinaldo Johnson Espinoza**", es)
        self.assertIn("con la ayuda de **Claude** (Anthropic)", es)
        self.assertIn("Created by **Reinaldo Johnson Espinoza**", en)
        self.assertIn("with the help of **Claude** (Anthropic)", en)
        self.assertIn("[CREDITS.md](CREDITS.md)", es, "cada uno enlaza al otro idioma")
        self.assertIn("[CREDITOS.md](CREDITOS.md)", en)

    def test_el_mismo_nombre_en_la_interfaz(self):
        self.assertIn(f"creado por {gc.AUTOR}, con la ayuda de Claude", tp.CREDITO_PROYECTO)

    def test_todos_los_sonidos_con_sus_datos(self):
        es, en = self.archivos["CREDITOS.md"], self.archivos["CREDITS.md"]
        for i in self.lista:
            with self.subTest(i.id):
                fila_es = next(l for l in es.splitlines() if l.startswith(f"| {i.nombre} |"))
                for dato in (i.autor, i.licencia, cat.NOMBRE_CATEGORIA[i.tipo], f"<{i.fuente}>"):
                    self.assertIn(dato, fila_es)
                fila_en = next(l for l in en.splitlines() if l.startswith(f"| {gc.en(i.nombre)} |"))
                for dato in (gc.en(i.autor), gc.en(i.licencia), gc.CATEGORIA_EN[i.tipo], f"<{i.fuente}>"):
                    self.assertIn(dato, fila_en)
                self.assertEqual(f"**{i.uso}**" in fila_es, i.restringido, "las restricciones, en negrita")
                self.assertEqual(f"**{gc.en(i.uso)}**" in fila_en, i.restringido)
        self.assertEqual(sum(l.startswith("| ") for l in es.splitlines()), 1 + 8 + 1 + len(self.lista),
                         "tabla de programas (cabecera + 8) y tabla de sonidos (cabecera + uno por sonido)")

    def test_el_ingles_no_queda_en_espanol(self):
        tabla = self.archivos["CREDITS.md"].split("## Sounds")[1].split("## Sources")[0]
        for palabra in ("suave", "libre", "muestras", "Órgano", "Cuerdas", "Clavecín", "grabación", "Dominio"):
            self.assertNotIn(palabra, tabla)

    def test_falta_una_traduccion(self):
        with self.assertRaises(ValueError) as cm:
            gc.en("Piano de fieltro")
        self.assertIn("falta la traducción", str(cm.exception))
        for texto in ("Órgano nuevo", "Uso libre", "grabado de algo", "Sonido raro"):
            with self.subTest(texto):
                self.assertRaises(ValueError, gc.en, texto)
        for propio in ("Hohner Pianet T", "CC BY 3.0", "Versilian Studios (VCSL)", "Greg Sullivan (SFZ: kinwie)"):
            self.assertEqual(gc.en(propio), propio, "nombres propios y licencias estándar no se traducen")

    def test_sin_traducciones_sobrantes(self):
        usadas = {t for i in self.lista for t in (i.nombre, i.autor, i.licencia, i.uso)}
        self.assertEqual(set(gc.TRADUCCION) - usadas, set(), "cada traducción corresponde a un texto del catálogo")

    def test_escribir_y_comprobar(self):
        with tempfile.TemporaryDirectory() as d:
            def correr(*args):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
                    return gc.main(["--catalogo", RUTA_REAL, "--raiz", d, *args]), err.getvalue()
            self.assertEqual(correr("--comprobar")[0], 1, "sin archivos: no están al día")
            self.assertEqual(correr()[0], 0)
            self.assertEqual(correr("--comprobar"), (0, ""))
            with open(os.path.join(d, "CREDITS.md"), "a", encoding="utf-8") as f:
                f.write("cambio a mano\n")
            rc, err = correr("--comprobar")
            self.assertEqual(rc, 1)
            self.assertIn("CREDITS.md", err)
            self.assertNotIn("CREDITOS.md", err)

    def test_los_del_repositorio_estan_al_dia(self):
        """En el repositorio (no en la copia de herramientas de la Pi, que no lleva la raíz)."""
        if not os.path.isfile(os.path.join(gc.RAIZ, "LICENSE")):
            self.skipTest("fuera del repositorio")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(gc.main(["--comprobar"]), 0, "ejecutar generar_creditos.py tras cambiar el catálogo")
        with open(os.path.join(gc.RAIZ, "LICENSE"), encoding="utf-8") as f:
            self.assertIn(gc.AUTOR, f.read())


if __name__ == "__main__":
    unittest.main()
