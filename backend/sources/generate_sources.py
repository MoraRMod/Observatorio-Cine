"""CAPA 1 · FUENTES DE DATOS (simuladas).

Genera las exportaciones de los "sistemas operacionales" de una cadena de cines:

* catalogos/*.json            -> sistema maestro (complejos, salas, películas, productos,
                                 promociones, canales)
* programacion/funciones_YYYY-MM.csv     -> sistema de programación + control de acceso
* taquilla/ventas_boletos_YYYY-MM.csv     -> punto de venta de taquilla (por función y canal)
* dulceria/ventas_dulceria_YYYY-MM.csv    -> punto de venta de dulcería (por día, producto y canal)

Todo es SINTÉTICO y reproducible: cada mes se genera con generadores pseudoaleatorios
sembrados con (SEED, mes, complejo), por lo que generar un mes de forma aislada produce
exactamente el mismo archivo que generarlo junto con el resto del histórico.

Los archivos incluyen, a propósito, una pequeña proporción de registros "sucios"
(duplicados, fechas inválidas, canales escritos de distintas formas, claves huérfanas,
precios faltantes) para que el proceso ETL tenga trabajo real de limpieza.

Uso:
    python -m backend.sources.generate_sources            # histórico 2023-01 a 2025-12
    python -m backend.sources.generate_sources --siguiente  # agrega el siguiente mes
"""
import argparse
import csv
import json
import math
import random
from datetime import date, timedelta

import numpy as np

from backend import calendario as cal
from backend.config import HIST_END, HIST_START, MAX_SIM_MONTH, SEED, SOURCES_DIR

# ---------------------------------------------------------------------------
# Catálogos maestros
# ---------------------------------------------------------------------------
# Ciudades reales; nombres de complejos FICTICIOS.
COMPLEJOS = [
    # código, nombre, ciudad, estado, región, tipo, apertura, crecimiento anual, factor demanda
    ("C01", "Complejo Reforma Centro", "Ciudad de México", "Ciudad de México", "Centro", "Premium", "2012-05-10", 0.035, 1.25),
    ("C02", "Complejo Coyoacán Sur", "Ciudad de México", "Ciudad de México", "Centro", "Tradicional", "2009-03-01", 0.015, 1.10),
    ("C03", "Complejo Azcapotzalco Norte", "Ciudad de México", "Ciudad de México", "Centro", "Tradicional", "2006-08-20", -0.09, 0.95),
    ("C04", "Complejo Andares Poniente", "Guadalajara", "Jalisco", "Occidente", "Premium", "2014-11-15", 0.045, 1.15),
    ("C05", "Complejo Tlaquepaque Plaza", "Guadalajara", "Jalisco", "Occidente", "Tradicional", "2010-06-01", 0.0, 0.95),
    ("C06", "Complejo Valle Oriente", "Monterrey", "Nuevo León", "Noreste", "Premium", "2013-09-05", 0.05, 1.20),
    ("C07", "Complejo Cumbres", "Monterrey", "Nuevo León", "Noreste", "Tradicional", "2011-02-14", 0.02, 1.00),
    ("C08", "Complejo Atlixcáyotl", "Puebla", "Puebla", "Centro", "Premium", "2015-04-22", 0.03, 1.00),
    ("C09", "Complejo Centro Sur Querétaro", "Querétaro", "Querétaro", "Bajío", "Tradicional", "2012-10-01", 0.04, 0.95),
    ("C10", "Complejo Montejo", "Mérida", "Yucatán", "Sureste", "Premium", "2016-07-08", 0.06, 1.05),
    ("C11", "Complejo Tres Marías", "Morelia", "Michoacán", "Occidente", "Premium", "2017-03-30", 0.025, 0.95),
    ("C12", "Complejo Centro Histórico Morelia", "Morelia", "Michoacán", "Occidente", "Tradicional", "2005-12-01", -0.02, 0.80),
    ("C13", "Complejo Zona Río", "Tijuana", "Baja California", "Noroeste", "Tradicional", "2010-09-17", 0.01, 0.95),
    ("C14", "Complejo Juriquilla Norte", "Querétaro", "Querétaro", "Bajío", "Premium", "2024-03-01", 0.08, 1.05),
]
# Configuración de salas por complejo (formatos públicos de la cadena: Tradicional,
# Macro XE, IMAX, 4DX, VIP y Junior).  Capacidades supuestas.
SALAS = {
    "C01": ["IMAX", "4DX", "VIP", "VIP", "Macro XE", "Tradicional", "Tradicional", "Tradicional", "Tradicional"],
    "C02": ["Macro XE", "Tradicional", "Tradicional", "Tradicional", "Tradicional", "Junior"],
    "C03": ["Tradicional", "Tradicional", "Tradicional", "Tradicional", "Tradicional"],
    "C04": ["IMAX", "VIP", "VIP", "4DX", "Tradicional", "Tradicional", "Tradicional", "Junior"],
    "C05": ["Macro XE", "Tradicional", "Tradicional", "Tradicional", "Tradicional", "Tradicional"],
    "C06": ["IMAX", "4DX", "VIP", "VIP", "Tradicional", "Tradicional", "Tradicional", "Tradicional"],
    "C07": ["Macro XE", "Tradicional", "Tradicional", "Tradicional", "Tradicional", "Junior"],
    "C08": ["Macro XE", "VIP", "4DX", "Tradicional", "Tradicional", "Tradicional"],
    "C09": ["Macro XE", "Tradicional", "Tradicional", "Tradicional", "Tradicional", "Tradicional"],
    "C10": ["IMAX", "VIP", "VIP", "Tradicional", "Tradicional", "Tradicional", "Tradicional"],
    "C11": ["Macro XE", "VIP", "VIP", "4DX", "Tradicional", "Tradicional", "Tradicional"],
    "C12": ["Tradicional", "Tradicional", "Tradicional", "Tradicional", "Tradicional"],
    "C13": ["Macro XE", "Tradicional", "Tradicional", "Tradicional", "Tradicional", "Junior"],
    "C14": ["Macro XE", "VIP", "4DX", "Tradicional", "Tradicional", "Tradicional"],
}
CAPACIDAD = {"Tradicional": (120, 210), "Macro XE": (240, 320), "IMAX": (300, 380),
             "4DX": (100, 140), "VIP": (40, 60), "Junior": (70, 90)}
