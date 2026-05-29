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
import math
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

# ---------------------------------------------------------------------------
# Garantizar Java 17 o 21 para Spark 4.x.
# - Java < 17: no soportado por Spark 4.x
# - Java 17–21: compatible (con --add-opens)
# - Java 22+:  Subject.getSubject() fue removido en Java 25 → Hadoop falla
#              En Java 22-24 es deprecated-for-removal pero aún funciona;
#              en Java 25 ya no. Para evitar ambigüedad preferimos Java 17/21.
# ---------------------------------------------------------------------------
def _ensure_java17():
    import subprocess, re

    def _java_major(java_exe: str) -> int:
        try:
            out = subprocess.check_output(
                [java_exe, "-version"], stderr=subprocess.STDOUT,
                timeout=5, text=True,
            )
            m = re.search(r'version "(\d+)', out)
            if m:
                major = int(m.group(1))
                # Java 8 reporta "1.8.x" → retornar 8
                return major if major >= 9 else int(out.split('"')[1].split('.')[1])
        except Exception:
            pass
        return 0

    def _is_compatible(major: int) -> bool:
        """Spark 4.x requiere Java 17+; Java 22+ rompe Hadoop getSubject."""
        return 17 <= major <= 21

    # Verificar JAVA_HOME actual
    java_home = os.environ.get("JAVA_HOME", "")
    if java_home:
        java_exe = os.path.join(java_home, "bin",
                                "java.exe" if sys.platform == "win32" else "java")
        major = _java_major(java_exe)
        if _is_compatible(major):
            return  # ya está configurado correctamente

    # Buscar Java 17 o 21 en ubicaciones típicas de Windows
    if sys.platform == "win32":
        import glob as _g
        # Preferir versiones más bajas compatibles (17 > 21)
        candidates = sorted(
            _g.glob(r"C:\Program Files\Java\jdk-17*") +
            _g.glob(r"C:\Program Files\Java\jdk-21*") +
            _g.glob(r"C:\Program Files\Eclipse Adoptium\jdk-17*") +
            _g.glob(r"C:\Program Files\Eclipse Adoptium\jdk-21*") +
            _g.glob(r"C:\Program Files\Microsoft\jdk-17*") +
            _g.glob(r"C:\Program Files\Microsoft\jdk-21*") +
            _g.glob(r"C:\Program Files\Java\jdk-1[789]*") +
            _g.glob(r"C:\Program Files\Java\jdk-2[01]*"),
        )
        for jdir in candidates:
            java_exe = os.path.join(jdir, "bin", "java.exe")
            if _is_compatible(_java_major(java_exe)):
                os.environ["JAVA_HOME"] = jdir
                print(f"  [Spark] JAVA_HOME → {jdir}  (Java ≤21 requerido por Hadoop)")
                return

    current_major = _java_major(
        os.path.join(os.environ.get("JAVA_HOME", ""), "bin",
                     "java.exe" if sys.platform == "win32" else "java")
    )
    if current_major >= 22:
        print(f"  [Spark] ADVERTENCIA: Java {current_major} detectado. "
              "Hadoop en PySpark 4.1.1 requiere Java 17–21. "
              "Instala Java 17 o configura JAVA_HOME manualmente.")

_ensure_java17()

# Memoria del JVM — debe configurarse ANTES de importar PySpark.
# spark.driver.memory en SparkConf no tiene efecto en local mode porque
# el JVM ya está iniciado; PYSPARK_SUBMIT_ARGS es la única forma de pasar
# -Xmx al proceso JVM real antes de que arranque.
os.environ.setdefault("PYSPARK_SUBMIT_ARGS", "--driver-memory 6g pyspark-shell")

# ---------------------------------------------------------------------------
# Java 17+ requiere --add-opens para que Hadoop pueda acceder a
# javax.security.auth.Subject.getSubject() (removido en Java 17+).
# Configurar ANTES de importar pyspark para que el JVM lo reciba.
# ---------------------------------------------------------------------------
_JAVA_OPENS = " ".join([
    "--add-opens=java.base/java.lang=ALL-UNNAMED",
    "--add-opens=java.base/java.util=ALL-UNNAMED",
    "--add-opens=java.base/java.io=ALL-UNNAMED",
    "--add-opens=java.base/sun.nio.cs=ALL-UNNAMED",
    "--add-opens=java.base/sun.nio.ch=ALL-UNNAMED",
    "--add-opens=java.base/javax.security.auth=ALL-UNNAMED",
    "--add-opens=java.base/java.nio=ALL-UNNAMED",
])
os.environ["JAVA_TOOL_OPTIONS"] = _JAVA_OPENS

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
FPG_MIN_SUPPORT      = 0.05   # subido de 0.02 → reduce drásticamente itemsets intermedios
FPG_MIN_CONF         = 0.30
FPG_MAX_BASKETS      = 400_000  # muestra máxima de cestos para FP-Growth
TOP_RECOMMENDATIONS  = 15
SAMPLE_SIZE          = 2000


# ---------------------------------------------------------------------------
# Helpers: carga de datos
# ---------------------------------------------------------------------------

def _create_spark() -> SparkSession:
    return (
        SparkSession.builder
        .appName("Supermercado-Spark-Pipeline")
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.driver.memory", "4g")
        .config("spark.driver.extraJavaOptions", _JAVA_OPENS)
        .config("spark.executor.extraJavaOptions", _JAVA_OPENS)
        .getOrCreate()
    )


