"""Acceso mínimo al secuenciador ALSA mediante ctypes (libasound del sistema; sin dependencias).

Incluye: snd_seq_event_t, construcción de eventos, un cliente con puertos de entrada/salida,
enumeración de clientes/puertos, suscripciones y lectura no bloqueante de eventos.
"""
import ctypes
import struct


class _Direccion(ctypes.Structure):
    _fields_ = [("client", ctypes.c_ubyte), ("port", ctypes.c_ubyte)]


class EventoSeq(ctypes.Structure):
    """snd_seq_event_t (28 bytes)."""
    _fields_ = [("type", ctypes.c_ubyte), ("flags", ctypes.c_ubyte), ("tag", ctypes.c_ubyte),
                ("queue", ctypes.c_ubyte), ("time", ctypes.c_uint * 2),
                ("source", _Direccion), ("dest", _Direccion), ("data", ctypes.c_ubyte * 12)]


SEQ_EVENT_NOTE, SEQ_EVENT_NOTEON, SEQ_EVENT_NOTEOFF, SEQ_EVENT_KEYPRESS = 5, 6, 7, 8
SEQ_EVENT_CONTROLLER, SEQ_EVENT_PGMCHANGE, SEQ_EVENT_CHANPRESS, SEQ_EVENT_PITCHBEND = 10, 11, 12, 13
SEQ_EVENT_LENGTH_MASK, SEQ_EVENT_LENGTH_FIXED = 3 << 2, 0
SEQ_QUEUE_DIRECT, SEQ_ADDRESS_SUBSCRIBERS, SEQ_ADDRESS_UNKNOWN = 253, 254, 253
SEQ_OPEN_OUTPUT, SEQ_OPEN_INPUT, SEQ_OPEN_DUPLEX = 1, 2, 3
SEQ_PORT_CAP_READ, SEQ_PORT_CAP_WRITE = 1 << 0, 1 << 1
SEQ_PORT_CAP_SUBS_READ, SEQ_PORT_CAP_SUBS_WRITE = 1 << 5, 1 << 6
SEQ_PORT_CAP_NO_EXPORT = 1 << 7
SEQ_PORT_TYPE_MIDI_GENERIC, SEQ_PORT_TYPE_APPLICATION = 1 << 1, 1 << 20
SEQ_KERNEL_CLIENT = 2           # snd_seq_client_type_t: SND_SEQ_USER_CLIENT=1, SND_SEQ_KERNEL_CLIENT=2
POLLIN = 0x001
EAGAIN = 11


def construir_evento(msg, puerto, canal=0):
    """("on", nota, vel) | ("off", nota) | ("cc", control, valor) -> snd_seq_event_t para los suscriptores."""
    ev = EventoSeq()
    ev.flags = 0
    ev.queue = SEQ_QUEUE_DIRECT
    ev.source.port = puerto
    ev.dest.client, ev.dest.port = SEQ_ADDRESS_SUBSCRIBERS, SEQ_ADDRESS_UNKNOWN
    d = ev.data
    if msg[0] in ("on", "off"):
        ev.type = SEQ_EVENT_NOTEON if msg[0] == "on" else SEQ_EVENT_NOTEOFF
        d[0], d[1] = canal, msg[1]
        d[2] = msg[2] if msg[0] == "on" else 0
    elif msg[0] == "cc":
        ev.type = SEQ_EVENT_CONTROLLER
        d[0] = canal
        struct.pack_into("<Ii", d, 4, msg[1], msg[2])
    else:
        raise ValueError(f"mensaje no enviable: {msg!r}")
    return ev


def control_de(ev):
    """(param, valor) de un evento CONTROLLER."""
    return struct.unpack_from("<Ii", bytes(ev.data), 4)


class _PollFd(ctypes.Structure):
    _fields_ = [("fd", ctypes.c_int), ("events", ctypes.c_short), ("revents", ctypes.c_short)]