# Precio de lista 2023 (MXN, entre semana) por formato; supuesto.
PRECIO_FORMATO = {"Tradicional": 62, "Macro XE": 80, "IMAX": 112, "4DX": 128, "VIP": 158, "Junior": 76}
DEMANDA_FORMATO = {"Tradicional": 1.0, "Macro XE": 0.92, "IMAX": 0.88, "4DX": 0.85, "VIP": 1.15, "Junior": 0.9}
FACTOR_CIUDAD = {"Ciudad de México": 1.10, "Monterrey": 1.08, "Guadalajara": 1.05, "Tijuana": 1.05,
                 "Querétaro": 1.00, "Puebla": 0.97, "Mérida": 0.97, "Morelia": 0.93}
INFLACION_BOLETO = {2023: 1.0, 2024: 1.05, 2025: 1.097, 2026: 1.14}
INFLACION_DULCERIA = {2023: 1.0, 2024: 1.06, 2025: 1.12, 2026: 1.18}
# Factor de mercado por año (2024 menor por la menor oferta de estrenos tras las huelgas
# de Hollywood de 2023; supuesto inspirado en la caída reportada por CANACINE).
FACTOR_ANIO = {2023: 1.0, 2024: 0.86, 2025: 0.85, 2026: 0.87}

GENEROS = {  # peso de aparición, multiplicador de potencial, decaimiento semanal, duración
    "Acción": (14, 1.25, 0.64, (105, 150)), "Animación": (10, 1.35, 0.80, (85, 105)),
    "Aventura": (8, 1.15, 0.70, (100, 145)), "Ciencia ficción": (7, 1.10, 0.66, (105, 160)),
    "Comedia": (14, 0.85, 0.72, (88, 115)), "Drama": (12, 0.60, 0.78, (100, 150)),
    "Familiar": (6, 1.05, 0.78, (90, 115)), "Romance": (7, 0.65, 0.70, (92, 125)),
    "Suspenso": (9, 0.80, 0.66, (95, 130)), "Terror": (10, 0.85, 0.57, (85, 110)),
    "Documental": (3, 0.30, 0.75, (80, 110)),
}
CLASIFICACION = {"Acción": ["B", "B15"], "Animación": ["AA", "A"], "Aventura": ["A", "B"],
                 "Ciencia ficción": ["B", "B15"], "Comedia": ["A", "B", "B15"], "Drama": ["B", "B15", "C"],
                 "Familiar": ["AA", "A"], "Romance": ["B", "B15"], "Suspenso": ["B15", "C"],
                 "Terror": ["B15", "C"], "Documental": ["A", "B"]}
