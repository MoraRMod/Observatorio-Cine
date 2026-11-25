"""Reglas de calendario mexicano compartidas por el generador, el ETL y el modelo.

Días festivos oficiales según el Art. 74 de la Ley Federal del Trabajo, más fechas
de alta asistencia de uso común (Semana Santa, Día de Muertos, 12 de diciembre).
Los periodos vacacionales son aproximaciones al calendario escolar de la SEP.
"""
from datetime import date, timedelta
from functools import lru_cache

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
         "Septiembre", "Octubre", "Noviembre", "Diciembre"]
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def easter(year: int) -> date:
    """Domingo de Pascua (algoritmo anónimo gregoriano)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_monday(year: int, month: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(7 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


@lru_cache(maxsize=None)
def holidays(year: int) -> dict:
    """Devuelve {fecha: (nombre, oficial)}."""
    e = easter(year)
    h = {
        date(year, 1, 1): ("Año Nuevo", True),
        _nth_monday(year, 2, 1): ("Día de la Constitución", True),
        _nth_monday(year, 3, 3): ("Natalicio de Benito Juárez", True),
        date(year, 5, 1): ("Día del Trabajo", True),
        date(year, 9, 16): ("Día de la Independencia", True),
        _nth_monday(year, 11, 3): ("Día de la Revolución", True),
        date(year, 12, 25): ("Navidad", True),
        e - timedelta(days=3): ("Jueves Santo", False),
        e - timedelta(days=2): ("Viernes Santo", False),
        date(year, 11, 2): ("Día de Muertos", False),
        date(year, 12, 12): ("Día de la Virgen de Guadalupe", False),
    }
    if year % 6 == 0:  # Transmisión del Poder Ejecutivo Federal (2024, 2030...)
        h[date(year, 10, 1)] = ("Transmisión del Poder Ejecutivo", True)
    return h


def vacation_name(d: date):
    """Periodo vacacional escolar aproximado (SEP) o None."""
    e = easter(d.year)
    if e - timedelta(days=6) <= d <= e + timedelta(days=7):
        return "Semana Santa y Pascua"
    if date(d.year, 7, 15) <= d <= date(d.year, 8, 27):
        return "Verano"
    if d >= date(d.year, 12, 18) or d <= date(d.year, 1, 7):
        return "Invierno"
    return None


def season(d: date) -> str:
    """Temporada comercial: Alta, Media o Baja."""
    if vacation_name(d) or d in holidays(d.year):
        return "Alta"
    if d.month in (2, 9) or (d.month == 1 and d.day > 7) or (d.month == 10 and d.day < 20):
        return "Baja"
    return "Media"


def is_long_weekend(d: date) -> bool:
    """Fin de semana largo por lunes festivo oficial."""
    h = holidays(d.year)
    if d.weekday() == 5:
        return (d + timedelta(days=2)) in h
    if d.weekday() == 6:
        return (d + timedelta(days=1)) in h
    return d.weekday() == 0 and d in h
