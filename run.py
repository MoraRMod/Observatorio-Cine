"""Punto de entrada del proyecto.

    python run.py --setup     # genera fuentes, ejecuta ETL completo y entrena el modelo
    python run.py             # inicia la plataforma en http://localhost:8765
"""
import argparse
import sys

from backend.config import DW_DB


def setup():
    from backend.etl.pipeline import run_etl
    from backend.ml.train import train
    from backend.sources.generate_sources import generate_history
    print("1/3 Generando fuentes sintéticas (2023-2025)…")
    generate_history(verbose=False)
    print("2/3 Ejecutando ETL completo…")
    r = run_etl(full=True, progress=lambda m, p: print(f"   [{p:3d}%] {m}") if p % 10 < 3 else None)
    print(f"   {r['estado']} en {r['duracion_seg']} s")
    print("3/3 Entrenando modelo predictivo…")
    t = train(progress=lambda m, p: print(f"   [{p:3d}%] {m}"))
    print(f"   Modelo seleccionado: {t['run']['algoritmo']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--setup", action="store_true")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    if args.setup or not DW_DB.exists():
        setup()
        if args.setup:
            sys.exit(0)
    import uvicorn
    uvicorn.run("backend.api.main:app", host="127.0.0.1", port=args.port)