DISTRIBUIDORAS = ["Galaxia Films", "Horizonte Distribución", "Lumen Pictures", "Altamar Pictures",
                  "Faro Cine", "Raíz Films (nacional)", "Cometa Entertainment"]

PRODUCTOS = [  # sku, nombre, categoría, precio 2023, % costo, unidades por asistente, solo VIP
    ("P01", "Palomitas chicas", "Palomitas", 65, .12, .050, False),
    ("P02", "Palomitas medianas", "Palomitas", 82, .12, .070, False),
    ("P03", "Palomitas grandes", "Palomitas", 98, .11, .060, False),
    ("P04", "Palomitas jumbo", "Palomitas", 115, .11, .030, False),
    ("P05", "Palomitas de caramelo", "Palomitas", 105, .20, .020, False),
    ("B01", "Refresco chico", "Bebidas", 52, .15, .050, False),
    ("B02", "Refresco mediano", "Bebidas", 62, .14, .070, False),
    ("B03", "Refresco grande", "Bebidas", 72, .13, .060, False),
    ("B04", "Bebida congelada", "Bebidas", 68, .18, .040, False),
    ("B05", "Agua embotellada", "Bebidas", 38, .30, .050, False),
    ("B06", "Café americano", "Bebidas", 45, .20, .020, False),
    ("B07", "Frappé", "Bebidas", 75, .28, .020, False),
    ("A01", "Nachos con queso", "Alimentos", 85, .35, .060, False),
    ("A02", "Hot dog", "Alimentos", 75, .38, .040, False),
    ("A03", "Baguette", "Alimentos", 105, .40, .015, False),
    ("A04", "Pizza individual", "Alimentos", 120, .38, .015, False),
    ("A05", "Papas a la francesa", "Alimentos", 78, .30, .020, False),
    ("A06", "Crepa", "Alimentos", 95, .35, .010, False),
    ("D01", "Chocolate", "Dulces", 45, .50, .030, False),
    ("D02", "Gomitas", "Dulces", 42, .45, .030, False),
    ("D03", "Cacahuates enchilados", "Dulces", 38, .40, .015, False),
    ("D04", "Paleta helada", "Dulces", 48, .45, .015, False),
    ("K01", "Combo individual", "Combos", 135, .22, .050, False),
    ("K02", "Combo pareja", "Combos", 225, .22, .060, False),
    ("K03", "Combo familiar", "Combos", 320, .22, .020, False),
    ("K04", "Combo infantil", "Combos", 115, .30, .020, False),
    ("V01", "Cerveza", "VIP", 85, .35, .250, True),
    ("V02", "Postre gourmet", "VIP", 95, .40, .120, True),
]
ATTACH_SCALE = 0.66   # calibra el gasto promedio por asistente en dulcería

PROMOCIONES = [  # código, nombre, tipo, % descuento, inicio, fin
    ("SINPROMO", "Sin promoción", "Ninguna", 0.0, "2023-01-01", "2026-12-31"),
    ("MIERCOLES", "Miércoles de descuento", "Día de la semana", 0.35, "2023-01-01", "2026-12-31"),
    ("MATINE", "Matiné entre semana", "Horario", 0.20, "2023-01-01", "2026-12-31"),
    ("SEMCINE24", "Semana del cine a precio especial 2024", "Evento temporal", 0.50, "2024-09-23", "2024-09-29"),
    ("SEMCINE25", "Semana del cine a precio especial 2025", "Evento temporal", 0.50, "2025-09-22", "2025-09-28"),
]
CANALES = [  # código, nombre, tipo, boletos, dulcería
    ("TAQ", "Taquilla", "Presencial", True, False),
    ("KIO", "Kiosko de autoservicio", "Presencial", True, False),
    ("APP", "Aplicación móvil", "Digital", True, True),
    ("WEB", "Página web", "Digital", True, False),
    ("MOS", "Mostrador de dulcería", "Presencial", False, True),
    ("SAL", "Servicio en sala (VIP)", "Presencial", False, True),
]
# Nombre con el que cada canal aparece en las exportaciones (y variantes "sucias").
CANAL_EXPORT = {"TAQ": "Taquilla", "KIO": "Kiosko", "APP": "App", "WEB": "Web",
                "MOS": "Mostrador", "SAL": "Servicio en sala"}
CANAL_VARIANTES = {"TAQ": ["taquilla", "TAQUILLA ", " Taquilla"], "KIO": ["kiosko", "Kiosco", "KIOSKO"],
                   "APP": ["app", "Aplicacion", "APLICACIÓN MÓVIL"], "WEB": ["web", "Pagina Web", "WEB "],
                   "MOS": ["mostrador", "MOSTRADOR", "Dulceria"], "SAL": ["servicio en sala", "SALA VIP"]}

