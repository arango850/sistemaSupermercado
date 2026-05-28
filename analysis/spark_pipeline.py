"""
spark_pipeline.py
-----------------
Pipeline alternativo de análisis usando Apache Spark (PySpark).

Replica la funcionalidad de main.py pero usa DataFrames de Spark y
las bibliotecas MLlib de PySpark para:
  - Carga y normalización de CSV
  - Segmentación de clientes con KMeans (pyspark.ml.clustering)
  - Recomendaciones con FPGrowth  (pyspark.ml.fpm)

Los archivos JSON de salida son idénticos a los del pipeline pandas,
por lo que el backend Django y el frontend React no requieren cambios.

Uso:
    python spark_pipeline.py [data_dir] [output_dir]
    o bien, desde main.py con USE_SPARK=1:
    USE_SPARK=1 python main.py

Requisitos:
    pip install pyspark
    Java 8/11/17 instalado y JAVA_HOME configurado.
"""

import sys
import os
import json
import time

# ---------------------------------------------------------------------------
# Ajuste de SPARK_HOME para Windows con caracteres no-ASCII en la ruta
# (mismo parche que en spark-recommendations.py)
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    import importlib.util as _ilu
    _spec = _ilu.find_spec("pyspark")
    if _spec and _spec.origin:
        _pdir = os.path.dirname(os.path.abspath(_spec.origin))
        try:
            import ctypes as _ct
            _buf = _ct.create_unicode_buffer(32768)
            _ct.windll.kernel32.GetShortPathNameW(_pdir, _buf, 32768)
            if _buf.value:
                _pdir = _buf.value
        except Exception:
            pass
        os.environ["SPARK_HOME"] = _pdir
        del _pdir, _spec, _ilu

os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, IntegerType, LongType,
    StringType, DateType,
)
from pyspark.ml.feature import VectorAssembler, StandardScaler
from pyspark.ml.clustering import KMeans
from pyspark.ml.evaluation import ClusteringEvaluator
from pyspark.ml.fpm import FPGrowth

# Rutas por defecto relativas al directorio del proyecto
_BASE_DIR          = os.path.join(os.path.dirname(__file__), '..')
DEFAULT_DATA_DIR   = os.path.abspath(os.path.join(_BASE_DIR, 'DataSet'))
DEFAULT_OUTPUT_DIR = os.path.abspath(os.path.join(_BASE_DIR, 'output'))

# ---------------------------------------------------------------------------
# Parámetros del pipeline
# ---------------------------------------------------------------------------
FEATURE_KEYS     = ['purchase_frequency', 'total_units', 'avg_basket_size',
                    'category_diversity', 'active_days']
K_VALUES         = [3, 4, 5, 6]
FPG_MIN_SUPPORT  = 0.02
FPG_MIN_CONF     = 0.25
TOP_RECOMMENDATIONS = 15
SAMPLE_SIZE      = 2000


# ---------------------------------------------------------------------------
# Helpers: carga de datos
# ---------------------------------------------------------------------------

def _create_spark() -> SparkSession:
    return (
        SparkSession.builder
        .appName("Supermercado-Spark-Pipeline")
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.driver.memory", "4g")
        .getOrCreate()
    )


def _load_transactions_spark(spark: SparkSession, data_dir: str):
    """
    Lee todos los *_Tran.csv y devuelve un DataFrame explosionado con columnas:
        transaction_id (long), date (string), store_id (int),
        client_id (int), category_id (int)
    """
    import glob as _glob

    txn_dir = os.path.join(data_dir, 'Transactions')
    files = sorted(_glob.glob(os.path.join(txn_dir, '*_Tran.csv')))
    if not files:
        raise FileNotFoundError(f"No se encontraron *_Tran.csv en {txn_dir}")

    print(f"  Leyendo {len(files)} archivos de transacciones con Spark...")

    # Usar pandas para la carga inicial (archivos con separador |, sin header)
    # y luego convertir a Spark DataFrame — es más sencillo que el reader de Spark
    # para este formato ad-hoc.
    import pandas as pd

    dfs = []
    for fpath in files:
        df = pd.read_csv(
            fpath, sep='|', header=None,
            names=['date', 'store_id', 'client_id', 'items_str'],
            dtype={'store_id': int, 'client_id': int, 'items_str': str},
        )
        dfs.append(df)
        print(f"    {os.path.basename(fpath)}: {len(df):,} transacciones")

    raw = pd.concat(dfs, ignore_index=True)
    raw['transaction_id'] = raw.index.astype('int64')
    raw['items'] = raw['items_str'].str.split()
    raw = raw.drop(columns=['items_str'])

    # Explotar ítems
    exploded = raw.explode('items').copy()
    exploded['category_id'] = pd.to_numeric(exploded['items'], errors='coerce')
    exploded = exploded.dropna(subset=['category_id'])
    exploded['category_id'] = exploded['category_id'].astype('int32')
    exploded = exploded.drop(columns=['items'])

    # Convertir a Spark DataFrame
    sdf = spark.createDataFrame(exploded)
    sdf = sdf.withColumn('date', F.to_date('date', 'yyyy-MM-dd'))
    return sdf


