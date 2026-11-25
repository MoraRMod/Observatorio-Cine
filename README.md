# Cine BI · Plataforma de Business Intelligence y Data Warehouse

Proyecto final de **Almacenes de Datos**: plataforma de BI para una cadena cinematográfica inspirada en Cinépolis. Incluye fuentes simuladas, staging, ETL incremental, Data Warehouse en estrella, data marts, OLAP, modelo predictivo y recomendaciones de negocio.

> **Datos sintéticos para fines académicos. No representan información financiera oficial de Cinépolis.**

La documentación técnica completa (arquitectura, diccionario, diagramas, ETL, modelo y resultados) está en [docs/DOCUMENTACION.md](docs/DOCUMENTACION.md).

## Requisitos

- Python 3.9 o superior

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

En Windows usa `.venv\Scripts\pip` y `.venv\Scripts\python`.

## Ejecutar

1. Generar las fuentes, cargar el Data Warehouse y entrenar el modelo (~2 minutos, una sola vez):

```bash
.venv/bin/python run.py --setup
```

2. Iniciar la plataforma:

```bash
.venv/bin/python run.py
```

- <http://localhost:8765> — página de inicio original (Observatorio Cine), con los datos del Data Warehouse y la pestaña **Análisis BI**, que lista los 10 análisis.
- <http://localhost:8765/bi> — plataforma de Business Intelligence completa.
- <http://localhost:8765/docs> — documentación interactiva de la API.

Si `data/warehouse.sqlite` no existe, `python run.py` ejecuta el *setup* automáticamente antes de iniciar.

## Comandos por etapa

| Etapa | Comando |
|---|---|
| Generar fuentes 2023-2025 | `.venv/bin/python -m backend.sources.generate_sources` |
| Agregar el siguiente mes | `.venv/bin/python -m backend.sources.generate_sources --siguiente` |
| ETL incremental | `.venv/bin/python -m backend.etl.pipeline` |
| ETL completo | `.venv/bin/python -m backend.etl.pipeline --completa` |
| Entrenar el modelo | `.venv/bin/python -m backend.ml.train` |

Todas estas operaciones también se pueden ejecutar desde la interfaz (secciones **Procesos ETL** y **Modelo predictivo**).

## Estructura

```
backend/
  config.py             rutas, semilla, periodos
  calendario.py         festivos, vacaciones SEP y temporadas
  sources/              capa 1: generador de fuentes sintéticas
  etl/                  capas 2-5: schema.sql + pipeline (extract, transform, load, marts)
  ml/train.py           minería de datos: comparación de modelos, evaluación, pronóstico
  services/             acceso a datos, KPI, OLAP, inteligencia de negocios, metadatos
  api/main.py           capa 6: API FastAPI (sirve también el frontend)
index.html, app.js, styles.css   página de inicio original (sirve en /)
frontend/               plataforma BI (sirve en /bi): HTML/CSS/JS, gráficas SVG propias (sin CDN)
data/
  complejos.json        directorio público SIC (fuente verificable)
  sources/              fuentes generadas (no versionadas)
  warehouse.sqlite      Data Warehouse (no versionado, ~300 MB)
docs/DOCUMENTACION.md   documentación técnica
legacy/                 piloto sintético 2025 y script del directorio SIC
```

Los datos generados no se versionan porque se reproducen exactamente con la semilla fija.
