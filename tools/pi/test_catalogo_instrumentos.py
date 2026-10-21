"""Pruebas del catálogo de instrumentos: el catálogo real, validación, disponibilidad, navegación y órdenes."""
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import catalogo_instrumentos as c  # noqa: E402

RUTA_REAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instrumentos.json")
BASICO = {"instrumentos": [
    {"id": "a", "nombre": "Piano A", "tipo": "cola", "sfz": "a/a.sfz", "ganancia_db": 0,
     "autor": "X", "licencia": "CC0", "uso": "libre, sin condiciones", "fuente": "http://a"},
    {"id": "b", "nombre": "Piano B", "tipo": "electrico", "sfz": "b dir/b b.sfz", "ganancia_db": -3.5,
     "controles": {"101": 0, "77": 10}, "voces": 24, "autor": "Y", "licencia": "CC BY-NC",
     "uso": "solo uso no comercial", "restringido": True, "fuente": "http://b"},
    {"id": "c", "nombre": "Piano C", "tipo": "vertical", "sfz": "c/c.sfz", "ganancia_db": 6,
     "autor": "Z", "licencia": "CC0", "uso": "libre, sin condiciones", "fuente": "http://c"},
]}


class TestCatalogoReal(unittest.TestCase):
    def test_valida_y_contiene_los_sonidos_elegidos(self):
        lista = c.cargar(RUTA_REAL, "/base")
        self.assertEqual([i.id for i in lista],
                         ["salamander", "headroom", "maestro", "splendid", "softify", "upright", "osiris",
                          "rhodes", "wurlitzer", "cp80", "pianet", "fm-piano",
                          "hammond-drawbar", "hammond-rock", "hammond-percusivo", "iglesia", "clavecin",
                          "cuerdas", "arpa", "vibrafono", "marimba", "saxo"],
                         "los 10 de la fase 07 y los 12 de la fase 08, agrupados por categoría")
        self.assertEqual(lista[0].ganancia_db, 0.0, "el Salamander es la referencia de nivel")
        self.assertTrue(all(i.sfz.startswith("/base" + os.sep) or i.sfz.startswith("/base/") for i in lista))
        self.assertTrue(all(i.voces == c.VOCES_DEFECTO for i in lista))

    def test_octava_corregida(self):
        """Las muestras del Piano FM y de los Hammond están grabadas una octava por debajo de su tecla (medido)."""
        lista = c.cargar(RUTA_REAL, "/base")
        corregidos = {i.id: i.transposicion for i in lista if i.transposicion}
        self.assertEqual(corregidos, {"fm-piano": 12, "hammond-drawbar": 12, "hammond-rock": 12,
                                      "hammond-percusivo": 12})

    def test_controles_que_reducen_voces(self):
        lista = c.cargar(RUTA_REAL, "/base")
        self.assertEqual(c.buscar(lista, "headroom").controles, ((77, 0),))
        self.assertEqual(c.buscar(lista, "osiris").controles, ((101, 0), (102, 0)))

    def test_la_licencia_no_comercial_esta_indicada(self):
        lista = c.cargar(RUTA_REAL, "/base")
        self.assertIn("NC", c.buscar(lista, "rhodes").licencia)
        self.assertIn("no redistribuir", c.buscar(lista, "softify").licencia)
        self.assertTrue(all(i.licencia for i in lista) and all(i.fuente for i in lista))

    def test_uso_en_palabras_simples(self):
        """Cada sonido dice sus condiciones; solo los tres con restricción (no comercial, no redistribuir, sin
        licencia estándar) van marcados para resaltarse en la interfaz."""
        lista = c.cargar(RUTA_REAL, "/base")
        self.assertEqual({i.id for i in lista if i.restringido}, {"rhodes", "softify", "maestro"})
        self.assertEqual(c.buscar(lista, "rhodes").uso, "solo uso no comercial")
        self.assertEqual(c.buscar(lista, "softify").uso, "no redistribuir las muestras")
        self.assertEqual(c.buscar(lista, "maestro").uso, "gratis; mejor no redistribuir")
        for i in lista:
            with self.subTest(i.id):
                if i.restringido:
                    continue
                esperado = "libre; citar al autor" if i.licencia.startswith("CC BY") else "libre, sin condiciones"
                self.assertEqual(i.uso, esperado, "CC BY pide citar al autor; CC0 y dominio público, nada")
                self.assertIn(i.licencia, ("CC0", "Dominio público", "CC BY 3.0", "CC BY 4.0"))

    def test_los_datos_caben_enteros(self):
        lista = c.cargar(RUTA_REAL, "/base")
        for i in lista:
            with self.subTest(i.id):
                self.assertLessEqual(len(i.uso), c.USO_MAX)
                self.assertLessEqual(max(len(i.autor), len(i.licencia), len(i.fuente)), c.DETALLE_MAX)


