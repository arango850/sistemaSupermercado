"""
main.py
-------
Orquestador principal del pipeline de análisis de supermercado.

Uso:
    python main.py [data_dir] [output_dir]

Por defecto:
    data_dir   = ../DataSet
    output_dir = ../output

Ejemplos:
    python main.py
    python main.py C:/ruta/a/DataSet C:/ruta/a/output
"""

import sys
import os
import time
import json

# Asegura que el directorio de analysis esté en el path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_loader       import load_all, DEFAULT_DATA_DIR, DEFAULT_OUTPUT_DIR
from executive_summary import compute_executive_summary
from analytical_charts import compute_time_series, compute_boxplot_data, compute_heatmap_data
from clustering        import compute_clustering
from recommender       import compute_recommendations


def run_pipeline(data_dir: str = DEFAULT_DATA_DIR, output_dir: str = DEFAULT_OUTPUT_DIR):
    """
    Ejecuta el pipeline completo:
      1. Carga de datos
      2. Resumen ejecutivo
      3. Visualizaciones analíticas (series de tiempo, boxplot, heatmap)

    Retorna un diccionario con todos los resultados.
    """
    os.makedirs(output_dir, exist_ok=True)

    print("\n" + "=" * 60)
    print("  ANÁLISIS DE TRANSACCIONES DE SUPERMERCADO")
    print("=" * 60)
    start_total = time.time()

    # ------------------------------------------------------------------
    # PASO 1 — Carga de datos
    # ------------------------------------------------------------------
    print("\n[1/4] Cargando datos...")
    t0 = time.time()
    transactions, categories = load_all(data_dir)
    print(f"  ✓ Datos cargados en {time.time() - t0:.1f}s")

    results = {}

    # ------------------------------------------------------------------
    # PASO 2 — Resumen Ejecutivo
    # ------------------------------------------------------------------
    print("\n[2/6] Generando resumen ejecutivo...")
    t0 = time.time()
    results['executive_summary'] = compute_executive_summary(transactions, output_dir)
    print(f"  ✓ Resumen ejecutivo en {time.time() - t0:.1f}s")

    # ------------------------------------------------------------------
    # PASO 3 — Visualizaciones Analíticas
    # ------------------------------------------------------------------
    print("\n[3/6] Generando datos para visualizaciones analíticas...")
    t0 = time.time()

    print("  → Serie de tiempo...")
    results['time_series'] = compute_time_series(transactions, output_dir)

    print("  → Boxplot...")
    results['boxplot'] = compute_boxplot_data(transactions, output_dir)

    print("  → Heatmap de correlación...")
    results['heatmap'] = compute_heatmap_data(transactions, output_dir)

    print(f"  ✓ Visualizaciones analíticas en {time.time() - t0:.1f}s")

    # ------------------------------------------------------------------
    # PASO 4 — Segmentación de clientes (K-Means)
    # ------------------------------------------------------------------
    print("\n[4/6] Segmentando clientes (K-Means)...")
    t0 = time.time()
    results['clustering'] = compute_clustering(transactions, output_dir)
    print(f"  ✓ Segmentación en {time.time() - t0:.1f}s")

    # ------------------------------------------------------------------
    # PASO 5 — Recomendaciones por co-ocurrencia
    # ------------------------------------------------------------------
    print("\n[5/6] Generando recomendaciones de categorías...")
    t0 = time.time()
    results['recommendations'] = compute_recommendations(transactions, output_dir)
    print(f"  ✓ Recomendaciones en {time.time() - t0:.1f}s")

    # ------------------------------------------------------------------
    # PASO 6 — Índice de archivos generados
    # ------------------------------------------------------------------
    print("\n[6/6] Generando índice de outputs...")
    generated_files = [
        f for f in os.listdir(output_dir) if f.endswith('.json')
    ]
    index = {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'data_dir':     os.path.abspath(data_dir),
        'output_dir':   os.path.abspath(output_dir),
        'files':        sorted(generated_files),
    }
    with open(os.path.join(output_dir, 'index.json'), 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - start_total
    print(f"\n{'=' * 60}")
    print(f"  Pipeline completado en {elapsed:.1f}s")
    print(f"  Archivos generados en: {os.path.abspath(output_dir)}")
    for fname in sorted(generated_files):
        size_kb = os.path.getsize(os.path.join(output_dir, fname)) / 1024
        print(f"    {fname:<40} ({size_kb:,.0f} KB)")
    print("=" * 60)

    return results


def main():
    data_dir   = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DATA_DIR
    output_dir = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUTPUT_DIR

    data_dir   = os.path.abspath(data_dir)
    output_dir = os.path.abspath(output_dir)

    if not os.path.isdir(data_dir):
        print(f"Error: data_dir no existe: {data_dir}")
        sys.exit(1)

    run_pipeline(data_dir, output_dir)


if __name__ == '__main__':
    main()
