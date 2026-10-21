"""Pruebas de salidas_audio.py: detección, elección y cambio en caliente de la salida de audio (sin PipeWire)."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import salidas_audio as sa  # noqa: E402

G1 = "alsa_output.usb-Creative_Technology_Ltd_Sound_BlasterX_G1_00030790-00.analog-stereo"
G432 = "alsa_output.usb-Logitech_G432_Gaming_Headset_000000000000-00.analog-stereo"
PI = "alsa_output.platform-3f00b840.mailbox.stereo-fallback"
HDMI = "alsa_output.platform-3f902000.hdmi.hdmi-stereo"
SOLO48 = "alsa_output.usb-Otra_Marca_Tarjeta_48k-00.analog-stereo"


def nodo(oid, nombre, desc, nick, ruta, tarjeta, rate):
    return {"id": oid, "type": "PipeWire:Interface:Node",
            "info": {"props": {"media.class": "Audio/Sink", "node.name": nombre, "node.description": desc,
                               "node.nick": nick, "api.alsa.path": ruta, "api.alsa.card.name": tarjeta},
                     "params": {"EnumFormat": [{"mediaSubtype": "raw", "rate": rate, "channels": 2}]}}}


# Como el pw-dump real de la Pi (fase 10), más la G1 y una tarjeta USB que solo admite 48 kHz
DUMP = [
    nodo(70, PI, "Built-in Audio Stereo", "bcm2835 Headphones", "hw:0", "bcm2835 Headphones",
         {"default": 48000, "min": 8000, "max": 192000}),
    nodo(34, HDMI, "Built-in Audio Digital Stereo (HDMI)", "MAI PCM i2s-hifi-0", "hdmi:1", "vc4-hdmi",
         {"default": 48000, "min": 32000, "max": 48000}),
    nodo(80, G432, "G432 Gaming Headset Analog Stereo", "G432 Gaming Headset", "front:2", "G432 Gaming Headset",
         {"default": 48000, "min": 8000, "max": 48000}),
    nodo(81, G1, "Sound BlasterX G1 Analog Stereo", "Sound BlasterX G1", "front:3", "Sound BlasterX G1", 44100),
    nodo(82, SOLO48, "Tarjeta 48k Analog Stereo", "Tarjeta 48k", "front:4", "Tarjeta 48k",
         {"default": 48000, "min": 32000, "max": 96000}),
    {"id": 5, "type": "PipeWire:Interface:Node", "info": {"props": {"media.class": "Audio/Source", "node.name": "mic"}}},
    {"id": 6, "type": "PipeWire:Interface:Port", "info": {"props": {}}},
]
STREAM_G432 = """Logitech G432 Gaming Headset at usb-3f980000.usb-1.5, full speed : USB Audio

Playback:
  Status: Stop
  Interface 2
    Altset 1
    Format: S16_LE
    Channels: 2
    Endpoint: 0x01 (1 OUT) (ADAPTIVE)
    Rates: 8000, 16000, 24000, 32000, 44100, 48000
    Bits: 16

Capture:
  Status: Stop
  Interface 1
    Rates: 16000