class TestCategorias(unittest.TestCase):
    def test_categorias_del_menu(self):
        self.assertEqual(c.TIPOS, ("cola", "vertical", "electrico", "organo", "clavecin", "cuerdas", "percusion",
                                   "viento"))
        self.assertEqual(c.NOMBRE_CATEGORIA["organo"], "Órganos")
        self.assertEqual(len(set(c.NOMBRE_CATEGORIA.values())), len(c.TIPOS), "nombres distintos")

    def test_el_catalogo_real_va_agrupado_por_categoria(self):
        """F6/F7 recorren el catálogo en orden: los de una misma categoría van juntos y en el orden del menú."""
        tipos = [i.tipo for i in c.cargar(RUTA_REAL, "/base")]
        orden = [c.TIPOS.index(t) for t in tipos]
        self.assertEqual(orden, sorted(orden))


class TestValidacion(unittest.TestCase):
    def malo(self, mutar, texto):
        d = copy.deepcopy(BASICO)
        mutar(d)
        with self.assertRaises(ValueError) as cm:
            c.validar(d, "/base")
        self.assertIn(texto, str(cm.exception))

    def test_basico(self):
        lista = c.validar(BASICO, "/base")
        b = lista[1]
        self.assertEqual(b.sfz, os.path.join("/base", "b dir/b b.sfz"))
        self.assertEqual(b.controles, ((77, 10), (101, 0)), "controles ordenados por número de CC")
        self.assertEqual((b.voces, b.ganancia_db, lista[0].voces), (24, -3.5, c.VOCES_DEFECTO))
        self.assertEqual(lista[0].carga_s, c.CARGA_DEFECTO_S, "sin dato, la estimación genérica")
        self.assertEqual(lista[0].transposicion, 0)
        self.assertEqual((lista[0].uso, lista[0].restringido), ("libre, sin condiciones", False),
                         "sin 'restringido', no hay restricción")
        self.assertEqual((b.uso, b.restringido, b.licencia), ("solo uso no comercial", True, "CC BY-NC"))

    def test_errores(self):
        casos = [
            (lambda d: d.update(instrumentos=[]), "no vacía"),
            (lambda d: d.pop("instrumentos"), "no vacía"),
            (lambda d: d["instrumentos"][1].update(id="a"), "repetido"),
            (lambda d: d["instrumentos"][0].update(id="Mayús"), "id inválido"),
            (lambda d: d["instrumentos"][0].update(tipo="sintetizador"), "tipo"),
            (lambda d: d["instrumentos"][0].update(tipo="órgano"), "tipo"),
            (lambda d: d["instrumentos"][0].update(sfz="/abs/x.sfz"), "relativa"),
            (lambda d: d["instrumentos"][0].update(sfz="../fuera.sfz"), "relativa"),
            (lambda d: d["instrumentos"][0].update(sfz='con"comilla.sfz'), "relativa"),
            (lambda d: d["instrumentos"][0].update(ganancia_db=40), "ganancia_db"),
            (lambda d: d["instrumentos"][0].update(ganancia_db=True), "ganancia_db"),
            (lambda d: d["instrumentos"][0].pop("ganancia_db"), "ganancia_db"),
            (lambda d: d["instrumentos"][0].update(controles={"128": 0}), "control inválido"),
            (lambda d: d["instrumentos"][0].update(controles={"7": 200}), "control inválido"),
            (lambda d: d["instrumentos"][0].update(controles={"x": 1}), "control inválido"),
            (lambda d: d["instrumentos"][0].update(controles=[1, 2]), "controles"),
            (lambda d: d["instrumentos"][0].update(voces=4), "voces"),
            (lambda d: d["instrumentos"][0].update(carga_s=0), "carga_s"),
            (lambda d: d["instrumentos"][0].update(carga_s="3"), "carga_s"),
            (lambda d: d["instrumentos"][0].update(carga_s=True), "carga_s"),
            (lambda d: d["instrumentos"][0].update(transposicion=30), "transposicion"),
            (lambda d: d["instrumentos"][0].update(transposicion=1.5), "transposicion"),
            (lambda d: d["instrumentos"][0].update(autor=""), "autor"),
            (lambda d: d["instrumentos"][0].pop("uso"), "'uso'"),
            (lambda d: d["instrumentos"][0].update(uso="  "), "'uso'"),
            (lambda d: d["instrumentos"][0].update(uso="x" * (c.USO_MAX + 1)), "'uso' de más de"),
            (lambda d: d["instrumentos"][0].update(autor="x" * (c.DETALLE_MAX + 1)), "'autor' de más de"),
            (lambda d: d["instrumentos"][0].update(licencia="x" * (c.DETALLE_MAX + 1)), "'licencia' de más de"),
            (lambda d: d["instrumentos"][0].update(fuente="x" * (c.DETALLE_MAX + 1)), "'fuente' de más de"),
            (lambda d: d["instrumentos"][0].update(restringido="sí"), "restringido"),
            (lambda d: d["instrumentos"][0].update(restringido=1), "restringido"),
            (lambda d: d["instrumentos"][0].update(nombre="x" * (c.NOMBRE_MAX + 1)), "nombre"),
            (lambda d: d["instrumentos"].append("texto"), "objeto"),
        ]
        for mutar, texto in casos:
            with self.subTest(texto=texto):
                self.malo(mutar, texto)


