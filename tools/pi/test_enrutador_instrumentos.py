"""Pruebas de la lógica del cambio de instrumento en caliente (GestorInstrumentos y su uso en Enrutador).
Sin ALSA ni sfizz: reloj simulado y líneas de salida de sfizz escritas a mano."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import catalogo_instrumentos as cat  # noqa: E402
import enrutador_midi as em  # noqa: E402

CATALOGO = {"instrumentos": [
    {"id": "a", "nombre": "Piano A", "tipo": "cola", "sfz": "a/a.sfz", "ganancia_db": 0,
     "autor": "x", "licencia": "l", "uso": "u", "fuente": "f"},
    {"id": "b", "nombre": "Piano B", "tipo": "cola", "sfz": "b dir/b b.sfz", "ganancia_db": 9.2,
     "controles": {"77": 0}, "carga_s": 8.0, "autor": "Autora B", "licencia": "CC BY-NC",
     "uso": "solo uso no comercial", "restringido": True, "fuente": "https://b.example/b"},
    {"id": "c", "nombre": "Piano C", "tipo": "electrico", "sfz": "c/c.sfz", "ganancia_db": -10.2,
     "transposicion": 12, "autor": "x", "licencia": "l", "uso": "u", "fuente": "f"},
]}


class Reloj:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def avanzar(self, s):
        self.t += s


class Base(unittest.TestCase):
    def setUp(self):
        self.lista = cat.validar(CATALOGO, "/inst")
        self.a, self.b, self.c = self.lista
        self.reloj = Reloj()
        self.pared = Reloj()
        self.pared.t = 1_700_000_000.0
        self.g = em.GestorInstrumentos(self.lista, "a", self.reloj, reloj_pared=self.pared)

    def confirmar_inicio(self):
        self.g.iniciar()
        self.assertEqual(self.g.linea("> Volume set: 0 dB"), ([], "listo"))

    def cargar(self, inst, confirmar=True):
        """Espera la pausa de selección y devuelve las órdenes de carga; si confirmar, simula sfizz."""
        self.reloj.avanzar(em.ESPERA_SELECCION + 0.01)
        ordenes = self.g.tick()
        if confirmar:
            self.assertEqual(self.g.linea(f"> Instrument loaded: {inst.sfz}"), ([], None))
            self.assertEqual(self.g.linea(f"> Volume set: {inst.ganancia_db:g} dB"), ([], "listo"))
        return ordenes


class TestGestor(Base):
    def test_inicio_aplica_ajustes_sin_volver_a_cargar(self):
        ordenes = self.g.iniciar()
        self.assertEqual(ordenes, ["set_voices 32", "set_volume 0"])
        self.assertEqual(self.g.estado()["estado"], "cargando")
        self.assertEqual(self.g.linea("> Instrument loaded: /inst/a/a.sfz"), ([], None),
                         "en la fase de ajustes solo cuenta la confirmación del volumen")
        self.assertEqual(self.g.linea("> Volume set: 0 dB"), ([], "listo"))
        e = self.g.estado()
        self.assertEqual((e["estado"], e["actual"]["id"], e["posicion"], e["total"]), ("listo", "a", 1, 3))

    def test_preferido_inexistente_usa_el_primero(self):
        g = em.GestorInstrumentos(self.lista, "borrado", self.reloj)
        self.assertEqual(g.actual.id, "a")

    def test_cambio_completo_con_espera_y_confirmacion(self):
        self.confirmar_inicio()
        self.assertTrue(self.g.seleccionar("siguiente"))
        self.assertEqual(self.g.tick(), [], "no carga antes de la pausa")
        self.assertEqual(self.g.estado()["estado"], "elegido")
        self.reloj.avanzar(em.ESPERA_SELECCION + 0.01)
        ordenes = self.g.tick()
        self.assertEqual(ordenes, [f'load_instrument "{self.b.sfz}"', "set_voices 32", "set_cc 77 0",
                                   "set_volume 9.2"])
        self.assertEqual(self.g.tick(), [], "no repite la carga mientras está en curso")
        e = self.g.estado()
        self.assertEqual((e["estado"], e["cargando"]["id"], e["actual"]["id"]), ("cargando", "b", "a"))
        self.assertEqual(self.g.linea("> Instrument loaded: /inst/a/a.sfz"), ([], None), "otra ruta: se ignora")
        self.assertEqual(self.g.linea("> Volume set: 9.2 dB"), ([], None), "volumen antes de cargar: se ignora")
        self.assertEqual(self.g.linea(f"> Instrument loaded: {self.b.sfz}"), ([], None))
        self.assertEqual(self.g.linea("CC set: 77 = 0"), ([], None))
        self.assertEqual(self.g.linea("> Volume set: 9.2 dB"), ([], "listo"))
        e = self.g.estado()
        self.assertEqual((e["estado"], e["actual"]["id"], e["cargando"], e["posicion"]), ("listo", "b", None, 2))

    def test_recorrer_la_lista_rapido_carga_solo_el_ultimo(self):
        self.confirmar_inicio()
        for _ in range(2):
            self.g.seleccionar("siguiente")
            self.reloj.avanzar(em.ESPERA_SELECCION / 3)
            self.assertEqual(self.g.tick(), [])
        self.assertEqual(self.g.estado()["elegido"]["id"], "c")
        ordenes = self.cargar(self.c, confirmar=False)
        self.assertEqual(ordenes[0], f'load_instrument "{self.c.sfz}"')

    def test_eleccion_inmediata_desde_el_menu(self):
        self.confirmar_inicio()
        self.assertTrue(self.g.seleccionar("ya c"))
        ordenes = self.g.tick()
        self.assertEqual(ordenes[0], f'load_instrument "{self.c.sfz}"', "sin la pausa de recorrer la lista")
        self.assertFalse(self.g.seleccionar("ya no-existe"))

    def test_lista_para_el_menu(self):
        """Con los créditos de cada sonido: el menú F9 los muestra enteros y el panel inferior, los que caben."""
        lista = self.g.estado()["lista"]
        libre = {"autor": "x", "licencia": "l", "uso": "u", "restringido": False, "fuente": "f"}
        self.assertEqual(lista, [dict({"id": "a", "nombre": "Piano A", "tipo": "cola"}, **libre),
                                 {"id": "b", "nombre": "Piano B", "tipo": "cola", "autor": "Autora B",
                                  "licencia": "CC BY-NC", "uso": "solo uso no comercial", "restringido": True,
                                  "fuente": "https://b.example/b"},
                                 dict({"id": "c", "nombre": "Piano C", "tipo": "electrico"}, **libre)])

    def test_anterior_circular_y_por_id(self):
        self.confirmar_inicio()
        self.g.seleccionar("anterior")
        self.assertEqual(self.g.estado()["elegido"]["id"], "c")
        self.assertTrue(self.g.seleccionar("b"))
        self.assertEqual(self.g.estado()["elegido"]["id"], "b")
        self.assertFalse(self.g.seleccionar("no-existe"))
        self.assertEqual(self.g.estado()["elegido"]["id"], "b", "una selección inválida no cambia nada")

    def test_volver_al_actual_antes_de_la_pausa_no_carga(self):
        self.confirmar_inicio()
        self.g.seleccionar("siguiente")
        self.g.seleccionar("anterior")
        self.reloj.avanzar(10)
        self.assertEqual(self.g.tick(), [])
        self.assertEqual(self.g.estado()["estado"], "listo")

    def test_elegir_otro_durante_una_carga(self):
        self.confirmar_inicio()
        self.g.seleccionar("b")
        self.cargar(self.b, confirmar=False)
        self.g.seleccionar("c")                       # mientras carga "b"
        self.reloj.avanzar(em.ESPERA_SELECCION + 0.01)
        self.assertEqual(self.g.tick(), [], "espera a que termine la carga en curso")
        self.g.linea(f"> Instrument loaded: {self.b.sfz}")
        self.assertEqual(self.g.linea("> Volume set: 9.2 dB"), ([], "listo"))
        self.assertEqual(self.g.estado()["estado"], "elegido")
        ordenes = self.g.tick()
        self.assertEqual(ordenes[0], f'load_instrument "{self.c.sfz}"', "después carga el último elegido")

    def test_fallo_de_carga_vuelve_al_anterior_y_lo_informa(self):
        self.confirmar_inicio()
        self.g.seleccionar("c")
        self.cargar(self.c, confirmar=False)
        ordenes, evento = self.g.linea(f"> Could not load the instrument file: {self.c.sfz}")
        self.assertEqual(evento, "fallo")
        self.assertEqual(ordenes, [f'load_instrument "{self.a.sfz}"', "set_voices 32", "set_volume 0"])
        e = self.g.estado()
        self.assertEqual((e["estado"], e["cargando"]["id"], e["actual"]), ("cargando", "a", None))
        self.assertIn("Piano C", e["error"])
        self.g.linea(f"> Instrument loaded: {self.a.sfz}")
        self.assertEqual(self.g.linea("> Volume set: 0 dB"), ([], "listo"))
        e = self.g.estado()
        self.assertEqual((e["estado"], e["actual"]["id"]), ("error", "a"), "el error queda a la vista")
        self.assertEqual(self.g.tick(), [], "no reintenta solo")
        self.g.seleccionar("b")
        self.assertIsNone(self.g.estado()["error"], "una nueva elección borra el aviso")

    def test_error_generico_de_sfizz(self):
        self.confirmar_inicio()
        self.g.seleccionar("b")
        self.cargar(self.b, confirmar=False)
        self.assertEqual(self.g.linea("> ERROR: Can't load instrument!")[1], "fallo")

    def test_sin_respuesta(self):
        self.confirmar_inicio()
        self.g.seleccionar("b")
        self.cargar(self.b, confirmar=False)
        self.reloj.avanzar(em.TIEMPO_MAX_CARGA + 1)
        self.assertEqual(self.g.tick(), [])
        e = self.g.estado()
        self.assertEqual((e["estado"], e["cargando"], e["actual"]["id"]), ("error", None, "a"))
        self.assertIn("sin respuesta", e["error"])

    def test_lineas_sin_carga_en_curso_se_ignoran(self):
        self.confirmar_inicio()
        self.assertEqual(self.g.linea("> Volume set: 3 dB"), ([], None))
        self.assertEqual(self.g.linea("Could not load the instrument file: x"), ([], None))

    def test_lista_vacia(self):
        g = em.GestorInstrumentos([], "a", self.reloj)
        self.assertEqual(g.iniciar(), [])
        self.assertFalse(g.seleccionar("siguiente"))
        self.assertEqual(g.estado()["actual"], None)


class TestEnrutadorConInstrumentos(Base):
    def setUp(self):
        super().setUp()
        self.enr = em.Enrutador(instrumentos=self.g)
        self.enr.actualizar_fuentes({"Teclado Piano:notas": (128, 0, "pc")})
        self.confirmar_inicio()

    def test_cambio_suelta_las_notas_y_guarda_la_preferencia(self):
        self.enr.nota_on("Teclado Piano:notas", "pc", 0, 60, 80)
        self.assertEqual(self.enr.orden("instrumento siguiente"), ([], []))
        self.assertFalse(self.enr.cambios_prefs, "la preferencia no se guarda hasta que sfizz confirma")
        self.reloj.avanzar(em.ESPERA_SELECCION + 0.01)
        efectos, msgs = self.enr.tick()
        self.assertEqual(efectos[0][0], "sintetizador")
        self.assertEqual(efectos[0][1][0], f'load_instrument "{self.b.sfz}"')
        self.assertEqual(msgs, [("off", 60, 0)])
        self.assertEqual(self.enr.estado()["sonando"], [])
        self.assertEqual(self.enr.nota_off("Teclado Piano:notas", 0, 60), [], "la tecla soltada después no duplica")
        self.enr.linea_sintetizador(f"> Instrument loaded: {self.b.sfz}")
        self.assertEqual(self.enr.linea_sintetizador("> Volume set: 9.2 dB"),
                         ([("registro", "INSTRUMENTO b cargado en 0.0 s")], []))
        self.assertEqual(self.enr.prefs["instrumento"], "b")
        self.assertTrue(self.enr.cambios_prefs)
        self.assertEqual(self.enr.estado()["instrumento"]["actual"]["id"], "b")

    def test_pedal_cambiado_durante_la_carga_se_reenvia(self):
        self.enr.orden("instrumento c")
        self.reloj.avanzar(em.ESPERA_SELECCION + 0.01)
        self.enr.tick()
        self.enr.control(0, 64, 127)          # se pisa el pedal mientras sfizz carga (y no lee MIDI)
        self.enr.linea_sintetizador(f"> Instrument loaded: {self.c.sfz}")
        self.assertEqual(self.enr.linea_sintetizador("> Volume set: -10.2 dB"),
                         ([("registro", "INSTRUMENTO c cargado en 0.0 s")], [("cc", 64, 127, 0)]))

    def test_pedal_sin_cambios_no_se_reenvia(self):
        self.enr.control(0, 64, 127)
        self.enr.orden("instrumento c")
        self.reloj.avanzar(em.ESPERA_SELECCION + 0.01)
        efectos, msgs = self.enr.tick()
        self.assertNotIn(("cc", 64, 0, 0), msgs, "cambiar de sonido no suelta el pedal")
        self.enr.linea_sintetizador(f"> Instrument loaded: {self.c.sfz}")
        self.assertEqual(self.enr.linea_sintetizador("> Volume set: -10.2 dB"),
                         ([("registro", "INSTRUMENTO c cargado en 0.0 s")], []),
                         "sin reenvío (evita ruidos de pedal de algunos instrumentos)")

    def test_fallo_pide_recargar_el_anterior(self):
        self.enr.orden("instrumento b")
        self.reloj.avanzar(em.ESPERA_SELECCION + 0.01)
        self.enr.tick()
        efectos, _ = self.enr.linea_sintetizador("Could not load the instrument file: x")
        self.assertEqual(efectos, [("sintetizador", [f'load_instrument "{self.a.sfz}"', "set_voices 32",
                                                      "set_volume 0"])])
        self.assertEqual(self.enr.prefs["instrumento"], "salamander", "la preferencia no cambia")

    def test_orden_instrumento_ya(self):
        self.enr.orden("instrumento ya c")
        efectos, _ = self.enr.tick()
        self.assertEqual(efectos[0][1][0], f'load_instrument "{self.c.sfz}"')

    def test_transposicion_del_instrumento(self):
        PC = "Teclado Piano:notas"
        msgs = self.enr.nota_on(PC, "pc", 0, 60, 80)
        self.assertEqual(self.enr.para_sintetizador(msgs), [("on", 60, 80, 0)], "Piano A: sin transposición")
        self.enr.nota_off(PC, 0, 60)
        self.enr.orden("instrumento c")
        self.reloj.avanzar(em.ESPERA_SELECCION + 0.01)
        self.enr.tick()
        self.enr.linea_sintetizador(f"> Instrument loaded: {self.c.sfz}")
        self.enr.linea_sintetizador("> Volume set: -10.2 dB")
        msgs = self.enr.nota_on(PC, "pc", 0, 60, 80)
        self.assertEqual(msgs, [("on", 60, 80, 0)], "la interfaz ve la tecla pulsada")
        self.assertEqual(self.enr.estado()["sonando"], [60])
        self.assertEqual(self.enr.para_sintetizador(msgs), [("on", 72, 80, 0)], "a sfizz va una octava arriba")
        self.assertEqual(self.enr.para_sintetizador(self.enr.nota_off(PC, 0, 60)), [("off", 72, 0)])
        self.assertEqual(self.enr.para_sintetizador([("on", 120, 80, 0), ("cc", 64, 127, 0)]), [("cc", 64, 127, 0)],
                         "las notas que se saldrían de rango no se envían; los controles sí")

    def test_sin_gestor(self):
        enr = em.Enrutador()
        self.assertEqual(enr.orden("instrumento siguiente"), ([], []))
        self.assertEqual(enr.tick(), ([], []))
        self.assertEqual(enr.linea_sintetizador("> Volume set: 0 dB"), ([], []))
        self.assertNotIn("instrumento", enr.estado())
        self.assertEqual(enr.para_sintetizador([("on", 60, 80, 0)]), [("on", 60, 80, 0)])


class TestPausaYProgreso(Base):
    def setUp(self):
        super().setUp()
        self.enr = em.Enrutador(instrumentos=self.g)
        self.confirmar_inicio()

    def empezar(self, inst):
        self.enr.orden(f"instrumento {inst.id}")
        self.reloj.avanzar(em.ESPERA_SELECCION + 0.01)
        return self.enr.tick()

    def test_piano_en_pausa_mientras_carga(self):
        PC = "Teclado Piano:notas"
        self.assertFalse(self.enr.bloqueado())
        self.assertEqual(self.enr.nota_on(PC, "pc", 0, 60, 80), [("on", 60, 80, 0)])
        self.empezar(self.b)
        self.assertTrue(self.enr.bloqueado())
        self.assertEqual(self.enr.nota_on(PC, "pc", 0, 62, 80), [], "las notas no llegan a sfizz")
        self.assertEqual(self.enr.estado()["sonando"], [], "ni se ven como sonando en la interfaz")
        self.assertEqual(self.enr.nota_off(PC, 0, 62), [])
        self.assertEqual(self.enr.control(0, 1, 90), [], "tampoco otros controles")
        self.assertEqual(self.enr.control(0, 64, 127), [])
        self.assertTrue(self.enr.pedal, "el pedal se sigue registrando")
        self.enr.linea_sintetizador(f"> Instrument loaded: {self.b.sfz}")
        self.assertTrue(self.enr.bloqueado(), "sigue en pausa hasta aplicar volumen y controles")
        _, msgs = self.enr.linea_sintetizador("> Volume set: 9.2 dB")
        self.assertEqual(msgs, [("cc", 64, 127, 0)], "al terminar se le envía el pedal real")
        self.assertFalse(self.enr.bloqueado())
        self.assertEqual(self.enr.nota_on(PC, "pc", 0, 64, 80), [("on", 64, 80, 0)], "y vuelve a sonar")

    def test_progreso_para_la_interfaz(self):
        self.assertIsNone(self.enr.estado()["instrumento"]["carga"], "sin carga, sin ventana")
        self.empezar(self.b)
        carga = self.enr.estado()["instrumento"]["carga"]
        self.assertEqual(carga, {"id": "b", "nombre": "Piano B", "inicio": self.pared.t, "estimado_s": 8.0,
                                 "despues": None})
        self.enr.orden("instrumento c")                    # elegir otro durante la carga
        self.assertEqual(self.enr.estado()["instrumento"]["carga"]["despues"], {"id": "c", "nombre": "Piano C"})

    def test_aprende_el_tiempo_de_carga(self):
        self.assertEqual(self.g.estimado(self.b), 8.0, "al principio, el del catálogo")
        self.assertEqual(self.g.estimado(self.c), cat.CARGA_DEFECTO_S, "sin dato en el catálogo, el genérico")
        self.empezar(self.b)
        self.reloj.avanzar(4.0)
        self.enr.linea_sintetizador(f"> Instrument loaded: {self.b.sfz}")
        efectos, _ = self.enr.linea_sintetizador("> Volume set: 9.2 dB")
        self.assertEqual(efectos, [("registro", "INSTRUMENTO b cargado en 4.0 s")])
        self.assertEqual(self.g.estimado(self.b), 4.0)
        self.assertEqual(self.enr.prefs["tiempos_carga"], {"b": 4.0}, "se guarda en las preferencias")
        self.assertTrue(self.enr.cambios_prefs)
        self.enr.orden("instrumento a")
        self.reloj.avanzar(em.ESPERA_SELECCION + 0.01)
        self.enr.tick()
        self.enr.linea_sintetizador(f"> Instrument loaded: {self.a.sfz}")
        self.enr.linea_sintetizador("> Volume set: 0 dB")
        self.empezar(self.b)
        self.reloj.avanzar(2.0)
        self.enr.linea_sintetizador(f"> Instrument loaded: {self.b.sfz}")
        self.enr.linea_sintetizador("> Volume set: 9.2 dB")
        self.assertEqual(self.g.estimado(self.b), 3.0, "media entre la anterior (4) y la última (2)")

    def test_tiempos_aprendidos_al_arrancar_y_sin_ventana_al_inicio(self):
        g = em.GestorInstrumentos(self.lista, "a", self.reloj, tiempos={"b": 1.5}, reloj_pared=self.pared)
        self.assertEqual(g.estimado(self.b), 1.5, "lo aprendido manda sobre el catálogo")
        g.iniciar()
        self.assertIsNone(g.estado()["carga"], "los ajustes del arranque no muestran la pausa")
        self.reloj.avanzar(1.0)
        g.linea("> Volume set: 0 dB")
        self.assertIsNone(g.ultima_duracion, "ni cuentan como tiempo de carga")


class TestPreferenciaInstrumento(unittest.TestCase):
    def test_tiempos_de_carga(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "p.json")
            with open(ruta, "w") as f:
                f.write('{"tiempos_carga": {"osiris": 8.123, "Mal": 3, "maestro": true, "rhodes": -1, '
                        '"cp80": "2", "splendid": 0.9}}')
            self.assertEqual(em.cargar_preferencias(ruta)["tiempos_carga"], {"osiris": 8.12, "splendid": 0.9})
            self.assertEqual(em.cargar_preferencias(os.path.join(d, "no.json"))["tiempos_carga"], {})

    def test_validacion(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "p.json")
            self.assertEqual(em.cargar_preferencias(ruta)["instrumento"], "salamander")
            for valor, esperado in (("maestro", "maestro"), ("Mal ID", "salamander"), (3, "salamander")):
                with open(ruta, "w") as f:
                    f.write('{"instrumento": %s}' % (f'"{valor}"' if isinstance(valor, str) else valor))
                self.assertEqual(em.cargar_preferencias(ruta)["instrumento"], esperado)


if __name__ == "__main__":
    unittest.main()