class ClienteSeq:
    """Cliente del secuenciador. modo: SEQ_OPEN_OUTPUT / INPUT / DUPLEX."""

    def __init__(self, nombre, modo=SEQ_OPEN_OUTPUT, no_bloqueante=False):
        self.lib = ctypes.CDLL("libasound.so.2")
        L = self.lib
        L.snd_seq_event_output_direct.argtypes = [ctypes.c_void_p, ctypes.POINTER(EventoSeq)]
        L.snd_seq_event_input.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(EventoSeq))]
        for f in ("snd_seq_client_info_get_name", "snd_seq_port_info_get_name"):
            getattr(L, f).restype = ctypes.c_char_p
        for f in ("snd_seq_client_info_malloc", "snd_seq_port_info_malloc"):
            getattr(L, f).argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        for f in ("snd_seq_client_info_get_client", "snd_seq_client_info_get_type",
                  "snd_seq_client_info_get_name", "snd_seq_port_info_get_port", "snd_seq_port_info_get_name",
                  "snd_seq_port_info_get_capability", "snd_seq_port_info_get_type",
                  "snd_seq_client_info_free", "snd_seq_port_info_free"):
            getattr(L, f).argtypes = [ctypes.c_void_p]
        L.snd_seq_port_info_get_capability.restype = ctypes.c_uint
        L.snd_seq_port_info_get_type.restype = ctypes.c_uint
        L.snd_seq_client_info_set_client.argtypes = [ctypes.c_void_p, ctypes.c_int]
        L.snd_seq_port_info_set_client.argtypes = [ctypes.c_void_p, ctypes.c_int]
        L.snd_seq_port_info_set_port.argtypes = [ctypes.c_void_p, ctypes.c_int]
        L.snd_seq_query_next_client.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        L.snd_seq_query_next_port.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.h = ctypes.c_void_p()
        if L.snd_seq_open(ctypes.byref(self.h), b"default", modo, 0) < 0:
            raise OSError("no se pudo abrir el secuenciador ALSA")
        L.snd_seq_set_client_name(self.h, nombre.encode())
        if no_bloqueante:
            L.snd_seq_nonblock(self.h, 1)
        self.cliente = L.snd_seq_client_id(self.h)

    # Puertos
    def puerto_salida(self, nombre):
        p = self.lib.snd_seq_create_simple_port(self.h, nombre.encode(), SEQ_PORT_CAP_READ | SEQ_PORT_CAP_SUBS_READ,
                                                SEQ_PORT_TYPE_MIDI_GENERIC | SEQ_PORT_TYPE_APPLICATION)
        if p < 0:
            raise OSError("no se pudo crear el puerto de salida")
        return p

    def puerto_entrada(self, nombre, privado=False):
        cap = SEQ_PORT_CAP_WRITE | SEQ_PORT_CAP_SUBS_WRITE | (SEQ_PORT_CAP_NO_EXPORT if privado else 0)
        p = self.lib.snd_seq_create_simple_port(self.h, nombre.encode(), cap,
                                                SEQ_PORT_TYPE_MIDI_GENERIC | SEQ_PORT_TYPE_APPLICATION)
        if p < 0:
            raise OSError("no se pudo crear el puerto de entrada")
        return p

    # Envío
    def enviar_evento(self, ev):
        r = self.lib.snd_seq_event_output_direct(self.h, ctypes.byref(ev))
        if r < 0:
            raise OSError(f"error al enviar MIDI ({r})")

    def enviar(self, msg, puerto, canal=0):
        self.enviar_evento(construir_evento(msg, puerto, canal))

    # Recepción
    def descriptores(self):
        n = self.lib.snd_seq_poll_descriptors_count(self.h, POLLIN)
        arr = (_PollFd * n)()
        self.lib.snd_seq_poll_descriptors(self.h, arr, n, POLLIN)
        return [arr[i].fd for i in range(n)]

    def leer_eventos(self):
        """Eventos pendientes (copias). Requiere modo no bloqueante."""
        eventos = []
        while True:
            p = ctypes.POINTER(EventoSeq)()
            r = self.lib.snd_seq_event_input(self.h, ctypes.byref(p))
            if r < 0 or not p:
                break                                   # -EAGAIN: no hay más
            ev = EventoSeq()
            ctypes.memmove(ctypes.byref(ev), p, ctypes.sizeof(EventoSeq))
            eventos.append(ev)
            if r == 0 and self.lib.snd_seq_event_input_pending(self.h, 0) == 0:
                break
        return eventos

    # Suscripciones (en nombre de un puerto propio de entrada)
    def conectar_desde(self, puerto_propio, cliente, puerto):
        return self.lib.snd_seq_connect_from(self.h, puerto_propio, cliente, puerto) == 0

    def desconectar_desde(self, puerto_propio, cliente, puerto):
        return self.lib.snd_seq_disconnect_from(self.h, puerto_propio, cliente, puerto) == 0

    # Enumeración: [(cliente, puerto, nombre_cliente, nombre_puerto, capacidades, tipo_cliente)]
    def puertos(self):
        L = self.lib
        ci, pi = ctypes.c_void_p(), ctypes.c_void_p()
        L.snd_seq_client_info_malloc(ctypes.byref(ci))
        L.snd_seq_port_info_malloc(ctypes.byref(pi))
        res = []
        try:
            L.snd_seq_client_info_set_client(ci, -1)
            while L.snd_seq_query_next_client(self.h, ci) >= 0:
                c = L.snd_seq_client_info_get_client(ci)
                nombre_c = (L.snd_seq_client_info_get_name(ci) or b"").decode("utf-8", "replace")
                tipo = L.snd_seq_client_info_get_type(ci)
                L.snd_seq_port_info_set_client(pi, c)
                L.snd_seq_port_info_set_port(pi, -1)
                while L.snd_seq_query_next_port(self.h, pi) >= 0:
                    res.append((c, L.snd_seq_port_info_get_port(pi),
                                nombre_c, (L.snd_seq_port_info_get_name(pi) or b"").decode("utf-8", "replace"),
                                L.snd_seq_port_info_get_capability(pi), tipo))
        finally:
            L.snd_seq_client_info_free(ci)
            L.snd_seq_port_info_free(pi)
        return res

    def cerrar(self):
        if self.h:
            self.lib.snd_seq_close(self.h)
            self.h = ctypes.c_void_p()