TITULO_A = ["El último", "La ciudad", "Más allá del", "Sombras de", "El secreto de", "La noche del",
            "Hijos del", "El regreso del", "La leyenda del", "Ecos del", "El guardián del", "Cartas desde el",
            "La rebelión del", "Bajo el", "Memorias del", "El código del", "La isla del", "Fuego en el"]
TITULO_B = ["faro", "desierto", "volcán", "abismo", "océano", "invierno", "jaguar", "eclipse", "laberinto",
            "horizonte", "bosque", "cometa", "silencio", "río", "imperio", "puerto", "viento", "relámpago",
            "espejo", "andén", "colibrí", "huracán", "glaciar", "barrio"]


def _rng(*parts) -> random.Random:
    return random.Random("-".join(str(p) for p in (SEED,) + parts))


def build_catalogs() -> dict:
    """Construye los catálogos maestros de forma determinística."""
    r = _rng("catalogos")
    complejos = [dict(codigo=c, nombre=n, ciudad=ci, estado=e, region=rg, tipo_complejo=t,
                      fecha_apertura=a, num_salas=len(SALAS[c])) for c, n, ci, e, rg, t, a, *_ in COMPLEJOS]
    salas = []
    for c, *_ in COMPLEJOS:
        for i, fmt in enumerate(SALAS[c], start=1):
            lo, hi = CAPACIDAD[fmt]
            salas.append(dict(codigo=f"{c}-S{i:02d}", complejo=c, numero=i, formato=fmt,
                              capacidad=int(r.randint(lo, hi) // 2 * 2)))
    # Películas: estrenos en jueves desde oct-2022 hasta dic-2026
    peliculas, hidden = [], {}
    used = set()
    d = date(2022, 10, 6)
    gen_names, gen_w = list(GENEROS), [g[0] for g in GENEROS.values()]
    n = 0
    while d <= date(2026, 12, 31):
        peak = d.month in (4, 5, 6, 7, 11, 12)
        lam = 1.15 if peak else 0.78
        for _ in range(sum(r.random() < lam / 3 for _ in range(3))):
            n += 1
            genero = r.choices(gen_names, gen_w)[0]
            _, gmult, gdecay, (dmin, dmax) = GENEROS[genero]
            pot = math.exp(r.gauss(-0.30, 0.80)) * gmult * (1.35 if peak else 0.9)
            if d.year == 2024:
                pot *= 0.88
            perceived = pot * math.exp(r.gauss(0, 0.35))
            tipo = ("Blockbuster" if perceived > 2.4 else "Comercial" if perceived > 0.85
                    else "Independiente / Nacional" if perceived > 0.4 else "Arte y ensayo")
            while True:
                titulo = f"{r.choice(TITULO_A)} {r.choice(TITULO_B)}"
                if r.random() < 0.08:
                    titulo += " 2"
                if titulo not in used:
                    used.add(titulo)
                    break
            dist = "Raíz Films (nacional)" if tipo == "Independiente / Nacional" and r.random() < .6 else r.choice(DISTRIBUIDORAS)
            codigo = f"PEL{n:04d}"
            peliculas.append(dict(codigo=codigo, titulo=titulo.capitalize() if titulo[0].islower() else titulo,
                                  genero=genero, clasificacion=r.choice(CLASIFICACION[genero]),
                                  duracion_min=r.randint(dmin, dmax), fecha_estreno=d.isoformat(),
                                  distribuidora=dist, tipo_lanzamiento=tipo))
            # Variables ocultas: NO se exportan (son la "verdad" del simulador).
            hidden[codigo] = dict(potencial=pot, decay=min(.9, max(.45, gdecay + r.gauss(0, .05))))
        d += timedelta(days=7)
    productos = []
    for sku, nom, cat, precio, pct, attach, vip in PRODUCTOS:
        precios = {str(y): round(precio * f) for y, f in INFLACION_DULCERIA.items()}
        costos = {y: round(p * pct * (1 + .01 * (int(y) - 2023)), 2) for y, p in precios.items()}
        productos.append(dict(sku=sku, nombre=nom, categoria=cat, precio_lista=precios,
                              costo_unitario=costos, exclusivo_vip=vip))
    promociones = [dict(codigo=c, nombre=n, tipo=t, descuento_pct=p, vigencia_inicio=i, vigencia_fin=f)
                   for c, n, t, p, i, f in PROMOCIONES]
    canales = [dict(codigo=c, nombre=n, tipo=t, vende_boletos=b, vende_dulceria=du) for c, n, t, b, du in CANALES]
    return dict(complejos=complejos, salas=salas, peliculas=peliculas, productos=productos,
                promociones=promociones, canales=canales, _hidden=hidden)


def write_catalogs(cat: dict) -> None:
    out = SOURCES_DIR / "catalogos"
    out.mkdir(parents=True, exist_ok=True)
    for name in ("complejos", "salas", "peliculas", "productos", "promociones", "canales"):
        (out / f"{name}.json").write_text(json.dumps(cat[name], ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Reglas de demanda
# ---------------------------------------------------------------------------
DOW = [0.62, 0.68, 0.72, 0.80, 1.15, 1.55, 1.35]
MES = [0, 0.95, 0.80, 0.88, 1.03, 1.00, 1.02, 1.22, 1.10, 0.80, 0.90, 0.98, 1.12]
BASE = 0.45


def hour_factor(minutes: int, weekend: bool, vacation: bool) -> float:
    h = minutes / 60
    if h < 13:
        f = .42
    elif h < 15:
        f = .62
    elif h < 17:
        f = .85
    elif h < 19:
        f = 1.05
    elif h < 21.25:
        f = 1.30
    elif h < 22:
        f = .95
    else:
        f = .68
    if (weekend or vacation) and h < 17:
        f *= 1.35
    return f


def genre_season(genero: str, d: date, vacation) -> float:
    f = 1.0
    if genero == "Terror" and (d.month == 10 or (d.month == 11 and d.day <= 3)):
        f *= 1.45
    if genero == "Romance" and d.month == 2:
        f *= 1.30
    if genero in ("Animación", "Familiar") and vacation:
        f *= 1.35
    if genero == "Drama" and d.month in (1, 2):
        f *= 1.15
    return f


def day_factor(d: date) -> float:
    vac = cal.vacation_name(d)
    hol = cal.holidays(d.year)
    f = DOW[d.weekday()]
    if vac and d.weekday() < 5:
        f = f + (1.25 - f) * 0.55
    f *= MES[d.month] * (1.10 if vac else 1.0)
    if d in hol and d.weekday() < 5:
        f *= 1.35
    if cal.is_long_weekend(d):
        f *= 1.12
    if d.month == 12 and d.day in (24, 31):
        f *= 0.45
    if d.month == 1 and d.day == 1:
        f *= 0.80
    return f


def complex_trend(code: str, d: date) -> float:
    info = next(c for c in COMPLEJOS if c[0] == code)
    years = (d - date(2023, 1, 1)).days / 365.25
    f = FACTOR_ANIO[d.year] * (1 + info[7]) ** years * info[8]
    if code == "C07" and d >= date(2025, 8, 1):      # remodelación de la plaza comercial (supuesto)
        f *= 0.80
    if code == "C14":                                 # apertura con rampa de 4 meses
        months_open = (d - date(2024, 3, 1)).days / 30.4
        f *= min(1.0, 0.65 + 0.35 * months_open / 4)
    return f


def channel_shares(d: date, vip: bool) -> np.ndarray:
    """Participación de canales de boletos: TAQ, KIO, APP, WEB (digitalización gradual)."""
    t = min(1.0, max(0.0, (d - date(2023, 1, 1)).days / 1095))
    s = np.array([0.46 - 0.15 * t, 0.12 + 0.03 * t, 0.28 + 0.13 * t, 0.14 - 0.01 * t])
    if vip:
        s = s * np.array([0.6, 0.7, 1.5, 1.2])
    return s / s.sum()


def promo_for(d: date, minutes: int) -> str:
    for code, _, _, _, ini, fin in PROMOCIONES[3:]:
        if ini <= d.isoformat() <= fin:
            return code
    if d.weekday() == 2:
        return "MIERCOLES"
    if d.weekday() < 5 and minutes < 14 * 60 and not cal.vacation_name(d) and d not in cal.holidays(d.year):
        return "MATINE"
    return "SINPROMO"


PROMO_UPLIFT = {"SINPROMO": 1.0, "MIERCOLES": 1.40, "MATINE": 1.15, "SEMCINE24": 2.1, "SEMCINE25": 2.1}
PROMO_PCT = {p[0]: p[3] for p in PROMOCIONES}


# ---------------------------------------------------------------------------
# Programación semanal
# ---------------------------------------------------------------------------
def _week_start(d: date) -> date:
    return d - timedelta(days=(d.weekday() - 3) % 7)   # semanas cinematográficas inician en jueves


def schedule_week(code: str, ws: date, cat: dict, salas: list) -> dict:
    """Asigna una película por sala para la semana (las salas grandes reciben los títulos fuertes)."""
    r = _rng("prog", code, ws.isoformat())
    hidden = cat["_hidden"]
    active = []
    for p in cat["peliculas"]:
        rel = date.fromisoformat(p["fecha_estreno"])
        w = (ws - rel).days // 7
        if 0 <= w <= 11:
            h = hidden[p["codigo"]]
            score = h["potencial"] * h["decay"] ** w * genre_season(p["genero"], ws, cal.vacation_name(ws))
            score *= math.exp(r.gauss(0, 0.15))   # criterio del programador del complejo
            active.append([score, p])
    active.sort(key=lambda x: -x[0])
    active = active[: len(salas) + 4]
    weights = {p["codigo"]: s for s, p in active}
    plan = {}
    for sala in sorted(salas, key=lambda s: -s["capacidad"]):
        pool = active
        if sala["formato"] == "Junior":
            pool = [a for a in active if a[1]["clasificacion"] in ("AA", "A")] or active
        if not pool:
            continue
        w = [weights[a[1]["codigo"]] * (1.6 if sala["formato"] in ("IMAX", "4DX", "Macro XE") and
                                         a[1]["genero"] in ("Acción", "Aventura", "Ciencia ficción", "Animación") else 1)
             for a in pool]
        chosen = r.choices(pool, w)[0][1]
        weights[chosen["codigo"]] *= 0.45
        plan[sala["codigo"]] = [chosen] + [a[1] for a in active[:6]]
    return plan


def sala_slots(sala_idx: int, formato: str, d: date) -> list:
    """Horarios de inicio (minutos desde medianoche) de una sala en un día."""
    offset = (sala_idx * 23) % 110
    start = (13 * 60 if formato == "VIP" else 11 * 60) + offset
    last = 19 * 60 if formato == "Junior" else 22 * 60 + 40
    slots, t = [], start
    while t <= last:
        slots.append(int(round(t / 5) * 5))
        t += 165 if formato != "VIP" else 180
    busy = d.weekday() >= 5 or cal.vacation_name(d) or d in cal.holidays(d.year)
    if not busy:
        slots = [s for s in slots if s >= 14 * 60] or slots[-2:]
        if sala_idx % 3 == 0 and len(slots) < 4:
            slots = [12 * 60 + offset // 2] + slots   # una matiné por cada tres salas
    return slots


# ---------------------------------------------------------------------------
# Generación de un mes
# ---------------------------------------------------------------------------
def generate_month(year: int, month: int, cat: dict) -> dict:
    hidden = cat["_hidden"]
    pel = {p["codigo"]: p for p in cat["peliculas"]}
    prod_by_sku = {p["sku"]: p for p in cat["productos"]}
    first = date(year, month, 1)
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    funciones, boletos, dulceria = [], [], []
    for ci, c in enumerate(COMPLEJOS):
        code, city = c[0], c[2]
        opening = date.fromisoformat(c[6])
        salas = [s for s in cat["salas"] if s["complejo"] == code]
        has_vip = any(s["formato"] == "VIP" for s in salas)
        g = np.random.default_rng([SEED, year, month, ci])
        pref = {p[0]: math.exp(g.normal(0, 0.15)) for p in PRODUCTOS}   # preferencias locales
        plans = {}
        d = first
        while d <= last:
            if d < opening:
                d += timedelta(days=1)
                continue
            ws = _week_start(d)
            if ws not in plans:
                plans[ws] = schedule_week(code, ws, cat, salas)
            plan = plans[ws]
            r = _rng("dia", code, d.isoformat())
            vac = cal.vacation_name(d)
            weekend = d.weekday() >= 4
            dayf = day_factor(d) * complex_trend(code, d) * math.exp(g.normal(0, 0.08))
            yr_price = INFLACION_BOLETO[d.year] * FACTOR_CIUDAD[city] * (1.06 if d.weekday() >= 4 else 1.0)
            day_att = fam_att = vip_att = 0
            for s in salas:
                if s["codigo"] not in plan:
                    continue
                main, *others = plan[s["codigo"]]
                for slot_i, minutes in enumerate(sala_slots(s["numero"] + ci, s["formato"], d)):
                    p = main
                    if slot_i >= 3 and others and r.random() < 0.25:
                        cands = [o for o in others if s["formato"] != "Junior" or o["clasificacion"] in ("AA", "A")]
                        p = r.choice(cands) if cands else main
                    h = hidden[p["codigo"]]
                    weeks = (d - date.fromisoformat(p["fecha_estreno"])).days // 7
                    film = (h["potencial"] * h["decay"] ** max(0, weeks)) ** 0.65
                    hf = hour_factor(minutes, d.weekday() >= 5, bool(vac))
                    if p["genero"] in ("Animación", "Familiar") and minutes >= 21 * 60:
                        hf *= 0.35
                    if p["genero"] in ("Terror", "Suspenso") and minutes >= 21 * 60:
                        hf *= 1.35
                    promo = promo_for(d, minutes)
                    x = (BASE * dayf * hf * DEMANDA_FORMATO[s["formato"]] * film *
                         genre_season(p["genero"], d, vac) * PROMO_UPLIFT[promo] * math.exp(g.normal(0, 0.28)))
                    occ = 1 - math.exp(-x)
                    cap = s["capacidad"]
                    sold = int(g.binomial(cap, min(0.99, occ)))
                    fid = int(d.strftime("%Y%m%d")) * 10000 + (ci * 10 + s["numero"]) * 10 + slot_i
                    split = g.multinomial(sold, channel_shares(d, s["formato"] == "VIP")) if sold else [0, 0, 0, 0]
                    taq, kio, app, web = (int(v) for v in split)
                    asist = taq + kio + int(g.binomial(app + web, 0.965)) if app + web else taq + kio
                    price = round(PRECIO_FORMATO[s["formato"]] * yr_price)
                    funciones.append([fid, d.isoformat(), f"{minutes // 60:02d}:{minutes % 60:02d}", code,
                                      s["codigo"], p["codigo"], promo, cap, asist])
                    for k, (ch, qty) in enumerate(zip(("TAQ", "KIO", "APP", "WEB"), (taq, kio, app, web))):
                        if qty:
                            boletos.append([fid * 10 + k, fid, CANAL_EXPORT[ch], qty, price, PROMO_PCT[promo]])
                    day_att += asist
                    if p["genero"] in ("Animación", "Familiar"):
                        fam_att += asist
                    if s["formato"] == "VIP":
                        vip_att += asist
            # ---- Dulcería del día (asociada a la asistencia, no proporcional constante)
            if day_att:
                t = min(1.0, max(0.0, (d - date(2023, 1, 1)).days / 1095))
                fam, vipsh = fam_att / day_att, vip_att / day_att
                app_share = 0.06 + 0.14 * t
                for sku, _, catg, _, _, attach, only_vip in PRODUCTOS:
                    if only_vip and not has_vip:
                        continue
                    base_n = vip_att if only_vip else day_att
                    m = base_n * attach * (1 if only_vip else ATTACH_SCALE) * pref[sku]
                    if catg == "Combos":
                        m *= (1 + 0.9 * fam) * (1 + 0.25 * t) * (1.25 if sku == "K04" and vac else 1)
                    if catg == "Palomitas":
                        m *= 1 + 0.4 * fam
                    if catg == "Bebidas" and sku in ("B01", "B02", "B03"):
                        m *= 1 - 0.12 * t       # migración de bebidas sueltas a combos
                    if sku in ("B05", "B06", "B07"):
                        m *= 1 + 0.30 * t
                    if catg == "Alimentos":
                        m *= 1 + 0.6 * vipsh
                    if weekend:
                        m *= 1.05
                    units = int(g.poisson(g.gamma(20, m / 20))) if m > 0 else 0
                    if units <= 0:
                        continue
                    sal = min(0.8, vipsh * 0.75) if has_vip else 0
                    if only_vip:
                        sh = np.array([0.15, app_share, 0.85 - app_share])
                    else:
                        sh = np.array([max(0.05, 1 - app_share - sal), app_share, sal])
                    split = g.multinomial(units, sh / sh.sum())
                    price = prod_by_sku[sku]["precio_lista"][str(d.year)]
                    for ch, qty in zip(("MOS", "APP", "SAL"), split):
                        if qty:
                            dulceria.append([d.isoformat(), code, sku, CANAL_EXPORT[ch], int(qty), price])
            d += timedelta(days=1)
    _inject_noise(year, month, funciones, boletos, dulceria)
    return dict(funciones=funciones, boletos=boletos, dulceria=dulceria)


def _inject_noise(year, month, funciones, boletos, dulceria):
    """Introduce problemas de calidad típicos de sistemas operacionales."""
    r = _rng("ruido", year, month)
    inv = {v: k for k, v in CANAL_EXPORT.items()}
    for row in r.sample(funciones, max(1, len(funciones) // 5000)):
        funciones.append(list(row))                               # duplicado exacto
    for row in r.sample(funciones, max(1, len(funciones) // 10000)):
        row[2] = "25:70"                                           # hora inválida
    for row in boletos:
        if r.random() < 0.04:
            row[2] = r.choice(CANAL_VARIANTES[inv[row[2]]])        # canal mal escrito
    for row in r.sample(boletos, max(1, len(boletos) // 700)):
        boletos.append(list(row))
    for row in r.sample(boletos, max(1, len(boletos) // 3000)):
        row[3] = -row[3]                                           # cantidad negativa
    for row in r.sample(boletos, max(1, len(boletos) // 5000)):
        row[1] = 99990000000000 + r.randint(0, 9999)               # función inexistente
    for row in r.sample(boletos, max(1, len(boletos) // 4000)):
        row[4] = ""                                                # precio faltante
    for row in dulceria:
        if r.random() < 0.04:
            y, m, dd = row[0].split("-")
            row[0] = f"{dd}/{m}/{y}"                               # otro formato de fecha (POS antiguo)
        if r.random() < 0.03:
            row[2] = f" {row[2].lower()} "
        if r.random() < 0.03:
            row[3] = r.choice(CANAL_VARIANTES[inv[row[3]]])
    for row in r.sample(dulceria, max(1, len(dulceria) // 700)):
        dulceria.append(list(row))
    for row in r.sample(dulceria, max(1, len(dulceria) // 5000)):
        row[0] = f"{year}-{month:02d}-32"                          # fecha inválida
    for row in r.sample(dulceria, max(1, len(dulceria) // 4000)):
        row[2] = "X99"                                             # producto inexistente
    for row in r.sample(dulceria, max(1, len(dulceria) // 2000)):
        row[5] = ""                                                # precio faltante -> se imputa
    for row in r.sample(dulceria, max(1, len(dulceria) // 5000)):
        row[4] = 0                                                 # unidades inválidas
    r.shuffle(boletos)
    r.shuffle(dulceria)


def write_month(year: int, month: int, cat: dict) -> dict:
    data = generate_month(year, month, cat)
    tag = f"{year}-{month:02d}"
    specs = [("programacion", f"funciones_{tag}.csv", data["funciones"],
              ["funcion_id", "fecha", "hora_inicio", "complejo", "sala", "pelicula", "promocion", "capacidad", "asistentes_registrados"]),
             ("taquilla", f"ventas_boletos_{tag}.csv", data["boletos"],
              ["venta_id", "funcion_id", "canal", "boletos", "precio_unitario", "descuento_pct"]),
             ("dulceria", f"ventas_dulceria_{tag}.csv", data["dulceria"],
              ["fecha", "complejo", "sku", "canal", "unidades", "precio_unitario"])]
    for folder, name, rows, header in specs:
        path = SOURCES_DIR / folder
        path.mkdir(parents=True, exist_ok=True)
        with (path / name).open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)
    return {k: len(v) for k, v in data.items()}


def months_between(a: date, b: date):
    y, m = a.year, a.month
    while (y, m) <= (b.year, b.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def existing_months() -> list:
    folder = SOURCES_DIR / "programacion"
    if not folder.exists():
        return []
    return sorted(tuple(int(x) for x in p.stem.split("_")[1].split("-")) for p in folder.glob("funciones_*.csv"))


def next_month():
    have = existing_months()
    if not have:
        return HIST_START.year, HIST_START.month
    y, m = have[-1]
    return (y + 1, 1) if m == 12 else (y, m + 1)


def generate_history(verbose=True) -> None:
    cat = build_catalogs()
    write_catalogs(cat)
    for y, m in months_between(HIST_START, HIST_END):
        n = write_month(y, m, cat)
        if verbose:
            print(f"{y}-{m:02d}: {n}")


def generate_next(verbose=True):
    y, m = next_month()
    if (y, m) > MAX_SIM_MONTH:
        raise ValueError(f"Se alcanzó el límite de simulación ({MAX_SIM_MONTH[0]}-{MAX_SIM_MONTH[1]:02d}).")
    cat = build_catalogs()
    write_catalogs(cat)
    n = write_month(y, m, cat)
    if verbose:
        print(f"{y}-{m:02d}: {n}")
    return f"{y}-{m:02d}", n


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--siguiente", action="store_true", help="genera únicamente el siguiente mes")
    args = ap.parse_args()
    generate_next() if args.siguiente else generate_history()