def _load_transactions_spark(spark: SparkSession, data_dir: str):
    """
    Lee todos los *_Tran.csv directamente con el lector nativo de Spark.
    Formato por columna: date|store_id|client_id|items_separados_por_espacio
    Sin header, separador |.
    """
    import glob as _glob

    txn_dir = os.path.join(data_dir, 'Transactions')
    files = sorted(_glob.glob(os.path.join(txn_dir, '*_Tran.csv')))
    if not files:
        raise FileNotFoundError(f"No se encontraron *_Tran.csv en {txn_dir}")

    print(f"  Leyendo {len(files)} archivos de transacciones con Spark...")

    # Contar filas por archivo con pandas solo para el reporte (rápido, sin Spark)
    import pandas as _pd
    for fpath in files:
        n = sum(1 for _ in open(fpath, encoding='utf-8'))
        print(f"    {os.path.basename(fpath)}: {n:,} transacciones")

    # Schema raw: 4 columnas separadas por |
    raw_schema = StructType([
        StructField('date',      StringType(),  True),
        StructField('store_id',  IntegerType(), True),
        StructField('client_id', IntegerType(), True),
        StructField('items_str', StringType(),  True),
    ])

    # Leer con el lector nativo de Spark → los executors leen desde disco
    # directamente, sin serializar datos gigantes por el driver.
    raw_sdf = (
        spark.read
        .option('sep', '|')
        .option('header', 'false')
        .schema(raw_schema)
        .csv([f.replace('\\', '/') for f in files])
    )

    # Agregar transaction_id, explotar ítems, parsear fecha — todo en Spark
    txn_sdf = (
        raw_sdf
        .withColumn('transaction_id', F.monotonically_increasing_id())
        .withColumn('items_arr',      F.split(F.col('items_str'), ' '))
        .withColumn('category_id',    F.explode(F.col('items_arr')))
        .filter(F.col('category_id') != '')
        .withColumn('category_id', F.col('category_id').cast(IntegerType()))
        .withColumn('date',         F.to_date(F.col('date'), 'yyyy-MM-dd'))
        .select('transaction_id', 'date', 'store_id', 'client_id', 'category_id')
    )

    # El DataFrame se cachea después del join con categorías en run_spark_pipeline
    return txn_sdf
def _load_categories_spark(spark: SparkSession, data_dir: str):
    """
    Carga Categories.csv con el lector nativo de Spark.
    Formato: category_id|category_name  (sin header, separador |)
    """
    path = os.path.join(data_dir, 'Products', 'Categories.csv')
    cats_schema = StructType([
        StructField('category_id',   IntegerType(), True),
        StructField('category_name', StringType(),  True),
    ])
    return (
        spark.read
        .option('sep', '|')
        .option('header', 'false')
        .schema(cats_schema)
        .csv(path.replace('\\', '/'))
    )


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

def _compute_clustering_spark(features_sdf, txn_sdf, cats_sdf, output_dir: str) -> dict:
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
        predictionCol='segment_id',
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
    centroids_scaled = np.array(best_model.clusterCenters())
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

    # ------------------------------------------------------------------
    # 7. Guardar client_segments.json
    # ------------------------------------------------------------------
    seg_labels_map = {str(s['segment_id']): s['label'] for s in segments}

    # Colectar todos los client_id → segment_id (puede ser grande pero es solo una vez)
    all_clients_pd = df_final.select('client_id', 'segment_id').toPandas()

    # Top 10 categorías por segmento usando cats_sdf para resolver nombres
    seg_top_cats: dict = {}
    # txn_sdf ya puede traer category_name; usar solo el de cats_sdf para evitar ambigüedad
    txn_no_catname = txn_sdf.drop('category_name') if 'category_name' in txn_sdf.columns else txn_sdf
    joined = txn_no_catname.join(cats_sdf.select('category_id', 'category_name'), on='category_id', how='left')
    joined = joined.join(
        df_final.select('client_id', 'segment_id'), on='client_id', how='left'
    )
    for sid in range(best_k):
        top_pd = (
            joined.filter(F.col('segment_id') == sid)
            .groupBy('category_name')
            .agg(F.countDistinct('client_id').alias('n_clients'))
            .orderBy(F.desc('n_clients'))
            .limit(10)
            .toPandas()
        )
        seg_top_cats[str(sid)] = top_pd['category_name'].tolist()

    cs_result = {
        'generated_at':          pd.Timestamp.now().isoformat(),
        'n_clients':              n_clients,
        'client_segments':        {
            str(r['client_id']): int(r['segment_id'])
            for _, r in all_clients_pd.iterrows()
        },
        'segment_top_categories': seg_top_cats,
        'segment_labels':         seg_labels_map,
    }
    cs_path = os.path.join(output_dir, 'client_segments.json')
    with open(cs_path, 'w', encoding='utf-8') as f:
        json.dump(cs_result, f, ensure_ascii=False)
    print(f"    ✓ client_segments.json ({os.path.getsize(cs_path)/1024:.0f} KB)")

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

    # Muestrear si hay demasiados cestos para FP-Growth (evita OOM)
    if n_txns > FPG_MAX_BASKETS:
        fraction = FPG_MAX_BASKETS / n_txns
        baskets_sdf = baskets_sdf.sample(fraction=fraction, seed=42)
        n_sampled = FPG_MAX_BASKETS
        print(f"    FP-Growth sobre ~{n_sampled:,} cestos (muestra {fraction:.1%}) · {n_cats} categorías")
    else:
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

    # Descartar reglas con valores no finitos (NaN / inf) que rompen JSON
    rules = [r for r in rules if all(
        isinstance(r[k], (int, float)) and math.isfinite(r[k])
        for k in ('support', 'confidence', 'lift')
    )]

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
    results['clustering'] = _compute_clustering_spark(features_sdf, txn_sdf, cats_sdf, output_dir)
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