"""
STREAM_SOLO48 = "Playback:\n  Interface 1\n    Rates: 48000, 96000\n\nCapture:\n    Rates: 44100\n"


class ConProc(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        for n, texto in ((2, STREAM_G432), (4, STREAM_SOLO48)):
            os.makedirs(os.path.join(self.d.name, f"card{n}"))
            with open(os.path.join(self.d.name, f"card{n}", "stream0"), "w") as f:
                f.write(texto)
        self.salidas = sa.salidas_de(DUMP, self.d.name)

    def tearDown(self):
        self.d.cleanup()

    def s(self, nombre):
        return next(x for x in self.salidas if x["nombre"] == nombre)


class TestDeteccion(ConProc):
    def test_solo_salidas_de_audio_y_en_orden(self):
        self.assertEqual([x["nombre"] for x in self.salidas], [G432, G1, SOLO48, PI, HDMI],
                         "USB primero (por nombre), después la Pi y el HDMI; sin micrófonos ni puertos")

    def test_tipos_nombres_y_avisos(self):
        self.assertEqual((self.s(G432)["tipo"], self.s(G432)["visible"], self.s(G432)["aviso"]),
                         ("usb", "G432 Gaming Headset", None))
        self.assertEqual(self.s(G1)["visible"], "Sound BlasterX G1")
        self.assertEqual((self.s(PI)["tipo"], self.s(PI)["visible"], self.s(PI)["aviso"]),
                         ("pi", "Auriculares de la Pi (3,5 mm)", sa.AVISO_PI))
        self.assertEqual((self.s(HDMI)["tipo"], self.s(HDMI)["visible"], self.s(HDMI)["aviso"]),
                         ("hdmi", "HDMI (por la pantalla)", sa.AVISO_HDMI))
        self.assertEqual(self.s(G432)["id"], 80, "el id del objeto: para el volumen con wpctl")

    def test_tasas(self):
        self.assertEqual(self.s(G432)["tasas"], [8000, 16000, 24000, 32000, 44100, 48000],
                         "USB: la lista exacta de /proc/asound (reproducción, no la captura)")
        self.assertEqual(self.s(G1)["tasas"], [44100], "la G1 solo admite 44,1 kHz")
        self.assertEqual(self.s(SOLO48)["tasas"], [48000, 96000])
        self.assertEqual(self.s(PI)["rango"], [8000, 192000])
        self.assertEqual((sa.tasa_para(self.s(G432)), sa.tasa_para(self.s(G1)), sa.tasa_para(self.s(SOLO48)),
                          sa.tasa_para(self.s(PI)), sa.tasa_para(self.s(HDMI))), (44100, 44100, 48000, 44100, 44100))

    def test_usb_sin_proc_usa_el_rango_de_pipewire(self):
        salidas = sa.salidas_de(DUMP, os.path.join(self.d.name, "no-existe"))
        g432 = next(x for x in salidas if x["nombre"] == G432)
        self.assertIsNone(g432["tasas"])
        self.assertEqual(g432["rango"], [8000, 48000])
        self.assertTrue(sa.admite(g432, 44100))

    def test_tasas_de_formato_con_alternativas(self):
        exactas, rango = sa.tasas_de_formato({"EnumFormat": [{"rate": {"default": 48000, "alt1": 44100}}]})
        self.assertEqual((exactas, rango), ({48000, 44100}, None))
        self.assertTrue(sa.admite({"tasas": None, "rango": None}, 44100), "sin datos: PipeWire convierte")

    def test_filtrar_para_las_pruebas(self):
        self.assertEqual([x["nombre"] for x in sa.filtrar(self.salidas, f" {PI} ,{G1}")], [G1, PI])
        self.assertEqual(sa.filtrar(self.salidas, ""), self.salidas)


class TestEleccion(ConProc):
    def test_la_preferida_si_esta(self):
        self.assertEqual(sa.elegir(self.salidas, G1), (self.s(G1), None))

    def test_si_falta_la_preferida_otra_usb_con_aviso(self):
        s, aviso = sa.elegir(self.salidas, "alsa_output.usb-no-esta")
        self.assertEqual(s["nombre"], G432)
        self.assertIn("no está conectada: se usa G432 Gaming Headset", aviso)

    def test_sin_preferida_la_primera_sin_aviso(self):
        self.assertEqual(sa.elegir(self.salidas, None), (self.s(G432), None))

    def test_solo_salidas_de_la_pi(self):
        s, _ = sa.elegir(sa.filtrar(self.salidas, f"{HDMI},{PI}"), G1)
        self.assertEqual(s["nombre"], PI, "sin USB, los auriculares de la Pi antes que el HDMI")

    def test_ninguna(self):
        s, aviso = sa.elegir([], G1)
        self.assertIsNone(s)
        self.assertIn("no hay ninguna salida", aviso)


class TestEnlaces(unittest.TestCase):
    def test_puertos_y_pares(self):
        lineas = [f"{G1}:playback_FR", "otro:playback_FL", f"{G1}:playback_FL", f"{G1}:monitor_FL"]
        puertos = sa.puertos_de(G1, lineas)
        self.assertEqual(puertos[:2], [f"{G1}:playback_FL", f"{G1}:playback_FR"], "FL y FR primero")
        self.assertEqual(sa.pares(["fx:left_out", "fx:right_out"], puertos[:2]),
                         [("fx:left_out", f"{G1}:playback_FL"), ("fx:right_out", f"{G1}:playback_FR")])
        self.assertEqual(sa.pares(["fx:mono"], ["s:FL", "s:FR"]), [("fx:mono", "s:FL"), ("fx:mono", "s:FR")])
        self.assertEqual(sa.pares(["a", "b"], ["s:MONO"]), [("a", "s:MONO"), ("b", "s:MONO")])
        self.assertEqual(sa.pares([], ["x"]), [])

    def test_destinos_de_pw_link_l(self):
        lineas = ["piano-vivo-fx:left_out", f"  |-> {G1}:playback_FL", "  |-> piano-ancla-vivo:input_FL",
                  "piano-vivo-fx:right_out", f"  |-> {G1}:playback_FR", f"{G1}:playback_FL",
                  "  |<- piano-vivo-fx:left_out"]
        self.assertEqual(sa.destinos_de(lineas, "piano-vivo-fx:left_out"),
                         [f"{G1}:playback_FL", "piano-ancla-vivo:input_FL"])
        self.assertEqual(sa.destinos_de(lineas, "piano-vivo-fx:right_out"), [f"{G1}:playback_FR"])
        self.assertEqual(sa.destinos_de(lineas, f"{G1}:playback_FL"), [], "los enlaces de entrada (|<-) no cuentan")
        self.assertEqual(sa.destinos_de(lineas, "no:existe"), [])

    # Como `pw-link -iIl` real en la Pi (fase 10): ids alineados a la derecha, puertos con espacios y paréntesis
    IIL = ["  31 Midi-Bridge:Midi Through:(playback_0) Midi Through Port-0",
           f" 105 {G1}:playback_FL",
           " 114   |<-  116 piano-vivo-fx:left_out",
           f"  95 {G1}:playback_FR",
           " 108   |<-  110 piano-vivo-fx:right_out",
           " 120 piano-ancla-vivo:input_FL",
           " 121   |<-  116 piano-vivo-fx:left_out",
           " 122   |<-  130 otro:out",
           " 123 piano-ancla-vivo:input_FR",
           "",
           "basura sin id"]

    def test_entradas_de_pw_link_iIl(self):
        e = sa.entradas_de(self.IIL)
        self.assertEqual(e["Midi-Bridge:Midi Through:(playback_0) Midi Through Port-0"], (31, []))
        self.assertEqual(e[f"{G1}:playback_FL"], (105, ["piano-vivo-fx:left_out"]))
        self.assertEqual(e["piano-ancla-vivo:input_FL"], (120, ["piano-vivo-fx:left_out", "otro:out"]),
                         "varios orígenes en una entrada")
        self.assertEqual(e["piano-ancla-vivo:input_FR"], (123, []))
        self.assertEqual(len(e), 5, "las líneas vacías o sin id no son entradas")
        self.assertEqual(sa.entradas_de([]), {})
        self.assertEqual(sa.entradas_de(["   |<-  116 huérfano:out"]), {}, "un enlace sin entrada antes: se ignora")

    def test_firma_cambia_si_se_recrea_no_con_los_enlaces(self):
        base = sa.firma_entradas(sa.entradas_de(self.IIL))
        sin_enlaces = [l for l in self.IIL if "|<-" not in l]
        self.assertEqual(sa.firma_entradas(sa.entradas_de(sin_enlaces)), base,
                         "perder enlaces no cambia la firma (eso lo vigila enlazada)")
        recreada = [l.replace(" 105 ", " 140 ") for l in self.IIL]
        self.assertNotEqual(sa.firma_entradas(sa.entradas_de(recreada)), base,
                            "la tarjeta recreada (mismo nombre, otro id: WirePlumber reiniciado) se nota")
        self.assertNotEqual(sa.firma_entradas(sa.entradas_de(self.IIL[:3])), base, "y si desaparece una entrada")

    def test_enlazada(self):
        e = sa.entradas_de(self.IIL)
        desde = ["piano-vivo-fx:left_out", "piano-vivo-fx:right_out"]
        self.assertTrue(sa.enlazada(e, G1, desde))
        self.assertFalse(sa.enlazada(e, "piano-ancla-vivo", desde), "al ancla solo llega la izquierda")
        self.assertFalse(sa.enlazada(e, G432, desde), "salida sin entradas")
        self.assertFalse(sa.enlazada(e, G1, []), "sin puertos de la reverb no hay nada enlazado")
        sin_der = [l for l in self.IIL if "right_out" not in l]
        self.assertFalse(sa.enlazada(sa.entradas_de(sin_der), G1, desde), "falta un canal: no está enlazada")
        self.assertTrue(sa.enlazada(e, G1, ["piano-vivo-fx:left_out"]), "reverb mono")
        self.assertFalse(sa.enlazada(e, G1[:-3], desde), "el nombre se compara entero (prefijo «nombre:»)")


class TestSuspension(unittest.TestCase):
    """Una salida que el piano deja se suspende en cuanto queda libre (WirePlumber 0.4.13 cae si desaparece en los
    5 s que él espera para suspenderla)."""

    def dump(self, estado):
        return [{"id": 81, "type": "PipeWire:Interface:Node", "info": {"state": estado, "props": {"node.name": G1}}},
                {"id": 82, "type": "PipeWire:Interface:Port", "info": {"props": {"node.name": G1}}}]

    def ejecutor(self, salida="Object: size 8, type Spa:Pod:Object:Command:Node", rc=0, error=None):
        llamadas = []

        def ejecutar(args, **kw):
            llamadas.append(args)
            if error:
                raise error
            return mock.Mock(returncode=rc, stdout=salida, stderr="")
        return ejecutar, llamadas

    def test_estado_nodo(self):
        self.assertEqual(sa.estado_nodo(self.dump("idle"), G1), (81, "idle"), "el nodo, no su puerto")
        self.assertIsNone(sa.estado_nodo(self.dump("idle"), G432))

    def test_libre_se_suspende(self):
        ejecutar, llamadas = self.ejecutor()
        self.assertEqual(sa.suspender_si_libre(G1, self.dump("idle"), ejecutar), "suspendida")
        self.assertEqual(llamadas, [["pw-cli", "send-command", "81", "Suspend", "{}"]])

    def test_ocupada_ya_o_ausente_no_se_toca(self):
        for estado, esperado in (("running", "ocupada"), ("suspended", "ya"), ("error", "ocupada")):
            ejecutar, llamadas = self.ejecutor()
            self.assertEqual(sa.suspender_si_libre(G1, self.dump(estado), ejecutar), esperado)
            self.assertEqual(llamadas, [], f"{estado}: sin orden")
        ejecutar, llamadas = self.ejecutor()
        self.assertEqual(sa.suspender_si_libre(G432, self.dump("idle"), ejecutar), "no está")
        self.assertEqual(llamadas, [])

    def test_errores_de_pw_cli(self):
        ejecutar, _ = self.ejecutor(salida='Error: "send-command: unknown global \'81\'"')
        self.assertEqual(sa.suspender_si_libre(G1, self.dump("idle"), ejecutar), "error",
                         "pw-cli termina con 0 aunque falle: se mira lo que imprime")
        ejecutar, _ = self.ejecutor(rc=1)
        self.assertEqual(sa.suspender_si_libre(G1, self.dump("idle"), ejecutar), "error")
        ejecutar, _ = self.ejecutor(error=OSError("sin pw-cli"))
        self.assertEqual(sa.suspender_si_libre(G1, self.dump("idle"), ejecutar), "error")

    def test_linea_de_ordenes_espera_a_que_quede_libre(self):
        dumps = [self.dump("running"), self.dump("running"), self.dump("idle")]
        dormidas, ordenes = [], []

        def ejecutar(args, **kw):
            ordenes.append(args)
            return mock.Mock(returncode=0, stdout="", stderr="")
        out = io.StringIO()
        with mock.patch.object(sa, "leer_pw_dump", lambda: dumps.pop(0)), \
                mock.patch.object(sa.subprocess, "run", ejecutar), redirect_stdout(out):
            self.assertEqual(sa.suspender_cli(G1, dormir=dormidas.append), 0)
        self.assertEqual((out.getvalue(), dormidas, len(ordenes)), (f"{G1}: suspendida\n", [0.2, 0.2], 1))

    def test_linea_de_ordenes_nunca_falla(self):
        out = io.StringIO()
        with mock.patch.object(sa, "leer_pw_dump", lambda: self.dump("running")), redirect_stdout(out):
            self.assertEqual(sa.suspender_cli(G1, espera=1.0, dormir=lambda s: None), 0,
                             "siempre 0: es una protección y no debe impedir el cierre del piano")
        self.assertEqual(out.getvalue(), f"{G1}: ocupada\n")

        def roto():
            raise ValueError("pw-dump ilegible")
        out = io.StringIO()
        with mock.patch.object(sa, "leer_pw_dump", roto), redirect_stdout(out):
            self.assertEqual(sa.suspender_cli(G1, dormir=lambda s: None), 0)
        self.assertEqual(out.getvalue(), f"{G1}: error\n")


class TestGestorSalida(ConProc):
    def gestor(self, activa=G1, prefs=None, tasa=44100):
        g = sa.GestorSalida(prefs if prefs is not None else {}, activa, tasa)
        g.actualizar(self.salidas)
        return g

    def test_inicio_aplica_el_volumen(self):
        self.assertEqual(self.gestor().inicio(), [("volumen", G1)])

    def test_volumen_la_primera_vez_con_tope_y_despues_el_recordado(self):
        g = self.gestor()
        self.assertEqual(g.volumen_para(G432, 0.80), 0.40, "un audífono nunca hereda de golpe el 80 %")
        self.assertEqual(g.volumen_para(PI, 0.25), 0.25, "si ya estaba más bajo, se respeta")
        self.assertTrue(g.cambios_prefs)
        self.assertEqual(g.volumen_para(G432, 0.10), 0.40, "la segunda vez, el recordado")
        g.registrar_volumen(G432, 0.62)
        self.assertEqual(g.volumen_para(G432, 0.10), 0.62)
        self.assertEqual(g.prefs["volumen_salidas"], {G432: 0.62, PI: 0.25})
        self.assertFalse(g.registrar_volumen(G432, 0.62), "sin cambios, no se marca")

    def test_cambio_en_caliente_conectar_antes_de_cortar(self):
        g = self.gestor()
        efectos = g.seleccionar(G432)
        self.assertEqual(efectos, [("guardar_volumen", G1), ("enlazar", G432), ("comprobar", G432)],
                         "primero se guarda el volumen de la que se deja y se enlaza la nueva; nada se suelta aún")
        self.assertEqual((g.estado, g.activa), ("cambiando", G1))
        self.assertEqual(g.estado_publico()["destino"], "G432 Gaming Headset")
        efectos = g.confirmar(True)
        self.assertEqual(efectos, [("soltar", G1), ("nodo_cortes", G1, G432), ("volumen", G432), ("suspender", G1)],
                         "solo con la nueva confirmada se suelta la anterior, y después se suspende")
        self.assertEqual((g.estado, g.activa, g.prefs["salida"], g.cambios_prefs), ("lista", G432, G432, True))

    def test_si_no_se_pudo_enlazar_sigue_la_anterior(self):
        g = self.gestor()
        g.seleccionar(G432)
        self.assertEqual(g.confirmar(False), [("soltar", G432)])
        self.assertEqual((g.estado, g.activa, g.error), ("lista", G1, "no se pudo enlazar la salida"))
        self.assertNotIn("salida", g.prefs)

    def test_ordenes_que_no_se_cumplen(self):
        g = self.gestor()
        self.assertEqual(g.seleccionar("no-existe"), [])
        self.assertEqual(g.error, "esa salida ya no está conectada")
        self.assertEqual(g.seleccionar(G1), [], "la que ya suena: nada")
        g.seleccionar(G432)
        self.assertEqual(g.seleccionar(PI), [])
        self.assertIn("espera", g.error)

    def test_tarjeta_que_necesita_48k(self):
        g = self.gestor()
        self.assertEqual(g.seleccionar(SOLO48), [], "no se cambia en caliente de frecuencia")
        self.assertEqual(g.error, "Tarjeta 48k necesita 48 kHz: se usará al volver a abrir el piano")
        self.assertEqual((g.prefs["salida"], g.activa), (SOLO48, G1), "queda elegida para la próxima vez")
        aviso = next(x["aviso"] for x in g.estado_publico()["lista"] if x["nombre"] == SOLO48)
        self.assertEqual(aviso, "necesita 48 kHz: al volver a abrir")
        g48 = self.gestor(activa=SOLO48, tasa=48000)
        self.assertEqual(g48.seleccionar(G432)[1], ("enlazar", G432), "a 48 kHz, una que la admite: en caliente")

    def test_desconexion_y_reconexion(self):
        g = self.gestor(activa=G432)
        sin_g432 = [x for x in self.salidas if x["nombre"] != G432]
        self.assertEqual(g.actualizar(sin_g432), [])
        self.assertEqual((g.estado, g.aviso), ("desconectada", sa.AVISO_DESCONECTADA))
        self.assertIsNone(g.estado_publico()["activa"]["id"])
        self.assertEqual(g.actualizar(sin_g432), [], "sigue desconectada: nada que hacer")
        self.assertEqual(g.actualizar(self.salidas), [("enlazar", G432), ("comprobar", G432)], "vuelve: se enlaza")
        self.assertEqual(g.confirmar(True), [("volumen", G432)], "la misma: nada que soltar")
        self.assertEqual((g.estado, g.aviso), ("lista", None))

    def test_desconectada_se_puede_elegir_otra(self):
        g = self.gestor(activa=G432)
        g.actualizar([x for x in self.salidas if x["nombre"] != G432])
        self.assertEqual(g.seleccionar(G1), [("enlazar", G1), ("comprobar", G1)],
                         "sin guardar el volumen de la que ya no está")
        self.assertEqual(g.confirmar(True), [("soltar", G432), ("nodo_cortes", G432, G1), ("volumen", G1)],
                         "ni se suspende: ya no está")

    def test_si_la_reverb_pierde_los_enlaces_se_rehacen(self):
        g = self.gestor()
        self.assertEqual(g.verificar(True), [], "enlazada: nada")
        self.assertEqual(g.verificar(False), [("enlazar", G1), ("comprobar", G1)],
                         "WirePlumber reiniciado: la tarjeta sigue, los enlaces no -> se rehacen")
        self.assertEqual((g.estado, g.estado_publico()["destino"]), ("cambiando", "Sound BlasterX G1"))
        self.assertEqual(g.verificar(False), [], "mientras se rehace, no se repite")
        self.assertEqual(g.confirmar(True), [("volumen", G1)], "la misma: ni soltar ni suspender; su volumen")
        self.assertEqual((g.estado, g.activa, g.error), ("lista", G1, None))

    def test_verificar_no_actua_sin_tarjeta_ni_a_mitad_de_un_cambio(self):
        g = self.gestor(activa=G432)
        g.actualizar([x for x in self.salidas if x["nombre"] != G432])
        self.assertEqual(g.verificar(False), [], "desconectada de verdad: espera a que vuelva (actualizar)")
        g = self.gestor()
        g.seleccionar(G432)
        self.assertEqual(g.verificar(False), [], "cambiando: lo resuelve confirmar")

    def test_reintento_espaciado_tras_un_enlace_fallido(self):
        g = self.gestor()
        g.verificar(False)
        self.assertEqual(g.confirmar(False), [])
        self.assertEqual((g.estado, g.error), ("desconectada", sa.ERROR_ENLAZAR))
        self.assertEqual([g.verificar(False) for _ in range(sa.ESPERA_REINTENTO)], [[]] * sa.ESPERA_REINTENTO,
                         "no se reintenta cada segundo")
        self.assertEqual(g.verificar(False), [("enlazar", G1), ("comprobar", G1)])
        g.confirmar(True)
        self.assertEqual((g.estado, g.error, g.aviso), ("lista", None, None), "al lograrlo, el error se borra")

    def test_un_error_de_otra_orden_no_lo_borra_el_reenlace(self):
        g = self.gestor()
        g.seleccionar(SOLO48)
        g.verificar(False)
        g.confirmar(True)
        self.assertIn("necesita 48 kHz", g.error)

    def test_la_destino_desaparece_a_mitad_del_cambio(self):
        g = self.gestor()
        g.seleccionar(G432)
        g.actualizar([x for x in self.salidas if x["nombre"] != G432])
        self.assertEqual((g.estado, g.activa), ("lista", G1))
        self.assertIn("se desconectó", g.error)
        self.assertEqual(g.confirmar(True), [], "una confirmación tardía no cambia nada")

    def test_estado_publico(self):
        e = self.gestor(activa=G432).estado_publico()
        self.assertEqual(e["activa"], {"nombre": G432, "visible": "G432 Gaming Headset", "id": 80, "tipo": "usb"})
        self.assertEqual([x["activa"] for x in e["lista"]], [True, False, False, False, False])
        self.assertEqual((e["estado"], e["tasa"], e["error"]), ("lista", 44100, None))
        json.dumps(e)


class TestEsperaAlEncender(ConProc):
    """Fase 11: al encender, esperar a que WirePlumber publique la tarjeta antes de abrir el piano."""

    def esperar(self, lecturas, preferida, segundos=20.0):
        """Reloj falso: cada lectura avanza 0,5 s (la pausa). Devuelve (código, lecturas hechas, salida)."""
        t, hechas = [0.0], []

        def leer():
            x = lecturas[min(len(hechas), len(lecturas) - 1)]
            hechas.append(1)
            if isinstance(x, Exception):
                raise x
            return x
        out = io.StringIO()
        with redirect_stdout(out):
            rc = sa.esperar_cli(preferida, segundos, leer=leer, reloj=lambda: t[0],
                                dormir=lambda s: t.__setitem__(0, t[0] + s))
        return rc, len(hechas), out.getvalue()

    def test_lista_para_tocar(self):
        self.assertTrue(sa.lista_para_tocar(self.salidas, G1))
        self.assertFalse(sa.lista_para_tocar(self.salidas, "usb-no-esta"), "con preferida: solo ella")
        self.assertTrue(sa.lista_para_tocar(self.salidas, None), "sin preferida: alguna USB")
        self.assertFalse(sa.lista_para_tocar([self.s(PI), self.s(HDMI)], None), "las de la Pi no bastan: se espera")
        self.assertFalse(sa.lista_para_tocar([], G1))

    def test_espera_a_que_aparezca(self):
        sin_g1 = [x for x in self.salidas if x["nombre"] != G1]
        rc, n, out = self.esperar([[], sin_g1, self.salidas], G1)
        self.assertEqual((rc, n), (0, 3), "espera mientras no está y sigue en cuanto aparece")
        self.assertIn("lista: Sound BlasterX G1", out)

    def test_pipewire_aun_arrancando(self):
        rc, n, _ = self.esperar([OSError("pw-dump"), ValueError("json a medias"), self.salidas], G1)
        self.assertEqual((rc, n), (0, 3), "un PipeWire que aún no responde no es un error: se sigue esperando")

    def test_si_no_llega_se_rinde_a_tiempo(self):
        rc, n, out = self.esperar([[self.s(PI)]], G1, segundos=3)
        self.assertEqual(rc, 1)
        self.assertEqual(n, 7, "0, 0,5 ... 3 s: siete lecturas y se rinde")
        self.assertIn("no apareció en 3 s: el piano usará otra", out)
        self.assertEqual(self.esperar([[]], G1, segundos=0)[:2], (1, 1), "0 s: una sola mirada")

    def test_sin_preferida_vale_la_primera_usb(self):
        rc, _, out = self.esperar([self.salidas], None)
        self.assertEqual(rc, 0)
        self.assertIn("lista: G432 Gaming Headset", out)


class TestLineaDeOrdenes(ConProc):
    def correr(self, *args, entorno=None, prefs=None):
        out, err = io.StringIO(), io.StringIO()
        ruta = os.path.join(self.d.name, "prefs.json")
        with open(ruta, "w") as f:
            json.dump(prefs or {}, f)
        salidas = self.salidas
        with mock.patch.object(sa, "leer_pw_dump", lambda: DUMP), \
                mock.patch.object(sa, "salidas_de", lambda objetos: salidas), \
                mock.patch.dict(os.environ, entorno or {}, clear=False), redirect_stdout(out), redirect_stderr(err):
            for k in ("PIANO_SALIDA", "PIANO_SOLO_SALIDAS"):
                if k not in (entorno or {}):
                    os.environ.pop(k, None)
            rc = sa.main(list(args) + ["--preferencias", ruta])
        return rc, out.getvalue(), err.getvalue()

    def test_elegir(self):
        self.assertEqual(self.correr("elegir", prefs={"salida": G1})[:2], (0, f"{G1}\t44100\t\n"))
        rc, out, _ = self.correr("elegir", prefs={"salida": "no-esta"})
        self.assertEqual(out.split("\t")[:2], [G432, "44100"])
        self.assertIn("no está conectada", out)
        self.assertEqual(self.correr("elegir", entorno={"PIANO_SALIDA": SOLO48}, prefs={"salida": G1})[1],
                         f"{SOLO48}\t48000\t\n", "PIANO_SALIDA manda; esa tarjeta pide 48 kHz")
        rc, out, err = self.correr("elegir", entorno={"PIANO_SOLO_SALIDAS": "ninguna-real"})
        self.assertEqual((rc, out), (1, ""))
        self.assertIn("no hay ninguna salida", err)

    def test_lista_y_uso(self):
        rc, out, _ = self.correr("lista")
        self.assertEqual(rc, 0)
        self.assertEqual(len(out.splitlines()), 5)
        self.assertIn("8000,16000,24000,32000,44100,48000", out)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(sa.main(["otra-cosa"]), 2)
            self.assertEqual(sa.main(["suspender"]), 2, "suspender sin nombre")
        self.assertIn("salidas_audio.py suspender NODE.NAME", err.getvalue(), "el uso impreso es el de la ayuda")
        with mock.patch.object(sa, "suspender_cli", lambda nombre: f"cli {nombre}"):
            self.assertEqual(sa.main(["suspender", G1]), f"cli {G1}")

    def test_esperar_desde_la_linea_de_ordenes(self):
        llamadas = []
        ruta = os.path.join(self.d.name, "p.json")
        with open(ruta, "w") as f:
            json.dump({"salida": G1}, f)
        with mock.patch.object(sa, "esperar_cli", lambda pref, seg: llamadas.append((pref, seg)) or 0), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PIANO_SALIDA", None)
            self.assertEqual(sa.main(["esperar", "--preferencias", ruta]), 0)
            self.assertEqual(sa.main(["esperar", "--preferencias", ruta, "--segundos", "5"]), 0)
            os.environ["PIANO_SALIDA"] = PI
            sa.main(["esperar", "--preferencias", ruta])
        self.assertEqual(llamadas, [(G1, 20.0), (G1, 5.0), (PI, 20.0)],
                         "20 s por omisión; la preferida de las preferencias, o PIANO_SALIDA por encima")
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(sa.main(["esperar", "--segundos", "mucho"]), 2)


if __name__ == "__main__":
    unittest.main()