def _load_categories_spark(spark: SparkSession, data_dir: str):
    """
    Carga Categories.csv y retorna un Spark DataFrame con:
        category_id (int), category_name (str)
    """
    path = os.path.join(data_dir, 'Products', 'Categories.csv')
    import pandas as pd
    cats = pd.read_csv(path, sep='|', header=None,
                       names=['category_id', 'category_name'],
                       dtype={'category_id': int, 'category_name': str})
    return spark.createDataFrame(cats)


# ---------------------------------------------------------------------------
# Módulo 1 — Features de clientes
# ---------------------------------------------------------------------------

def _build_client_features_spark(txn_sdf, spark: SparkSession):
    """
    Construye features por cliente usando operaciones nativas de Spark.
    Retorna un DataFrame Spark con columnas:
        client_id, purchase_frequency, total_units, avg_basket_size,
        category_diversity, active_days
    """
    # purchase_frequency, total_units, active_days, category_diversity
    base = txn_sdf.groupBy('client_id').agg(
        F.countDistinct('transaction_id').alias('purchase_frequency'),
        F.count('category_id').alias('total_units'),
        F.countDistinct('date').alias('active_days'),
        F.countDistinct('category_id').alias('category_diversity'),
    )

    # avg_basket_size: promedio de ítems únicos por transacción
    basket_sizes = (
        txn_sdf
        .groupBy('client_id', 'transaction_id')
        .agg(F.count('category_id').alias('basket_size'))
        .groupBy('client_id')
        .agg(F.avg('basket_size').alias('avg_basket_size'))
    )

    features = base.join(basket_sizes, on='client_id', how='left')
    features = features.fillna(0)
    return features


# ---------------------------------------------------------------------------
# Módulo 2 — K-Means con PySpark MLlib
# ---------------------------------------------------------------------------

