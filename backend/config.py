"""Configuración central del proyecto (rutas, semilla y periodos)."""
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SOURCES_DIR = DATA_DIR / "sources"          # Capa 1: fuentes (sistemas operacionales simulados)
STAGING_DB = DATA_DIR / "staging.sqlite"    # Capa 2: staging area (transitoria)
DW_DB = DATA_DIR / "warehouse.sqlite"       # Capas 4 y 5: data warehouse + data marts
MODELS_DIR = DATA_DIR / "models"            # Modelo predictivo serializado
FRONTEND_DIR = ROOT / "frontend"
PUBLIC_DIRECTORY = DATA_DIR / "complejos.json"  # Directorio público SIC (fuente verificable)

SEED = 20231001
# Periodo histórico base que se genera en la primera ejecución.
HIST_START = date(2023, 1, 1)
HIST_END = date(2025, 12, 31)
# Límite máximo para simular la llegada de nuevos meses (extracciones incrementales).
MAX_SIM_MONTH = (2026, 10)
# Calendario de la dimensión fecha (incluye horizonte de pronóstico).
CAL_START = date(2023, 1, 1)
CAL_END = date(2026, 12, 31)

DATA_LABEL = ("Datos sintéticos para fines académicos. No representan "
              "información financiera oficial de Cinépolis.")
