"""Pruebas de la lógica del enrutador MIDI (sin ALSA)."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import enrutador_midi as em  # noqa: E402
import alsa_seq as aseq  # noqa: E402

PC = "Teclado Piano:notas"
MIDI = "Roland FP:Roland FP MIDI 1"


def detectadas(**fuentes):
    return fuentes


class TestCurva(unittest.TestCase):
    def test_curvas(self):
        for v in (1, 40, 64, 100, 127):
            self.assertEqual(em.curva_fuerza(v, "normal"), v)
        self.assertGreater(em.curva_fuerza(64, "suave"), 64, "suave: menos fuerza para el mismo volumen")
        self.assertLess(em.curva_fuerza(64, "dura"), 64)
        for c in em.CURVAS:
            self.assertEqual(em.curva_fuerza(127, c), 127)
            self.assertGreaterEqual(em.curva_fuerza(1, c), 1, "nunca convierte una nota en silencio")
            self.assertEqual(em.curva_fuerza(0, c), 0)
        valores = [em.curva_fuerza(v, "dura") for v in range(1, 128)]
        self.assertEqual(valores, sorted(valores), "la curva es monótona")


class TestPreferencias(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.ruta = os.path.join(self.d.name, "sub", "preferencias.json")

    def tearDown(self):
        self.d.cleanup()

    def test_defecto_si_no_existe_o_corrupto(self):
        self.assertEqual(em.cargar_preferencias(self.ruta), em.PREFERENCIAS_DEFECTO)
        os.makedirs(os.path.dirname(self.ruta))
        with open(self.ruta, "w") as f:
            f.write("{no es json")
        self.assertEqual(em.cargar_preferencias(self.ruta), em.PREFERENCIAS_DEFECTO)
        with open(self.ruta, "w") as f:
            f.write("[1, 2]")
        self.assertEqual(em.cargar_preferencias(self.ruta), em.PREFERENCIAS_DEFECTO)

    def test_ida_y_vuelta_y_validacion(self):
        p = em.cargar_preferencias(self.ruta)
        p.update(transposicion=-3, curva="dura", latencia=256, reverb=0.5, auto_nuevas=False,
                 fuentes={MIDI: False})
        em.guardar_preferencias(p, self.ruta)
        self.assertEqual(em.cargar_preferencias(self.ruta), p)
        with open(self.ruta, "w") as f:
            json.dump({"transposicion": 99, "curva": "rara", "latencia": 333, "reverb": 7,
                       "auto_nuevas": "si", "fuentes": {"x": "no"}, "transposicion_extra": 1}, f)
        self.assertEqual(em.cargar_preferencias(self.ruta), em.PREFERENCIAS_DEFECTO,
                         "valores inválidos -> por defecto")
        with open(self.ruta, "w") as f:
            json.dump({"transposicion": True}, f)
        self.assertEqual(em.cargar_preferencias(self.ruta)["transposicion"], 0, "un bool no es un entero")

    def test_salida_y_volumen_por_tarjeta(self):
        """Fase 10: la tarjeta elegida y el volumen recordado de cada una, validados."""
        os.makedirs(os.path.dirname(self.ruta), exist_ok=True)
        g1 = "alsa_output.usb-Creative_Technology_Ltd_Sound_BlasterX_G1_00030790-00.analog-stereo"
        with open(self.ruta, "w") as f:
            json.dump({"salida": g1, "volumen_salidas": {g1: 0.8, "audifono": 0.333, "malo": "alto", "fuera": 3,
                                                         "bool": True}}, f)
        p = em.cargar_preferencias(self.ruta)
        self.assertEqual(p["salida"], g1)
        self.assertEqual(p["volumen_salidas"], {g1: 0.8, "audifono": 0.33}, "sin textos, fuera de rango ni bool")
        with open(self.ruta, "w") as f:
            json.dump({"salida": 7, "volumen_salidas": [1]}, f)
        p = em.cargar_preferencias(self.ruta)
        self.assertEqual((p["salida"], p["volumen_salidas"]), ("", {}))
        with open(self.ruta, "w") as f:
            json.dump({"salida": "x" * 300}, f)
        self.assertEqual(em.cargar_preferencias(self.ruta)["salida"], "", "un nombre absurdamente largo no")


class TestSalidaEnElEnrutador(unittest.TestCase):
    """Fase 10: la orden «salida», la pausa mientras se cambia y el estado para la interfaz."""

    def setUp(self):
        import salidas_audio as sa
        self.sa = sa
        self.salidas = [{"id": 80, "nombre": "usb-g432", "visible": "G432", "tipo": "usb", "tasas": [44100],
                         "rango": None, "aviso": None},
                        {"id": 81, "nombre": "usb-g1", "visible": "G1", "tipo": "usb", "tasas": [44100], "rango": None,
                         "aviso": None}]
        self.e = em.Enrutador()
        self.e.salida = sa.GestorSalida(self.e.prefs, "usb-g1", 44100)
        self.e.salida.actualizar(self.salidas)

    def test_orden_salida(self):
        efectos, msgs = self.e.orden("salida usb-g432")
        self.assertEqual(efectos, [("guardar_volumen", "usb-g1"), ("enlazar", "usb-g432"), ("comprobar", "usb-g432")])
        self.assertEqual(msgs, [])
        self.assertTrue(set(e[0] for e in efectos) <= set(em.EFECTOS_SALIDA), "todos los ejecuta aplicar_salida")
        self.assertEqual(self.e.orden("salida"), ([], []), "sin nombre: nada")
        sin = em.Enrutador()
        self.assertEqual(sin.orden("salida usb-g432"), ([], []), "modo silencio (sin gestor): nada")

    def test_pausa_mientras_cambia(self):
        self.assertEqual(self.e.nota_on("t", "pc", 0, 60, 90), [("on", 60, 90, 0)])
        self.e.orden("salida usb-g432")
        self.assertTrue(self.e.bloqueado())
        self.assertEqual(self.e.nota_on("t", "pc", 0, 62, 90), [], "en pausa no se envían notas")
        self.assertEqual(self.e.nota_off("t", 0, 60), [("off", 60, 0)], "pero las que sonaban se sueltan")
        self.e.salida.confirmar(True)
        self.assertFalse(self.e.bloqueado())

    def test_estado_y_preferencia(self):
        e = self.e.estado()
        self.assertEqual(e["salida"]["activa"]["nombre"], "usb-g1")
        self.assertEqual(len(e["salida"]["lista"]), 2)
        json.dumps(e)
        self.e.orden("salida usb-g432")
        self.e.salida.confirmar(True)
        self.assertEqual(self.e.prefs["salida"], "usb-g432", "la elección se guarda en las mismas preferencias")
        self.assertTrue(self.e.salida.cambios_prefs)
        self.assertNotIn("salida", em.Enrutador().estado(), "sin gestor no se publica")

    def test_todos_los_efectos_los_ejecuta_aplicar_salida(self):
        efectos = self.e.orden("salida usb-g432")[0] + self.e.salida.confirmar(True)
        efectos += self.e.salida.verificar(False) + self.e.salida.confirmar(True)
        self.assertIn(("suspender", "usb-g1"), efectos)
        self.assertTrue(set(e[0] for e in efectos) <= set(em.EFECTOS_SALIDA))

    def test_rehacer_los_enlaces_tambien_pausa(self):
        self.e.salida.verificar(False)
        self.assertTrue(self.e.bloqueado(), "mientras se rehacen los enlaces de la tarjeta no se envían notas nuevas")
        self.e.salida.confirmar(True)
        self.assertFalse(self.e.bloqueado())


class TestCambioDeNodoVigilado(unittest.TestCase):
    def test_cambiar_nodo(self):
        m = em.MonitorCortes(["piano-vivo", "piano-vivo-fx", "usb-g1"])
        m.ultimo["usb-g1"] = 5
        m.cambiar_nodo("usb-g1", "usb-g432")
        self.assertEqual(m.nodos, ["piano-vivo", "piano-vivo-fx", "usb-g432"])
        self.assertNotIn("usb-g1", m.ultimo, "el contador del nodo viejo ya no se compara")
        self.assertEqual(m.nodo, "piano-vivo", "el principal no cambia")
        m.cambiar_nodo("no-estaba", "otra")
        self.assertEqual(m.nodos[-1], "otra")
        m2 = em.MonitorCortes("solo")
        m2.cambiar_nodo("solo", "nuevo")
        self.assertEqual((m2.nodos, m2.nodo), (["nuevo"], "nuevo"))


class TestEsFuente(unittest.TestCase):
    LECT = aseq.SEQ_PORT_CAP_READ | aseq.SEQ_PORT_CAP_SUBS_READ

    def test_exclusiones(self):
        self.assertTrue(em.es_fuente(24, 0, "Roland FP", "MIDI 1", self.LECT, 130))
        self.assertTrue(em.es_fuente(128, 0, "Teclado Piano", "notas", self.LECT, 130))
        self.assertFalse(em.es_fuente(0, 1, "System", "Announce", self.LECT, 130))
        self.assertFalse(em.es_fuente(14, 0, "Midi Through", "Port-0", self.LECT, 130))
        self.assertFalse(em.es_fuente(142, 0, "PipeWire-System", "input", self.LECT, 130))
        self.assertFalse(em.es_fuente(130, 1, "Piano Enrutador", "salida", self.LECT, 130))
        self.assertFalse(em.es_fuente(24, 0, "X", "solo escritura", aseq.SEQ_PORT_CAP_WRITE, 130))
        self.assertFalse(em.es_fuente(24, 0, "X", "privado", self.LECT | aseq.SEQ_PORT_CAP_NO_EXPORT, 130))


class TestFuentes(unittest.TestCase):
    def setUp(self):
        self.e = em.Enrutador()

    def test_pc_siempre_y_nuevas_segun_auto(self):
        acc, _ = self.e.actualizar_fuentes({PC: (128, 0, "pc"), MIDI: (24, 0, "midi")})
        self.assertCountEqual(acc, [("suscribir", 128, 0), ("suscribir", 24, 0)])
        self.assertTrue(self.e.prefs["fuentes"][MIDI], "se recuerda la decisión para la nueva fuente")
        self.assertNotIn(PC, self.e.prefs["fuentes"])
        self.assertTrue(self.e.cambios_prefs)
        acc, _ = self.e.actualizar_fuentes({PC: (128, 0, "pc"), MIDI: (24, 0, "midi")})
        self.assertEqual(acc, [], "sin cambios no hay acciones")

    def test_auto_desactivado(self):
        self.e.prefs["auto_nuevas"] = False
        acc, _ = self.e.actualizar_fuentes({MIDI: (24, 0, "midi")})
        self.assertEqual(acc, [])
        self.assertFalse(self.e.prefs["fuentes"][MIDI])

    def test_desconexion_suelta_notas_y_reconexion(self):
        self.e.actualizar_fuentes({MIDI: (24, 0, "midi")})
        self.e.nota_on(MIDI, "midi", 0, 60, 100)
        acc, msgs = self.e.actualizar_fuentes({})
        self.assertEqual(msgs, [("off", 60, 0)], "al desenchufar no quedan notas colgadas")
        self.assertFalse(self.e.fuentes[MIDI]["conectada"])
        self.assertEqual(self.e.sonando, {})
        acc, _ = self.e.actualizar_fuentes({MIDI: (25, 0, "midi")})     # vuelve con otro nº de cliente
        self.assertEqual(acc, [("suscribir", 25, 0)])
        self.assertEqual(self.e.fuente_de(25, 0), (MIDI, "midi"))
        self.assertEqual(self.e.fuente_de(24, 0), (None, None))


class TestNotas(unittest.TestCase):
    def setUp(self):
        self.e = em.Enrutador()
        self.e.actualizar_fuentes({PC: (128, 0, "pc"), MIDI: (24, 0, "midi")})

    def test_transposicion_y_curva(self):
        self.e.orden("transponer =2")
        self.e.orden("curva dura")
        self.assertEqual(self.e.nota_on(PC, "pc", 0, 60, 80), [("on", 62, 80, 0)], "PC: sin curva")
        self.assertEqual(self.e.nota_on(MIDI, "midi", 0, 64, 64), [("on", 66, em.curva_fuerza(64, "dura"), 0)])
        self.assertEqual(self.e.ultima[0], 66)
        self.assertEqual(self.e.ultima[2], "Roland FP")

    def test_cambiar_transposicion_con_notas_pulsadas(self):
        self.e.nota_on(PC, "pc", 0, 60, 80)
        self.e.orden("transponer +1")
        self.assertEqual(self.e.nota_off(PC, 0, 60), [("off", 60, 0)], "se apaga la nota que realmente sonó")
        self.assertEqual(self.e.nota_on(PC, "pc", 0, 60, 80), [("on", 61, 80, 0)])

    def test_velocidad_cero_y_repulsacion(self):
        self.e.nota_on(MIDI, "midi", 0, 60, 90)
        self.assertEqual(self.e.nota_on(MIDI, "midi", 0, 60, 0), [("off", 60, 0)], "note on vel 0 = note off")
        self.e.nota_on(MIDI, "midi", 0, 60, 90)
        msgs = self.e.nota_on(MIDI, "midi", 0, 60, 90)
        self.assertEqual(msgs[0], ("off", 60, 0), "re-pulsación sin note off: se apaga primero")
        self.assertEqual(self.e.sonando, {60: 1})

    def test_fuera_de_rango(self):
        self.e.orden("transponer =12")
        self.assertEqual(self.e.nota_on(PC, "pc", 0, 120, 80), [])
        self.assertEqual(self.e.nota_off(PC, 0, 120), [])

    def test_misma_nota_desde_dos_fuentes(self):
        self.e.nota_on(PC, "pc", 0, 60, 80)
        self.e.nota_on(MIDI, "midi", 0, 60, 80)
        self.assertEqual(self.e.sonando, {60: 2})
        self.e.nota_off(PC, 0, 60)
        self.assertEqual(self.e.sonando, {60: 1}, "sigue sonando mientras la otra tecla está pulsada")
        self.e.nota_off(MIDI, 0, 60)
        self.assertEqual(self.e.sonando, {})

    def test_pedal_y_controles(self):
        self.assertEqual(self.e.control(0, 64, 127), [("cc", 64, 127, 0)])
        self.assertTrue(self.e.pedal)
        self.e.control(0, 64, 10)
        self.assertFalse(self.e.pedal)

    def test_panico(self):
        self.e.nota_on(PC, "pc", 0, 60, 80)
        self.e.nota_on(MIDI, "midi", 3, 64, 80)
        self.e.control(0, 64, 127)
        msgs = self.e.panico()
        self.assertIn(("off", 60, 0), msgs)
        self.assertIn(("off", 64, 3), msgs)
        for canal in (0, 3):
            for cc in (64, 123, 120):
                self.assertIn(("cc", cc, 0, canal), msgs)
        self.assertEqual((self.e.mapa, self.e.sonando, self.e.pedal), ({}, {}, False))


class TestOrdenes(unittest.TestCase):
    def setUp(self):
        self.e = em.Enrutador()
        self.e.actualizar_fuentes({PC: (128, 0, "pc"), MIDI: (24, 0, "midi")})
        self.e.cambios_prefs = False

    def test_transponer(self):
        self.e.orden("transponer +1")
        self.e.orden("transponer +1")
        self.assertEqual(self.e.prefs["transposicion"], 2)
        self.e.orden("transponer -1")
        self.assertEqual(self.e.prefs["transposicion"], 1)
        self.e.orden("transponer =-30")
        self.assertEqual(self.e.prefs["transposicion"], -12)
        self.e.orden("transponer 0")
        self.assertEqual(self.e.prefs["transposicion"], 0)
        self.assertTrue(self.e.cambios_prefs)

    def test_curva_ciclo(self):
        vistos = []
        for _ in range(4):
            self.e.orden("curva siguiente")
            vistos.append(self.e.prefs["curva"])
        self.assertEqual(vistos, ["dura", "suave", "normal", "dura"])

    def test_latencia(self):
        ef, _ = self.e.orden("latencia 256")
        self.assertEqual(ef, [("latencia", 256)])
        ef, _ = self.e.orden("latencia siguiente")
        self.assertEqual(ef, [("latencia", 512)])
        self.e.orden("latencia siguiente")
        ef, _ = self.e.orden("latencia siguiente")
        self.assertEqual(ef, [("latencia", 128)], "da la vuelta")
        self.assertEqual(self.e.orden("latencia 300"), ([], []))

    def test_reverb(self):
        ef, _ = self.e.orden("reverb +1")
        self.assertEqual(ef, [("reverb", 0.40)])
        self.e.orden("reverb 2")
        self.assertEqual(self.e.prefs["reverb"], 1.0)
        self.e.orden("reverb -5")
        self.assertEqual(self.e.prefs["reverb"], 0.0)
        self.assertEqual(self.e.orden("reverb mucho"), ([], []))

    def test_fuente_alternar_suelta_sus_notas(self):
        self.e.nota_on(MIDI, "midi", 0, 60, 90)
        ef, msgs = self.e.orden(f"fuente alternar {MIDI}")
        self.assertEqual(ef, [("desuscribir", 24, 0)])
        self.assertEqual(msgs, [("off", 60, 0)])
        self.assertFalse(self.e.prefs["fuentes"][MIDI])
        ef, _ = self.e.orden(f"fuente on {MIDI}")
        self.assertEqual(ef, [("suscribir", 24, 0)])
        self.assertEqual(self.e.orden("fuente alternar No:Existe"), ([], []))

    def test_auto(self):
        self.e.orden("auto off")
        self.assertFalse(self.e.prefs["auto_nuevas"])
        self.e.orden("auto")
        self.assertTrue(self.e.prefs["auto_nuevas"])

    def test_desconocidas_no_cambian_nada(self):
        for linea in ("", "   ", "volar alto", "transponer arriba", "curva rara"):
            self.assertEqual(self.e.orden(linea), ([], []))
        self.assertFalse(self.e.cambios_prefs)

    def test_estado(self):
        self.e.nota_on(PC, "pc", 0, 60, 80)
        e = self.e.estado({"xruns": 2})
        self.assertEqual([f["id"] for f in e["fuentes"]], [PC, MIDI], "el teclado de computador va primero")
        self.assertEqual(e["sonando"], [60])
        self.assertEqual(e["xruns"], 2)
        self.assertEqual(json.loads(json.dumps(e)), e, "serializable en JSON")


CABECERA = "S   ID  QUANT   RATE    WAIT    BUSY   W/Q   B/Q  ERR FORMAT           NAME"
FILA = "R   {id}      0      0   1.0ms   2.0ms  0.17  {bq}  {err}   F32LE 2 44100  + {nodo}"
G1 = "alsa_output.usb-Creative_Technology_Ltd_Sound_BlasterX_G1_00030790-00.analog-stereo"


class TestMonitorCortes(unittest.TestCase):
    def instantanea(self, m, **err_por_nodo):
        m.linea(CABECERA)
        for nodo, (err, bq) in err_por_nodo.items():
            m.linea(FILA.format(id=80, bq=bq, err=err, nodo=nodo.replace("_", "-") if nodo != "g1" else G1))

    def test_cuenta_y_reinicio_de_nodo(self):
        t = [100.0]
        m = em.MonitorCortes("piano-vivo", reloj=lambda: t[0])
        self.instantanea(m, piano_vivo=(7, "0.30"))
        self.instantanea(m)
        self.assertEqual((m.xruns, m.bq), (0, 0.30), "el valor inicial es la referencia")
        self.instantanea(m, piano_vivo=(9, "0.95"))
        self.instantanea(m)
        self.assertEqual(m.xruns, 2)
        t[0] = 103.0
        self.assertEqual(m.estado()["xrun_hace"], 3.0)
        self.instantanea(m, piano_vivo=(1, "0.20"))         # nodo reiniciado: su contador vuelve a 0
        self.instantanea(m, piano_vivo=(2, "0.20"))
        self.instantanea(m)
        self.assertEqual(m.xruns, 3)
        self.instantanea(m, piano_vivo_fx=(50, "0.9"))
        self.instantanea(m, piano_vivo_fx=(60, "0.9"))
        self.instantanea(m)
        self.assertEqual(m.xruns, 3, "un nodo no vigilado no cuenta (ni se confunde por el prefijo común)")

    def test_cortes_del_grafo_sin_contar_dos_veces(self):
        m = em.MonitorCortes(["piano-vivo", "piano-vivo-fx", G1])
        self.instantanea(m, g1=(10, "0.01"), piano_vivo=(3, "0.30"), piano_vivo_fx=(0, "0.02"))
        self.instantanea(m, g1=(11, "0.01"), piano_vivo=(3, "0.31"), piano_vivo_fx=(0, "0.02"))
        self.instantanea(m)
        self.assertEqual(m.xruns, 1, "un corte solo del reloj (la G1) también cuenta")
        self.assertEqual(m.tomar_eventos(), [(1, [G1])])
        self.instantanea(m, g1=(13, "0.01"), piano_vivo=(5, "0.95"), piano_vivo_fx=(1, "0.02"))
        self.instantanea(m)
        self.assertEqual(m.xruns, 3, "el mismo corte en varios nodos se cuenta una vez (el mayor incremento)")
        self.assertEqual(m.tomar_eventos(), [(2, sorted([G1, "piano-vivo", "piano-vivo-fx"]))])
        self.assertEqual(m.tomar_eventos(), [], "los eventos se entregan una sola vez")
        self.assertEqual(m.bq, 0.95, "la carga es la del nodo principal")


class TestCortesDelRegistro(unittest.TestCase):
    # Líneas reales del registro de PipeWire de la sesión del usuario (2026-10-19)
    GRAFO = ("pw.node: (" + G1 + "-69) graph xrun not-triggered (0 suppressed)")
    ESTADO = ("pw.node: (" + G1 + "-69) xrun state:0x7f97905008 pending:2/4 s:12045297950627 a:12045298733538 "
              "f:12045298809423 waiting:782911 process:75885 status:triggered")
    SEGUIDOR = ("pw.node: (piano-vivo-84) xrun state:0x7f94dd1008 pending:0/2 s:29090478373288 a:29090478414903 "
                "f:29090474755888 waiting:41615 process:18446744073705892601 status:awake")

    def test_cuenta_los_cortes_del_reloj_con_los_omitidos(self):
        t = [50.0]
        m = em.MonitorCortes(["piano-vivo", "piano-vivo-fx", G1], reloj=lambda: t[0], con_registro=True)
        m.linea_registro(self.GRAFO)
        m.linea_registro(self.ESTADO)
        m.linea_registro(self.SEGUIDOR)
        self.assertEqual(m.xruns, 1, "un corte = una línea «graph xrun»; las de detalle no cuentan")
        self.assertEqual(m.tomar_eventos(), [(1, [G1])])
        m.linea_registro(self.GRAFO.replace("(0 suppressed)", "(7 suppressed)"))
        self.assertEqual(m.xruns, 9, "PipeWire omitió 7 repeticiones: valen 1 + 7")
        t[0] = 52.0
        self.assertEqual(m.estado()["xrun_hace"], 2.0)

    def test_cambio_de_latencia_no_cuenta(self):
        pared = [1_792_000_000.0]
        m = em.MonitorCortes(["piano-vivo", G1], con_registro=True, reloj_pared=lambda: pared[0])
        m.pausa()                                            # F4 en t = 0
        hora = lambda dt: f"{pared[0] + dt:.6f} raspberrypi pipewire[902]: "
        m.linea_registro(hora(0.4) + self.GRAFO.replace("(0 suppressed)", "(5 suppressed)"))
        self.assertEqual((m.xruns, m.por_latencia), (0, 6), "los cortes de la reconfiguración se anotan aparte")
        self.assertEqual(m.tomar_eventos(), [])
        self.assertEqual(m.tomar_eventos_latencia(), [(6, [G1])])
        m.linea_registro(hora(em.PAUSA_LATENCIA + 0.5) + self.GRAFO)
        self.assertEqual(m.xruns, 1, "pasada la pausa, se cuenta")
        pared[0] += 30
        m.linea_registro(hora(-29.8) + self.GRAFO)
        self.assertEqual((m.xruns, m.por_latencia), (1, 7),
                         "lo decide la hora del aviso, no cuándo se lee (el registro puede llegar tarde)")
        self.assertEqual(m.estado()["xruns_por_latencia"], 7)

    def test_cambio_de_latencia_sin_registro(self):
        pared = [100.0]
        m = em.MonitorCortes("piano-vivo", reloj_pared=lambda: pared[0])

        def instantanea(err=None):
            m.linea(CABECERA)
            if err is not None:
                m.linea(FILA.format(id=80, bq="0.3", err=err, nodo="piano-vivo"))
        instantanea(1)
        m.pausa()
        instantanea(4)
        instantanea()
        self.assertEqual((m.xruns, m.por_latencia), (0, 3), "con pw-top también se anotan aparte")
        pared[0] += 5
        instantanea(5)
        instantanea()
        self.assertEqual(m.xruns, 1)

    def test_otros_relojes_no_cuentan(self):
        m = em.MonitorCortes(["piano-vivo", G1], con_registro=True)
        m.linea_registro("pw.node: (Dummy-Driver-30) graph xrun not-triggered (1 suppressed)")
        m.linea_registro("pw.node: (Midi-Bridge-38) graph xrun not-triggered (0 suppressed)")
        m.linea_registro("una línea cualquiera")
        self.assertEqual(m.xruns, 0)

    def test_con_registro_el_err_de_pw_top_no_se_suma(self):
        m = em.MonitorCortes(["piano-vivo", G1], con_registro=True)
        for err in (3, 5):
            m.linea(CABECERA)
            m.linea(FILA.format(id=80, bq="0.40", err=err, nodo="piano-vivo"))
        m.linea(CABECERA)
        self.assertEqual((m.xruns, m.bq), (0, 0.40), "pw-top solo aporta la carga (no contar dos veces)")


class TestLineaCorte(unittest.TestCase):
    def test_contexto(self):
        estado = {"instrumento": {"actual": {"id": "salamander", "nombre": "Salamander"}}, "pedal": True,
                  "sonando": [60, 62, 64]}
        t = em.linea_corte(2, ["piano-vivo", G1], 7, estado, 0.31, 61.6, 0x0)
        self.assertEqual(t, "CORTE +2 (total 7) | nodos: piano-vivo, " + G1 + " | instrumento salamander | "
                            "pedal sí | notas 3 | B/Q 0.31 | 62 °C | energía ok")
        self.assertTrue(em.linea_corte(1, ["x"], 1, estado, throttled=0x50005).endswith("BAJO VOLTAJE, CPU LIMITADA"))
        sin = em.linea_corte(1, ["x"], 1, {})
        self.assertIn("instrumento -", sin)
        self.assertIn("pedal no", sin)
        self.assertIn("B/Q ?", sin)
        self.assertIn("temp ?", sin)
        self.assertNotIn("energía", sin, "sin lectura de vcgencmd no se afirma nada")


if __name__ == "__main__":
    unittest.main()