def _compute_clustering_spark(features_sdf, output_dir: str) -> dict:
    """
    Entrena K-Means con PySpark MLlib, evalúa con ClusteringEvaluator
    y guarda output/clustering.json.
    """
    import pandas as pd
    import numpy as np

    assembler = VectorAssembler(inputCols=FEATURE_KEYS, outputCol='features_raw')
    scaler = StandardScaler(
        inputCol='features_raw', outputCol='features',
        withStd=True, withMean=True,
    )

    df_vec = assembler.transform(features_sdf)
    scaler_model = scaler.fit(df_vec)
    df_scaled = scaler_model.transform(df_vec)

    evaluator = ClusteringEvaluator(
        featuresCol='features', metricName='silhouette',
        distanceMeasure='squaredEuclidean',
    )

    elbow_data = []
    best_k = K_VALUES[0]
    best_sil = -1.0
    best_model = None

    print("    Evaluando k = " + ", ".join(str(k) for k in K_VALUES) + " ...")
    for k in K_VALUES:
        km = KMeans(k=k, seed=42, maxIter=20, featuresCol='features',
                    predictionCol='segment_id')
        model = km.fit(df_scaled)
        predictions = model.transform(df_scaled)
        sil = float(evaluator.evaluate(predictions))
        inertia = float(model.summary.trainingCost)
        elbow_data.append({'k': k, 'inertia': round(inertia, 2),
                           'silhouette': round(sil, 4)})
        print(f"      k={k}: inertia={inertia:,.0f}  silhouette={sil:.4f}")
        if sil > best_sil:
            best_sil, best_k, best_model = sil, k, model

    print(f"    Mejor k={best_k} (silhouette={best_sil:.4f})")

    # Predicciones finales
    df_final = best_model.transform(df_scaled)
    n_clients = df_final.count()

    # Centroides en escala original
    centroids_scaled = np.array([c.toArray() for c in best_model.clusterCenters()])
    # Desescalar manualmente: x_orig = x_scaled * std + mean
    std_values = np.array([float(scaler_model.std[i]) for i in range(len(FEATURE_KEYS))])
    mean_values = np.array([float(scaler_model.mean[i]) for i in range(len(FEATURE_KEYS))])
    centroids_orig = centroids_scaled * std_values + mean_values

    # Estadísticas por segmento
    seg_stats_sdf = df_final.groupBy('segment_id').agg(
        F.count('client_id').alias('size'),
        *[F.avg(c).alias(f'mean_{c}') for c in FEATURE_KEYS],
        *[F.median(F.col(c)).alias(f'median_{c}') for c in FEATURE_KEYS],
    )
    seg_stats = {
        row['segment_id']: row.asDict()
        for row in seg_stats_sdf.collect()
    }

    def _label(centroid: dict) -> str:
        if centroid['purchase_frequency'] <= 4 and centroid['total_units'] <= 25:
            return "Compradores Esporádicos"
        elif centroid['purchase_frequency'] <= 10 and centroid['total_units'] <= 80:
            return "Compradores Ocasionales"
        elif centroid['category_diversity'] >= 40 and centroid['total_units'] >= 200:
            return "Compradores Diversificados"
        elif centroid['total_units'] >= 300:
            return "Compradores VIP"
        return "Compradores Regulares"

    segments = []
    for seg_id in range(best_k):
        c_dict = {key: round(float(v), 2)
                  for key, v in zip(FEATURE_KEYS, centroids_orig[seg_id])}
        row = seg_stats.get(seg_id, {})
        size = int(row.get('size', 0))
        stats = {key: {'mean':   round(float(row.get(f'mean_{key}', 0)), 2),
                       'median': round(float(row.get(f'median_{key}', 0)), 2)}
                 for key in FEATURE_KEYS}
        segments.append({
            'segment_id': seg_id,
            'label':      _label(c_dict),
            'size':       size,
            'percentage': round(size / n_clients * 100, 1),
            'centroid':   c_dict,
            'stats':      stats,
        })
    segments.sort(key=lambda s: -s['size'])
    for new_id, seg in enumerate(segments):
        seg['segment_id'] = new_id

    # Muestra para scatter
    sample_sdf = df_final.select(
        'client_id', 'segment_id', *FEATURE_KEYS
    ).sample(fraction=min(SAMPLE_SIZE / n_clients, 1.0), seed=42).limit(SAMPLE_SIZE)
    sample_pd = sample_sdf.toPandas()
    client_sample = sample_pd.to_dict(orient='records')

    result = {
        'generated_at':     pd.Timestamp.now().isoformat(),
        'engine':           'spark',
        'k':                best_k,
        'silhouette_score': round(best_sil, 4),
        'total_clients':    n_clients,
        'feature_keys':     FEATURE_KEYS,
        'elbow_data':       elbow_data,
        'segments':         segments,
        'client_sample':    client_sample,
    }

    out_path = os.path.join(output_dir, 'clustering.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"    ✓ clustering.json ({os.path.getsize(out_path)/1024:.0f} KB)")
    return result


# ---------------------------------------------------------------------------
# Módulo 3 — FP-Growth con PySpark MLlib
# ---------------------------------------------------------------------------

def _compute_recommendations_spark(txn_sdf, cats_sdf, output_dir: str) -> dict:
    """
    Aplica FP-Growth sobre los cestos de categorías por transacción y
    guarda output/recommendations.json.
    """
    import pandas as pd

    # Construir cesto: lista de category_id por transacción
    baskets_sdf = (
        txn_sdf
        .groupBy('transaction_id')
        .agg(F.collect_set('category_id').alias('items'))
    )

    n_txns = int(txn_sdf.select('transaction_id').distinct().count())
    n_cats = int(txn_sdf.select('category_id').distinct().count())
    print(f"    FP-Growth sobre {n_txns:,} transacciones · {n_cats} categorías")
    print(f"    min_support={FPG_MIN_SUPPORT}  min_confidence={FPG_MIN_CONF}")

    fpg = FPGrowth(
        itemsCol='items',
        minSupport=FPG_MIN_SUPPORT,
        minConfidence=FPG_MIN_CONF,
    )
    model = fpg.fit(baskets_sdf)

    # Reglas de asociación (Spark las devuelve en formato antecedent/consequent)
    rules_sdf = model.associationRules
    # Calcular lift: lift = confidence / consequent_support
    # Spark 3.x ya incluye la columna lift
    rules_pd = rules_sdf.toPandas()

    # Mapa id → nombre de categoría
    cats_pd = cats_sdf.toPandas().set_index('category_id')['category_name'].to_dict()

    def _ids_to_names(ids):
        return [cats_pd.get(int(i), str(i)) for i in ids]

    rules = []
    for _, row in rules_pd.iterrows():
        ant_ids = list(row['antecedent'])
        con_ids = list(row['consequent'])
        if len(ant_ids) != 1 or len(con_ids) != 1:
            continue  # solo reglas simples A→B
        ant_name = cats_pd.get(int(ant_ids[0]), str(ant_ids[0]))
        con_name = cats_pd.get(int(con_ids[0]), str(con_ids[0]))
        rules.append({
            'antecedent_id':  int(ant_ids[0]),
            'antecedent':     ant_name,
            'consequent_id':  int(con_ids[0]),
            'consequent':     con_name,
            'support':    round(float(row.get('support', 0)), 4),
            'confidence': round(float(row['confidence']), 4),
            'lift':       round(float(row.get('lift', 0)), 4),
        })

    rules.sort(key=lambda r: (-r['lift'], -r['confidence']))
    print(f"    {len(rules):,} reglas A→B generadas")

    # Índice por categoría
    category_index: dict = {}
    for rule in rules:
        ant = rule['antecedent']
        if ant not in category_index:
            category_index[ant] = []
        if len(category_index[ant]) < TOP_RECOMMENDATIONS:
            category_index[ant].append({
                'recommendation': rule['consequent'],
                'confidence':     rule['confidence'],
                'lift':           rule['lift'],
                'support':        rule['support'],
            })

    result = {
        'generated_at':    pd.Timestamp.now().isoformat(),
        'engine':          'spark',
        'n_transactions':  n_txns,
        'n_categories':    n_cats,
        'min_support':     FPG_MIN_SUPPORT,
        'min_confidence':  FPG_MIN_CONF,
        'total_rules':     len(rules),
        'rules':           rules[:1000],
        'category_index':  category_index,
    }

    out_path = os.path.join(output_dir, 'recommendations.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"    ✓ recommendations.json ({os.path.getsize(out_path)/1024:.0f} KB)")
    return result


# ---------------------------------------------------------------------------
# Orquestador principal
# ---------------------------------------------------------------------------

def run_spark_pipeline(data_dir: str = DEFAULT_DATA_DIR,
                       output_dir: str = DEFAULT_OUTPUT_DIR) -> dict:
    """
    Ejecuta el pipeline completo con PySpark.
    Produce clustering.json y recommendations.json idénticos al pipeline pandas.
    """
    os.makedirs(output_dir, exist_ok=True)
    start_total = time.time()

    print("\n" + "=" * 60)
    print("  PIPELINE SPARK — ANÁLISIS DE SUPERMERCADO")
    print("=" * 60)

    # ------------------------------------------------------------------
    # PASO 1 — Iniciar Spark
    # ------------------------------------------------------------------
    print("\n[1/4] Iniciando SparkSession...")
    spark = _create_spark()
    spark.sparkContext.setLogLevel("WARN")
    print(f"  ✓ Spark {spark.version}")

    # ------------------------------------------------------------------
    # PASO 2 — Cargar datos
    # ------------------------------------------------------------------
    print("\n[2/4] Cargando datos...")
    t0 = time.time()
    txn_sdf  = _load_transactions_spark(spark, data_dir)
    cats_sdf = _load_categories_spark(spark, data_dir)
    txn_sdf  = txn_sdf.join(
        cats_sdf.withColumnRenamed('category_id', 'cat_id')
                .withColumnRenamed('category_name', 'category_name'),
        txn_sdf.category_id == F.col('cat_id'),
        how='left',
    ).drop('cat_id')
    txn_sdf.cache()
    n_rows = txn_sdf.count()
    print(f"  ✓ {n_rows:,} filas cargadas en {time.time()-t0:.1f}s")

    results = {}

    # ------------------------------------------------------------------
    # PASO 3 — Segmentación K-Means
    # ------------------------------------------------------------------
    print("\n[3/4] Segmentación de clientes (K-Means Spark)...")
    t0 = time.time()
    features_sdf = _build_client_features_spark(txn_sdf, spark)
    results['clustering'] = _compute_clustering_spark(features_sdf, output_dir)
    print(f"  ✓ Segmentación en {time.time()-t0:.1f}s")

    # ------------------------------------------------------------------
    # PASO 4 — Recomendaciones FP-Growth
    # ------------------------------------------------------------------
    print("\n[4/4] Recomendaciones (FP-Growth Spark)...")
    t0 = time.time()
    results['recommendations'] = _compute_recommendations_spark(txn_sdf, cats_sdf, output_dir)
    print(f"  ✓ Recomendaciones en {time.time()-t0:.1f}s")

    txn_sdf.unpersist()
    spark.stop()

    elapsed = time.time() - start_total
    print(f"\n{'=' * 60}")
    print(f"  Pipeline Spark completado en {elapsed:.1f}s")
    print("=" * 60)

    return results


# ---------------------------------------------------------------------------
# Entry-point directo
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    data_dir   = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DATA_DIR
    output_dir = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUTPUT_DIR
    run_spark_pipeline(
        data_dir=os.path.abspath(data_dir),
        output_dir=os.path.abspath(output_dir),
    )