class TestUso(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.lista = c.validar(BASICO, self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def crear(self, *ids):
        for i in self.lista:
            if i.id in ids:
                os.makedirs(os.path.dirname(i.sfz), exist_ok=True)
                open(i.sfz, "w").close()

    def test_disponibles_solo_con_archivo(self):
        self.assertEqual(c.disponibles(self.lista), [])
        self.crear("a", "c")
        self.assertEqual([i.id for i in c.disponibles(self.lista)], ["a", "c"])

    def test_vecino_circular(self):
        self.assertEqual(c.vecino(self.lista, "a", 1).id, "b")
        self.assertEqual(c.vecino(self.lista, "c", 1).id, "a")
        self.assertEqual(c.vecino(self.lista, "a", -1).id, "c")
        self.assertEqual(c.vecino(self.lista, "desconocido", 1).id, "a")
        self.assertIsNone(c.vecino([], "a", 1))

    def test_elegir(self):
        self.assertEqual(c.elegir(self.lista, "b").id, "b")
        self.assertEqual(c.elegir(self.lista, "otro").id, "a")
        self.assertEqual(c.elegir(self.lista, "").id, "a")
        self.assertIsNone(c.elegir([], "a"))

    def test_ordenes_sfizz(self):
        b = c.buscar(self.lista, "b")
        self.assertEqual(c.ordenes_sfizz(b), [
            f'load_instrument "{b.sfz}"', "set_voices 24", "set_cc 77 10", "set_cc 101 0", "set_volume -3.5"])
        self.assertEqual(c.ordenes_sfizz(b, cargar_sfz=False)[0], "set_voices 24")
        self.assertEqual(c.ordenes_sfizz(c.buscar(self.lista, "c"))[-1], "set_volume 6")
        self.assertEqual(c.ordenes_sfizz(c.buscar(self.lista, "a"), False), ["set_voices 32", "set_volume 0"])


class TestLineaDeOrdenes(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.cat = os.path.join(self.dir.name, "cat.json")
        with open(self.cat, "w", encoding="utf-8") as f:
            json.dump(BASICO, f)
        self.base = os.path.join(self.dir.name, "inst")
        for i in c.validar(BASICO, self.base):
            if i.id in ("b", "c"):
                os.makedirs(os.path.dirname(i.sfz), exist_ok=True)
                open(i.sfz, "w").close()

    def tearDown(self):
        self.dir.cleanup()

    def correr(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = c.main(["--catalogo", self.cat, "--base", self.base, *args])
        return rc, out.getvalue(), err.getvalue()

    def test_elegir_preferido_y_alternativa(self):
        rc, out, _ = self.correr("elegir", "c")
        self.assertEqual((rc, out.split("\t")[0]), (0, "c"))
        self.assertEqual(out.strip().split("\t")[1:], [os.path.join(self.base, "c/c.sfz"), "32"])
        rc, out, _ = self.correr("elegir", "a")          # "a" no está descargado: el primero disponible
        self.assertEqual((rc, out.split("\t")[0]), (0, "b"))
        self.assertIn("b dir/b b.sfz", out, "las rutas con espacios se conservan (separador: tabulador)")

    def test_sin_disponibles_y_catalogo_roto(self):
        self.base = os.path.join(self.dir.name, "vacia")       # ningún SFZ descargado
        rc, out, err = self.correr("elegir")
        self.assertEqual((rc, out), (1, ""))
        self.assertIn("ningún instrumento disponible", err)
        with open(self.cat, "w") as f:
            f.write("{roto")
        rc, _, err = self.correr("lista")
        self.assertEqual(rc, 2)
        self.assertIn("ERROR", err)

    def test_lista_y_creditos(self):
        rc, out, _ = self.correr("lista")
        self.assertEqual(rc, 0)
        lineas = out.splitlines()
        self.assertEqual(len(lineas), 3)
        self.assertIn("NO", lineas[0])
        self.assertIn("-3.5 dB", lineas[1])
        rc, out, _ = self.correr("creditos")
        self.assertIn("Licencia: CC BY", out)
        self.assertIn("Fuente: http://c", out)
        self.assertIn("Uso: solo uso no comercial (RESTRINGIDO)", out)
        self.assertIn("Uso: libre, sin condiciones\n", out, "sin marca si no hay restricción")


if __name__ == "__main__":
    unittest.main()
