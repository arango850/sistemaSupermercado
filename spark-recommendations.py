"""
spark-recommendations.py
------------------------
Sistema de Recomendación de Películas basado en Clusters de Usuarios
Laboratorio Semana 9 — Apache Spark / MovieLens 1M

Estrategia:
  1. Dividir ratings en train (80%) / test (20%).
  2. Construir features por usuario a partir del train.
  3. Agrupar usuarios con K-Means (varios valores de K).
  4. Para cada cluster calcular el Bayesian average score por película.
  5. Personalizar: combinar el score del cluster con la afinidad de género
     individual del usuario → personalized_score = ALPHA*bayesian + (1-ALPHA)*genre_affinity.
  6. Recomendar al usuario las TOP-10 películas mejor puntuadas que NO ha visto en train.
  7. Evaluar Precision@10 y Recall@10 contra el test.
  8. Comparar K y guardar recomendaciones en JSON.

Uso local (Windows):
    python spark-recommendations.py

Uso en cluster (spark-submit):
    spark-submit --master spark://master.us-central1-c.c.lab5-20261.internal:7077 \
        spark-recommendations.py gs://ml-100k/ml-1m

Pasar un segundo argumento para especificar la carpeta de salida (default: ./output):
    python spark-recommendations.py ./ml-1m ./my_output
    spark-submit ... spark-recommendations.py gs://ml-100k/ml-1m gs://my-bucket/output
"""

import sys
import os
import json

# ---------------------------------------------------------------------------
# Ajuste de SPARK_HOME para Windows con caracteres no-ASCII en la ruta
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

# Asegura que los workers Python de Spark usen el mismo intérprete que el driver.
# Sin esto, en Windows el alias "python" del Microsoft Store intercepta la llamada
# y los workers no pueden conectarse (SocketTimeoutException al ejecutar UDFs).
os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)

from pyspark.sql import SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, IntegerType, StringType, DoubleType
)
from pyspark.ml.feature import StringIndexer, VectorAssembler, StandardScaler
from pyspark.ml.clustering import KMeans
from pyspark.ml.evaluation import ClusteringEvaluator

# ---------------------------------------------------------------------------
# Constantes GCS
# ---------------------------------------------------------------------------
GCS_DATASET_PATH_1M = "gs://ml-100k/ml-1m"
GCS_CONNECTOR_JAR   = "gcs-connector-hadoop3-latest.jar"
GCS_CONNECTOR_URL   = (
    "https://storage.googleapis.com/hadoop-lib/gcs/" + GCS_CONNECTOR_JAR
)

# Géneros de MovieLens 100K (columnas internas)
GENRE_NAMES = [
    "unknown", "Action", "Adventure", "Animation", "Childrens",
    "Comedy", "Crime", "Documentary", "Drama", "Fantasy",
    "FilmNoir", "Horror", "Musical", "Mystery", "Romance",
    "SciFi", "Thriller", "War", "Western",
]

ML1M_GENRE_MAP = {
    "Action":      "Action",
    "Adventure":   "Adventure",
    "Animation":   "Animation",
    "Children's":  "Childrens",
    "Comedy":      "Comedy",
    "Crime":       "Crime",
    "Documentary": "Documentary",
    "Drama":       "Drama",
    "Fantasy":     "Fantasy",
    "Film-Noir":   "FilmNoir",
    "Horror":      "Horror",
    "Musical":     "Musical",
    "Mystery":     "Mystery",
    "Romance":     "Romance",
    "Sci-Fi":      "SciFi",
    "Thriller":    "Thriller",
    "War":         "War",
    "Western":     "Western",
}

# Valor mínimo de ratings en test para considerar una película "relevante"
RELEVANCE_THRESHOLD = 4.0
# Número de recomendaciones a generar por usuario
TOP_N = 10
# Peso del score de cluster vs afinidad personal de género en el score final
# 0.0 = solo preferencia personal  |  1.0 = solo score del cluster
ALPHA = 0.6
# Pre-filtro por cluster: solo las top PRE_FILTER_N películas por bayesian_score
# reciben el cálculo de genre_affinity. Reduce el tamaño del join de género de
# O(usuarios × películas) a O(usuarios × PRE_FILTER_N).
PRE_FILTER_N = 50


# ---------------------------------------------------------------------------
# Utilidades de ruta y GCS
# ---------------------------------------------------------------------------

def get_path(base: str, filename: str) -> str:
    if base.startswith("gs://"):
        return f"{base.rstrip('/')}/{filename}"
    return os.path.join(base, filename)


def detect_format(data_path: str) -> str:
    base = data_path.rstrip("/").replace("\\", "/").split("/")[-1].lower()
    return "1m" if base in ("ml-1m", "ml_1m", "1m") else "100k"


def _ensure_gcs_connector() -> str:
    spark_home = os.environ.get("SPARK_HOME", "")
    if not spark_home:
        print("  ADVERTENCIA: SPARK_HOME no definido; no se puede instalar el conector GCS.")
        return ""
    jar_dest = os.path.join(spark_home, "jars", GCS_CONNECTOR_JAR)
    if not os.path.exists(jar_dest):
        print(f"  Descargando conector GCS → {jar_dest} ...")
        try:
            import urllib.request
            urllib.request.urlretrieve(GCS_CONNECTOR_URL, jar_dest)
            print("  Conector GCS descargado correctamente.")
        except Exception as exc:
            print(f"  ADVERTENCIA: No se pudo descargar el conector GCS: {exc}")
            return ""
    return jar_dest


def create_spark_session(local_mode: bool, gcs_jar: str = "") -> SparkSession:
    builder = SparkSession.builder.appName("MovieRecommendation_KMeans")
    if local_mode:
        builder = builder.master("local[*]")
    if gcs_jar:
        builder = (
            builder
            .config("spark.jars", gcs_jar)
            .config("spark.hadoop.fs.gs.impl",
                    "com.google.cloud.hadoop.fs.gcs.GoogleHadoopFileSystem")
            .config("spark.hadoop.fs.AbstractFileSystem.gs.impl",
                    "com.google.cloud.hadoop.fs.gcs.GoogleHadoopFS")
            .config("spark.hadoop.google.cloud.auth.service.account.enable", "true")
        )
    # Disable broadcast joins to avoid OOM when joining large recommendation
    # tables (6040 users x K clusters).  Spark would otherwise try to
    # materialise the whole table in driver memory before broadcasting it.
    builder = (
        builder
        .config("spark.sql.autoBroadcastJoinThreshold", "-1")
        .config("spark.driver.memory", "4g")
    )
    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark


# ---------------------------------------------------------------------------
# Carga de datos (misma lógica que spark-kmeans - copia.py)
# ---------------------------------------------------------------------------

def _read_coloncolon(spark, path, col_names):
    """Lee archivo con separador '::' (ML-1M)."""
    raw = spark.read.text(path)
    split_col = F.split(F.col("value"), "::")
    return raw.select(
        *[split_col[i].alias(name) for i, name in enumerate(col_names)]
    )


def load_ratings(spark, data_path, dataset_format="100k"):
    col_names = ["userId", "movieId", "rating", "timestamp"]
    cast_map  = [IntegerType(), IntegerType(), DoubleType(), IntegerType()]
    if dataset_format == "1m":
        df = _read_coloncolon(spark, get_path(data_path, "ratings.dat"), col_names)
    else:
        schema = StructType([StructField(c, t, True) for c, t in zip(col_names, cast_map)])
        df = spark.read.csv(get_path(data_path, "u1.base"), sep="\t", schema=schema)
    for col_name, col_type in zip(col_names, cast_map):
        df = df.withColumn(col_name, F.col(col_name).cast(col_type))
    return df


def load_users(spark, data_path, dataset_format="100k"):
    if dataset_format == "1m":
        col_names = ["userId", "gender", "age", "occupation", "zipCode"]
        df = _read_coloncolon(spark, get_path(data_path, "users.dat"), col_names)
        df = (df
              .withColumn("userId",     F.col("userId").cast(IntegerType()))
              .withColumn("age",        F.col("age").cast(IntegerType()))
              .withColumn("occupation", F.col("occupation").cast(IntegerType()))
              )
    else:
        schema = StructType([
            StructField("userId",     IntegerType(), True),
            StructField("age",        IntegerType(), True),
            StructField("gender",     StringType(),  True),
            StructField("occupation", StringType(),  True),
            StructField("zipCode",    StringType(),  True),
        ])
        df = spark.read.csv(get_path(data_path, "u.user"), sep="|", schema=schema)
    return df


def load_movies(spark, data_path, dataset_format="100k"):
    if dataset_format == "1m":
        col_names = ["movieId", "title", "genres_str"]
        df = _read_coloncolon(spark, get_path(data_path, "movies.dat"), col_names)
        df = df.withColumn("movieId", F.col("movieId").cast(IntegerType()))
        for ml1m_name, col_name in ML1M_GENRE_MAP.items():
            df = df.withColumn(
                col_name,
                F.when(F.col("genres_str").contains(ml1m_name), 1).otherwise(0)
            )
        df = df.withColumn("unknown", F.lit(0))
        return df.drop("genres_str")
    else:
        fields = [
            StructField("movieId",          IntegerType(), True),
            StructField("title",            StringType(),  True),
            StructField("releaseDate",      StringType(),  True),
            StructField("videoReleaseDate", StringType(),  True),
            StructField("imdbUrl",          StringType(),  True),
        ]
        for g in GENRE_NAMES:
            fields.append(StructField(g, IntegerType(), True))
        return spark.read.csv(
            get_path(data_path, "u.item"),
            sep="|", schema=StructType(fields), encoding="ISO-8859-1"
        )


# ---------------------------------------------------------------------------
# PASO 2: Split Train / Test (80/20)
# ---------------------------------------------------------------------------

def split_train_test(ratings, seed=42):
    """Divide ratings en train (80%) y test (20%) de forma reproducible."""
    print("\n" + "=" * 60)
    print("  PASO 2: SPLIT TRAIN / TEST  (80% / 20%)")
    print("=" * 60)

    train, test = ratings.randomSplit([0.8, 0.2], seed=seed)
    train.cache()
    test.cache()

    total = ratings.count()
    n_train = train.count()
    n_test  = test.count()

    print(f"  Total ratings  : {total:,}")
    print(f"  Train ratings  : {n_train:,}  ({100*n_train/total:.1f}%)")
    print(f"  Test  ratings  : {n_test:,}  ({100*n_test/total:.1f}%)")
    print(f"  Usuarios en train : {train.select('userId').distinct().count():,}")
    print(f"  Usuarios en test  : {test.select('userId').distinct().count():,}")
    return train, test


# ---------------------------------------------------------------------------
# PASO 3 & 4: Feature Engineering + Vectorización
# ---------------------------------------------------------------------------

def build_user_features(train, users, movies, dataset_format="100k"):
    """
    Construye features por usuario a partir del conjunto de ENTRENAMIENTO.
    Igual que en spark-kmeans pero usando solo `train`.
    """
    print("\n" + "=" * 60)
    print("  PASO 3: CONSTRUCCIÓN DE FEATURES  (desde TRAIN)")
    print("=" * 60)

    # a) Estadísticas de rating
    user_stats = train.groupBy("userId").agg(
        F.count("rating").cast(DoubleType()).alias("num_ratings"),
        F.avg("rating").alias("avg_rating"),
        F.stddev("rating").alias("std_rating"),
        F.min("rating").cast(DoubleType()).alias("min_rating"),
        F.max("rating").cast(DoubleType()).alias("max_rating"),
    ).fillna(0.0, subset=["std_rating"])

    # b) Preferencias de género
    genre_cols = movies.select(["movieId"] + GENRE_NAMES)
    ratings_with_genres = train.join(genre_cols, on="movieId", how="left")
    genre_agg_exprs = [
        F.avg(F.when(F.col(g) == 1, F.col("rating"))).alias(f"pref_{g}")
        for g in GENRE_NAMES
    ]
    user_genre_prefs = ratings_with_genres.groupBy("userId").agg(*genre_agg_exprs)
    pref_cols = [f"pref_{g}" for g in GENRE_NAMES]
    user_genre_prefs = user_genre_prefs.fillna(0.0, subset=pref_cols)

    # c) Demografía
    users_enc = users.withColumn(
        "gender_num", F.when(F.col("gender") == "F", 1.0).otherwise(0.0)
    )
    if dataset_format == "1m":
        user_demo = users_enc.select(
            "userId",
            F.col("age").cast(DoubleType()).alias("age"),
            "gender_num",
            F.col("occupation").cast(DoubleType()).alias("occupation_idx"),
        )
    else:
        occ_indexer = StringIndexer(
            inputCol="occupation", outputCol="occupation_idx", handleInvalid="keep"
        )
        users_indexed = occ_indexer.fit(users_enc).transform(users_enc)
        user_demo = users_indexed.select(
            "userId",
            F.col("age").cast(DoubleType()).alias("age"),
            "gender_num",
            "occupation_idx",
        )

    # d) Época preferida: año promedio de películas calificadas + ratio de clásicos (<1980)
    #    Extrae el año del título  p.ej. "Toy Story (1995)" → 1995
    movies_with_year = movies.withColumn(
        "release_year",
        F.regexp_extract(F.col("title"), r"\((\d{4})\)", 1).cast(DoubleType())
    ).select("movieId", "release_year").filter(F.col("release_year") > 0)
    ratings_with_year = train.join(movies_with_year, on="movieId", how="left")
    era_features = ratings_with_year.groupBy("userId").agg(
        F.avg("release_year").alias("era_pref"),
        (F.sum(F.when(F.col("release_year") < 1980, 1).otherwise(0)).cast(DoubleType()) /
         F.count("rating").cast(DoubleType())).alias("classic_ratio"),
    ).fillna({"era_pref": 1990.0, "classic_ratio": 0.0})

    # e) Ratio de ratings altos (≥ 4.0): diferencia usuarios exigentes de generosos
    behavior_features = train.groupBy("userId").agg(
        (F.sum(F.when(F.col("rating") >= 4.0, 1).otherwise(0)).cast(DoubleType()) /
         F.count("rating").cast(DoubleType())).alias("high_rating_ratio"),
    )

    # f) Entropía de diversidad de géneros: distingue especialistas de generalistas
    #    Sin UDF: primero materializa el total como columna real (_total), luego
    #    construye la suma de entropía referenciando F.col("_total") — cada término
    #    es O(1) nodos en el plan, sin el árbol exponencial del enfoque anterior.
    cnt_exprs = [F.sum(F.coalesce(F.col(g), F.lit(0)).cast(DoubleType())).alias(f"cnt_{g}")
                 for g in GENRE_NAMES]
    user_genre_counts = ratings_with_genres.groupBy("userId").agg(*cnt_exprs)
    cnt_cols = [f"cnt_{g}" for g in GENRE_NAMES]

    # Paso 1: totalizar en una columna concreta
    total_sum_expr = F.lit(0.0)
    for _c in cnt_cols:
        total_sum_expr = total_sum_expr + F.col(_c)
    user_genre_counts = user_genre_counts.withColumn("_genre_total", total_sum_expr)

    # Paso 2: sumar los términos -p*log(p) usando F.col("_genre_total") (ref. plana)
    entropy_expr = F.lit(0.0)
    for _c in cnt_cols:
        _p = F.col(_c) / F.col("_genre_total")
        entropy_expr = entropy_expr + F.when(
            F.col(_c) > 0,
            -_p * F.log(_p)
        ).otherwise(F.lit(0.0))

    user_genre_diversity = (
        user_genre_counts
        .withColumn("genre_entropy",
                    F.when(F.col("_genre_total") > 0, entropy_expr).otherwise(F.lit(0.0)))
        .select("userId", "genre_entropy")
        .fillna(0.0, subset=["genre_entropy"])
    )

    user_features = (
        user_stats
        .join(user_genre_prefs,     on="userId", how="inner")
        .join(user_demo,            on="userId", how="inner")
        .join(era_features,         on="userId", how="left")
        .join(behavior_features,    on="userId", how="left")
        .join(user_genre_diversity, on="userId", how="left")
    )
    user_features = user_features.fillna({
        "era_pref": 1990.0, "classic_ratio": 0.0,
        "high_rating_ratio": 0.0, "genre_entropy": 0.0,
    })

    feature_cols = (
        ["num_ratings", "avg_rating", "std_rating", "min_rating", "max_rating",
         "age", "gender_num", "occupation_idx"]
        + pref_cols
        + ["era_pref", "classic_ratio", "high_rating_ratio", "genre_entropy"]
    )

    print(f"  Total features por usuario: {len(feature_cols)}")
    print(f"  Usuarios con features     : {user_features.count():,}")
    print("\n  Muestra de features (5 usuarios):")
    user_features.select(["userId"] + feature_cols[:6]).show(5, truncate=False)

    return user_features, feature_cols


def prepare_features(user_features, feature_cols):
    """Ensambla columnas en vector y aplica StandardScaler."""
    assembler = VectorAssembler(inputCols=feature_cols, outputCol="features_raw")
    assembled = assembler.transform(user_features)
    scaler = StandardScaler(
        inputCol="features_raw", outputCol="features",
        withMean=True, withStd=True
    )
    scaled = scaler.fit(assembled).transform(assembled)
    return scaled


# ---------------------------------------------------------------------------
# PASO 5: Entrenar K-Means con múltiples K
# ---------------------------------------------------------------------------

def train_kmeans_models(scaled, k_values=(3, 5, 8)):
    """
    Entrena K-Means para cada K.
    Evalúa con Silhouette Score y WSSSE.
    Retorna diccionario con resultados por K.
    """
    print("\n" + "=" * 60)
    print("  PASO 5: ENTRENAMIENTO K-MEANS")
    print("=" * 60)

    evaluator = ClusteringEvaluator(
        featuresCol="features",
        predictionCol="cluster",
        metricName="silhouette",
        distanceMeasure="squaredEuclidean",
    )

    results = {}
    for k in k_values:
        print(f"\n  Entrenando K-Means con K={k}...")
        kmeans = KMeans(
            featuresCol="features",
            predictionCol="cluster",
            k=k,
            seed=42,
            maxIter=20,
        )
        model       = kmeans.fit(scaled)
        predictions = model.transform(scaled)
        silhouette  = evaluator.evaluate(predictions)
        wssse       = model.summary.trainingCost

        # Tamaño de cada cluster
        cluster_sizes = (
            predictions.groupBy("cluster").count()
            .orderBy("cluster")
            .collect()
        )

        print(f"    Silhouette = {silhouette:.4f}  |  WSSSE = {wssse:,.2f}")
        print("    Distribución de clusters:")
        for row in cluster_sizes:
            print(f"      Cluster {row['cluster']}: {row['count']:,} usuarios")

        results[k] = {
            "silhouette":    silhouette,
            "wssse":         wssse,
            "model":         model,
            "predictions":   predictions,   # userId, features, cluster, ...
            "cluster_sizes": cluster_sizes,
        }

    # Resumen comparativo
    print("\n  Resumen comparativo de K:")
    print(f"  {'K':>4}  {'Silhouette':>12}  {'WSSSE':>16}")
    print("  " + "-" * 36)
    best_k = max(results, key=lambda k: results[k]["silhouette"])
    for k in k_values:
        marker = " ← mejor Silhouette" if k == best_k else ""
        print(f"  {k:>4}  {results[k]['silhouette']:>12.4f}  "
              f"{results[k]['wssse']:>16,.2f}{marker}")

    return results, best_k


# ---------------------------------------------------------------------------
# PASO 6: Asignar clusters a usuarios
# ---------------------------------------------------------------------------

def get_user_clusters(predictions):
    """Extrae la tabla userId → cluster del resultado de K-Means."""
    return predictions.select("userId", "cluster")


# ---------------------------------------------------------------------------
# PASO 7 & 8: Construir base de recomendaciones por cluster
# ---------------------------------------------------------------------------

def build_cluster_movie_stats(train, user_clusters):
    """
    Para cada (cluster, movieId) calcula:
      - avg_cluster_rating : promedio de ratings de ese cluster para esa película
      - num_cluster_ratings: cuántas veces fue calificada por usuarios del cluster
      - bayesian_score     : Bayesian average que penaliza películas con pocas
                             valoraciones para evitar que ítems vistos 1 sola vez
                             con rating=5 dominen las recomendaciones.

    Fórmula Bayesian average:
        score = (C * global_mean + n * avg_rating) / (C + n)
    donde:
        C          = factor de suavizado = promedio de valoraciones por película en el cluster
        global_mean= promedio global de ratings en el cluster
        n          = num_cluster_ratings de esa (cluster, movieId)

    Un C alto exige más valoraciones antes de alejarse de la media global.
    """
    # Unir train con la asignación de clusters
    train_with_cluster = train.join(user_clusters, on="userId", how="inner")

    cluster_movie_stats = train_with_cluster.groupBy("cluster", "movieId").agg(
        F.avg("rating").alias("avg_cluster_rating"),
        F.count("rating").alias("num_cluster_ratings"),
    )

    # Calcular promedio global y factor C por cluster
    cluster_globals = train_with_cluster.groupBy("cluster").agg(
        F.avg("rating").alias("cluster_global_mean"),
        # C = promedio de valoraciones por película dentro del cluster
        (F.count("rating") / F.countDistinct("movieId")).alias("cluster_C"),
    )

    cluster_movie_stats = cluster_movie_stats.join(cluster_globals, on="cluster", how="left")

    # Bayesian average score
    cluster_movie_stats = cluster_movie_stats.withColumn(
        "bayesian_score",
        (F.col("cluster_C") * F.col("cluster_global_mean")
         + F.col("num_cluster_ratings") * F.col("avg_cluster_rating"))
        / (F.col("cluster_C") + F.col("num_cluster_ratings"))
    ).drop("cluster_global_mean", "cluster_C")

    return cluster_movie_stats


# ---------------------------------------------------------------------------
# PASO 9: Generar recomendaciones TOP-N
# ---------------------------------------------------------------------------

def generate_recommendations(train, user_clusters, cluster_movie_stats,
                              user_features, movies_df, top_n=TOP_N):
    """
    Para cada usuario genera un ranking personalizado combinando dos señales:

      1. bayesian_score   : popularidad + rating promedio de la película dentro
                            del cluster al que pertenece el usuario.
      2. genre_affinity   : afinidad personal del usuario con los géneros de la
                            película, calculada como la media ponderada de sus
                            preferencias de género (pref_<Genre>) sobre los
                            géneros que tiene la película.

    Score final:
        personalized_score = ALPHA * bayesian_score + (1 - ALPHA) * genre_affinity

    Ambas señales están en escala 1-5, por lo que la mezcla es directa.
    ALPHA controla cuánto peso tiene el comportamiento colectivo del cluster
    frente a la preferencia individual de género.

    Pasos:
      1. Obtiene cluster del usuario.
      2. Cruza con películas del cluster (excluye ya vistas en train).
      3. Calcula genre_affinity por (usuario, película).
      4. Calcula personalized_score y rankea dentro de cada usuario.
      5. Selecciona top_n.
    """
    print(f"\n  Generando recomendaciones TOP-{top_n} por usuario "
          f"(ALPHA={ALPHA}, personalización por género, pre-filtro={PRE_FILTER_N})...")

    # Películas ya vistas por cada usuario en train
    seen = train.select("userId", "movieId")

    # ------------------------------------------------------------------
    # Pre-filtro por cluster: conservar solo las top PRE_FILTER_N películas
    # de cada cluster según bayesian_score, ANTES de unir con usuarios.
    # Esto reduce el tamaño del join de género de O(U×M) a O(U×PRE_FILTER_N).
    # ------------------------------------------------------------------
    window_cluster = Window.partitionBy("cluster").orderBy(F.desc("bayesian_score"))
    cluster_top = (
        cluster_movie_stats
        .withColumn("_cr", F.row_number().over(window_cluster))
        .filter(F.col("_cr") <= PRE_FILTER_N)
        .drop("_cr")
    )

    # Combinar cada usuario con las top-PRE_FILTER_N películas de su cluster
    user_cluster_movies = user_clusters.join(cluster_top, on="cluster", how="inner")

    # Eliminar películas ya vistas
    recs_candidates = user_cluster_movies.join(
        seen, on=["userId", "movieId"], how="left_anti"
    )

    # ------------------------------------------------------------------
    # Personalización: genre_affinity por (usuario, película)
    # ------------------------------------------------------------------
    # Preferencias de género del usuario (pref_Action, pref_Drama, ...)
    pref_cols = [f"pref_{g}" for g in GENRE_NAMES]
    user_genre_prefs = user_features.select(["userId"] + pref_cols)

    # Géneros binarios de cada película (Action=1, Drama=0, ...)
    movie_genre_cols = GENRE_NAMES
    movie_genres = movies_df.select(["movieId"] + movie_genre_cols)

    # Unir candidatos con preferencias del usuario y géneros de la película
    recs_candidates = (
        recs_candidates
        .join(user_genre_prefs, on="userId", how="left")
        .join(movie_genres,     on="movieId", how="left")
        .fillna(0.0, subset=pref_cols)
        .fillna(0,   subset=movie_genre_cols)
    )

    # Producto punto: sum(pref_G * G_flag) / max(1, sum(G_flag))
    # Resultado: rating promedio del usuario en los géneros que tiene la película.
    dot_product = sum(F.col(f"pref_{g}") * F.col(g).cast(DoubleType())
                      for g in GENRE_NAMES)
    num_genres  = sum(F.col(g).cast(DoubleType()) for g in GENRE_NAMES)

    recs_candidates = recs_candidates.withColumn(
        "genre_affinity",
        dot_product / F.greatest(num_genres, F.lit(1.0))
    )

    # Score final: mezcla lineal de ambas señales
    recs_candidates = recs_candidates.withColumn(
        "personalized_score",
        F.lit(ALPHA) * F.col("bayesian_score")
        + F.lit(1.0 - ALPHA) * F.col("genre_affinity")
    )

    # Limpiar columnas intermedias de género para no inflar el DataFrame
    recs_candidates = recs_candidates.drop(*pref_cols).drop(*movie_genre_cols)

    # ------------------------------------------------------------------
    # Ranking dentro de cada usuario por personalized_score DESC
    # ------------------------------------------------------------------
    window_spec = Window.partitionBy("userId").orderBy(
        F.desc("personalized_score"),
        F.desc("bayesian_score"),
    )
    recs_ranked = recs_candidates.withColumn("rank", F.row_number().over(window_spec))

    recs_top = recs_ranked.filter(F.col("rank") <= top_n)

    print(f"  Usuarios con recomendaciones generadas: "
          f"{recs_top.select('userId').distinct().count():,}")

    return recs_top


# ---------------------------------------------------------------------------
# PASO 10: Evaluación Precision@N y Recall@N
# ---------------------------------------------------------------------------

def evaluate_recommendations(recs_top, test, top_n=TOP_N,
                              relevance_threshold=RELEVANCE_THRESHOLD):
    """
    Precision@N: fracción de recomendaciones que son relevantes en test.
    Recall@N   : fracción de ítems relevantes en test que fueron recomendados.

    Un ítem es "relevante" si el usuario lo calificó con >= relevance_threshold en test.

    Retorna (precision, recall, DataFrame de métricas por usuario).
    """
    # Ítems relevantes en test por usuario
    relevant = (
        test
        .filter(F.col("rating") >= relevance_threshold)
        .groupBy("userId")
        .agg(F.collect_set("movieId").alias("relevant_movies"))
    )

    # Recomendaciones como set por usuario
    recs_set = (
        recs_top
        .groupBy("userId")
        .agg(F.collect_set("movieId").alias("recommended_movies"))
    )

    # Unir (solo usuarios que tienen tanto recomendaciones como ítems relevantes en test)
    eval_df = recs_set.join(relevant, on="userId", how="inner")

    # Calcular hits (intersección), precision y recall
    eval_df = eval_df.withColumn(
        "hits",
        F.size(F.array_intersect(F.col("recommended_movies"), F.col("relevant_movies")))
    ).withColumn(
        "num_recommended", F.size(F.col("recommended_movies"))
    ).withColumn(
        "num_relevant",    F.size(F.col("relevant_movies"))
    ).withColumn(
        "precision_at_n",
        F.col("hits") / F.col("num_recommended")
    ).withColumn(
        "recall_at_n",
        F.col("hits") / F.col("num_relevant")
    )

    # Métricas globales (promedio sobre usuarios)
    agg = eval_df.agg(
        F.avg("precision_at_n").alias("mean_precision"),
        F.avg("recall_at_n").alias("mean_recall"),
        F.count("userId").alias("num_evaluated_users"),
        F.avg("hits").alias("avg_hits"),
        F.avg("num_relevant").alias("avg_relevant"),
        F.avg("num_recommended").alias("avg_recommended"),
    ).collect()[0]

    precision = agg["mean_precision"]
    recall    = agg["mean_recall"]

    print(f"\n    Precision@{top_n}  = {precision:.4f}")
    print(f"    Recall@{top_n}     = {recall:.4f}")
    print(f"    Usuarios evaluados: {agg['num_evaluated_users']:,}")
    print(f"    Hits promedio     : {agg['avg_hits']:.2f}")
    print(f"    Relevantes prom.  : {agg['avg_relevant']:.2f}")
    print(f"    Recomendados prom.: {agg['avg_recommended']:.2f}")

    return precision, recall, eval_df


# ---------------------------------------------------------------------------
# PASO 11: Pipeline completo para múltiples K
# ---------------------------------------------------------------------------

def run_full_pipeline(train, test, users, movies, scaled, user_features,
                      k_values, dataset_format, top_n=TOP_N):
    """
    Ejecuta el pipeline de recomendación para cada valor de K.
    Entrena K-Means, genera recomendaciones (con personalización por género)
    y evalúa. Retorna diccionario de resultados por K.
    """
    print("\n" + "=" * 60)
    print("  PASO 11: PIPELINE COMPLETO PARA MÚLTIPLES K")
    print("=" * 60)

    kmeans_results, best_k_by_silhouette = train_kmeans_models(scaled, k_values)

    pipeline_results = {}
    for k in k_values:
        print(f"\n{'=' * 60}")
        print(f"  Evaluando sistema de recomendación con K={k}")
        print(f"{'=' * 60}")

        predictions      = kmeans_results[k]["predictions"]
        user_clusters    = get_user_clusters(predictions)

        cluster_stats    = build_cluster_movie_stats(train, user_clusters)
        recs_top         = generate_recommendations(
            train, user_clusters, cluster_stats,
            user_features, movies, top_n=top_n
        )

        print(f"\n  Evaluación (K={k}, threshold={RELEVANCE_THRESHOLD}):")
        precision, recall, eval_df = evaluate_recommendations(
            recs_top, test, top_n=top_n
        )

        pipeline_results[k] = {
            "silhouette":     kmeans_results[k]["silhouette"],
            "wssse":          kmeans_results[k]["wssse"],
            "precision":      precision,
            "recall":         recall,
            "recs_top":       recs_top,
            "eval_df":        eval_df,
            "user_clusters":  user_clusters,
            "cluster_stats":  cluster_stats,
        }

    return pipeline_results, best_k_by_silhouette


# ---------------------------------------------------------------------------
# Análisis de clusters (para el informe)
# ---------------------------------------------------------------------------

def analyze_clusters(predictions, users, k):
    """Describe cada cluster en términos demográficos y de comportamiento."""
    print(f"\n  Análisis de clusters (K={k}):")

    cluster_col = predictions.select(
        "userId", "cluster", "avg_rating", "num_ratings"
    )
    cluster_users = cluster_col.join(users, on="userId", how="left")

    print(f"\n  Distribución de usuarios por cluster (K={k}):")
    cluster_users.groupBy("cluster").count().orderBy("cluster").show(truncate=False)

    print(f"\n  Estadísticas por cluster (K={k}):")
    cluster_users.groupBy("cluster").agg(
        F.count("userId").alias("num_usuarios"),
        F.round(F.avg("age"), 1).alias("edad_promedio"),
        F.round(
            F.avg(F.when(F.col("gender") == "F", 1).otherwise(0)) * 100, 1
        ).alias("pct_mujeres"),
        F.round(F.avg("avg_rating"), 3).alias("rating_promedio"),
        F.round(F.avg("num_ratings"), 1).alias("peliculas_calificadas_promedio"),
    ).orderBy("cluster").show(truncate=False)


# ---------------------------------------------------------------------------
# PASO 12: Guardar recomendaciones en JSON
# ---------------------------------------------------------------------------

def save_recommendations(recs_top, movies, output_path, k, spark,
                          num_sample_users=None):
    """
    Guarda las recomendaciones en JSON.
    Si output_path comienza con gs:// guarda directamente en GCS.
    De lo contrario guarda en el sistema de archivos local.

    Formato por línea (newline-delimited JSON):
      {"userId": 1, "cluster": 2, "recommendations": [{"rank": 1, "movieId": 123,
        "title": "...", "avg_cluster_rating": 4.5, "num_cluster_ratings": 100}, ...]}

    También guarda un archivo de muestra con los primeros 20 usuarios
    si num_sample_users es None (o el valor especificado).
    """
    print(f"\n  Guardando recomendaciones (K={k})...")

    # Enriquecer con títulos de películas
    movie_titles = movies.select("movieId", "title")
    recs_with_title = recs_top.join(movie_titles, on="movieId", how="left")

    # Agrupar por usuario → array de structs ordenados por rank
    recs_grouped = (
        recs_with_title
        .orderBy("userId", "rank")
        .groupBy("userId", "cluster")
        .agg(
            F.collect_list(
                F.struct(
                    F.col("rank"),
                    F.col("movieId"),
                    F.col("title"),
                    F.round(F.col("personalized_score"), 4).alias("personalized_score"),
                    F.round(F.col("bayesian_score"), 4).alias("bayesian_score"),
                    F.round(F.col("genre_affinity"), 4).alias("genre_affinity"),
                    F.round(F.col("avg_cluster_rating"), 4).alias("avg_cluster_rating"),
                    F.col("num_cluster_ratings"),
                )
            ).alias("recommendations")
        )
        .orderBy("userId")
    )

    # Convertir a JSON nativo de Python para serialización
    rows = recs_grouped.collect()

    records = []
    for row in rows:
        rec_list = []
        for r in row["recommendations"]:
            rec_list.append({
                "rank":                r["rank"],
                "movieId":             r["movieId"],
                "title":               r["title"],
                "personalized_score":  float(r["personalized_score"]) if r["personalized_score"] is not None else None,
                "bayesian_score":      float(r["bayesian_score"]) if r["bayesian_score"] is not None else None,
                "genre_affinity":      float(r["genre_affinity"]) if r["genre_affinity"] is not None else None,
                "avg_cluster_rating":  float(r["avg_cluster_rating"]) if r["avg_cluster_rating"] is not None else None,
                "num_cluster_ratings": int(r["num_cluster_ratings"]),
            })
        # Ordenar explícitamente por rank (collect_list no garantiza orden)
        rec_list.sort(key=lambda x: x["rank"])
        records.append({
            "userId":          int(row["userId"]),
            "cluster":         int(row["cluster"]),
            "recommendations": rec_list,
        })

    # ---------- Guardar en destino ----------
    full_json_path   = f"{output_path}/recommendations_k{k}.json"
    sample_json_path = f"{output_path}/recommendations_k{k}_sample20.json"

    n_sample = num_sample_users if num_sample_users else 20
    sample_records = records[:n_sample]

    if output_path.startswith("gs://"):
        # Escribir en GCS a través del DataFrame de Spark
        recs_df_for_write = spark.createDataFrame(
            [(r["userId"], r["cluster"], json.dumps(r["recommendations"])) for r in records],
            ["userId", "cluster", "recommendations_json"]
        )
        recs_df_for_write.write.mode("overwrite").json(full_json_path)

        sample_df = spark.createDataFrame(
            [(r["userId"], r["cluster"], json.dumps(r["recommendations"])) for r in sample_records],
            ["userId", "cluster", "recommendations_json"]
        )
        sample_df.write.mode("overwrite").json(sample_json_path)
        print(f"  Recomendaciones guardadas en: {full_json_path}")
        print(f"  Muestra (20 usuarios) en    : {sample_json_path}")
    else:
        # Escribir localmente
        os.makedirs(output_path, exist_ok=True)
        with open(full_json_path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        with open(sample_json_path, "w", encoding="utf-8") as f:
            for r in sample_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"  Recomendaciones guardadas en: {full_json_path}")
        print(f"  Muestra (20 usuarios) en    : {sample_json_path}")

    return records


# ---------------------------------------------------------------------------
# Guardar recomendaciones del mejor K en formato API (lab semana 10)
# ---------------------------------------------------------------------------

def save_api_recommendations(recs_top, movies, output_path, best_k, spark):
    """
    Guarda un único archivo 'recommendations.json' con el formato requerido
    por el laboratorio semana 10:

      [
        {
          "user_id": 123,
          "cluster": 2,
          "recommendations": [
            {"movie_id": 10, "movie_title": "GoldenEye (1995)", "score": 4.8},
            ...
          ]
        },
        ...
      ]

    El campo 'score' corresponde al personalized_score redondeado a 4 decimales.
    Solo se genera para el mejor K (por silhouette), no para todos los K.
    """
    print(f"\n  Generando recommendations.json para el API (K={best_k})...")

    movie_titles = movies.select("movieId", "title")
    recs_with_title = recs_top.join(movie_titles, on="movieId", how="left")

    recs_grouped = (
        recs_with_title
        .orderBy("userId", "rank")
        .groupBy("userId", "cluster")
        .agg(
            F.collect_list(
                F.struct(
                    F.col("rank"),
                    F.col("movieId"),
                    F.col("title"),
                    F.round(F.col("personalized_score"), 4).alias("personalized_score"),
                )
            ).alias("recommendations")
        )
        .orderBy("userId")
    )

    rows = recs_grouped.collect()

    records = []
    for row in rows:
        rec_list = []
        for r in row["recommendations"]:
            rec_list.append({
                "movie_id":    r["movieId"],
                "movie_title": r["title"],
                "score":       float(r["personalized_score"]) if r["personalized_score"] is not None else None,
            })
        # collect_list no garantiza orden → reordenar por rank
        for i, r in enumerate(sorted(row["recommendations"], key=lambda x: x["rank"])):
            rec_list[i] = {
                "movie_id":    r["movieId"],
                "movie_title": r["title"],
                "score":       float(r["personalized_score"]) if r["personalized_score"] is not None else None,
            }
        records.append({
            "user_id":         int(row["userId"]),
            "cluster":         int(row["cluster"]),
            "recommendations": rec_list,
        })

    api_json_path = f"{output_path}/recommendations.json"

    if output_path.startswith("gs://"):
        recs_df = spark.createDataFrame(
            [(r["user_id"], r["cluster"], json.dumps(r["recommendations"])) for r in records],
            ["user_id", "cluster", "recommendations_json"]
        )
        recs_df.write.mode("overwrite").json(api_json_path)
        print(f"  recommendations.json guardado en: {api_json_path}")
    else:
        os.makedirs(output_path, exist_ok=True)
        with open(api_json_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        print(f"  recommendations.json guardado en: {api_json_path}")
        print(f"  Total usuarios en el archivo    : {len(records):,}")

    return records


# ---------------------------------------------------------------------------
# Comparación final de K
# ---------------------------------------------------------------------------

def print_comparison(pipeline_results, k_values, top_n=TOP_N):
    print("\n" + "=" * 60)
    print("  COMPARACIÓN FINAL DE CONFIGURACIONES")
    print("=" * 60)
    print(f"\n  {'K':>4}  {'Silhouette':>12}  {'WSSSE':>16}  "
          f"{'Precision@'+str(top_n):>14}  {'Recall@'+str(top_n):>12}")
    print("  " + "-" * 64)
    for k in k_values:
        r = pipeline_results[k]
        print(f"  {k:>4}  {r['silhouette']:>12.4f}  {r['wssse']:>16,.2f}  "
              f"{r['precision']:>14.4f}  {r['recall']:>12.4f}")

    best_prec_k = max(k_values, key=lambda k: pipeline_results[k]["precision"])
    best_rec_k  = max(k_values, key=lambda k: pipeline_results[k]["recall"])
    print(f"\n  Mejor Precision@{top_n}: K={best_prec_k} "
          f"({pipeline_results[best_prec_k]['precision']:.4f})")
    print(f"  Mejor Recall@{top_n}   : K={best_rec_k} "
          f"({pipeline_results[best_rec_k]['recall']:.4f})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # -----------------------------------------------------------------------
    # Argumentos y rutas
    # -----------------------------------------------------------------------
    if len(sys.argv) > 1:
        data_path  = sys.argv[1]
        local_mode = False
        print(f"Modo CLUSTER — dataset: {data_path}")
    elif sys.platform != "win32":
        data_path  = GCS_DATASET_PATH_1M
        local_mode = False
        print(f"Modo CLUSTER (GCS) — dataset: {data_path}")
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        data_path  = os.path.join(script_dir, "ml-1m")
        local_mode = True
        print(f"Modo LOCAL — dataset: {data_path}")

    # Carpeta de salida (segundo argumento opcional)
    if len(sys.argv) > 2:
        output_path = sys.argv[2]
    elif data_path.startswith("gs://"):
        # Mismo bucket, carpeta output al lado del dataset
        output_path = data_path.rstrip("/").rsplit("/", 1)[0] + "/recommendations_output"
    else:
        output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

    dataset_format = detect_format(data_path)
    print(f"Formato dataset : MovieLens {'1M' if dataset_format == '1m' else '100K'}")
    print(f"Carpeta salida  : {output_path}")

    # -----------------------------------------------------------------------
    # Conector GCS
    # -----------------------------------------------------------------------
    gcs_jar = ""
    if data_path.startswith("gs://"):
        gcs_jar = _ensure_gcs_connector()

    # -----------------------------------------------------------------------
    # SparkSession
    # -----------------------------------------------------------------------
    spark = create_spark_session(local_mode, gcs_jar=gcs_jar)
    print(f"Spark version   : {spark.version}")

    # -----------------------------------------------------------------------
    # PASO 1: Cargar datos
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  PASO 1: CARGA DE DATOS")
    print("=" * 60)
    ratings = load_ratings(spark, data_path, dataset_format)
    users   = load_users(spark, data_path, dataset_format)
    movies  = load_movies(spark, data_path, dataset_format)

    print(f"  Ratings cargados : {ratings.count():,}")
    print(f"  Usuarios cargados: {users.count():,}")
    print(f"  Películas cargadas: {movies.count():,}")

    print("\n  Distribución de ratings (1-5):")
    ratings.groupBy("rating").count().orderBy("rating").show(truncate=False)

    print("  Estadísticas descriptivas de ratings:")
    ratings.select("rating").describe().show(truncate=False)

    print("  Distribución de géneros de usuarios:")
    users.groupBy("gender").count().orderBy("gender").show(truncate=False)

    # -----------------------------------------------------------------------
    # PASO 2: Split train / test
    # -----------------------------------------------------------------------
    train, test = split_train_test(ratings, seed=42)

    # -----------------------------------------------------------------------
    # PASO 3 & 4: Features + vectorización (sobre train)
    # -----------------------------------------------------------------------
    user_features, feature_cols = build_user_features(
        train, users, movies, dataset_format
    )
    scaled = prepare_features(user_features, feature_cols)

    # -----------------------------------------------------------------------
    # K valores a evaluar  (mínimo 2 configuraciones distintas)
    # -----------------------------------------------------------------------
    K_VALUES = (3, 5, 8, 10, 15, 20)

    # -----------------------------------------------------------------------
    # PASOS 5-11: Pipeline completo para cada K
    # -----------------------------------------------------------------------
    pipeline_results, best_k_silhouette = run_full_pipeline(
        train, test, users, movies, scaled, user_features,
        k_values=K_VALUES,
        dataset_format=dataset_format,
        top_n=TOP_N,
    )

    # -----------------------------------------------------------------------
    # Análisis de clusters para el mejor K (por silhouette)
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"  ANÁLISIS DETALLADO DE CLUSTERS  (mejor K={best_k_silhouette})")
    print("=" * 60)
    best_predictions = pipeline_results[best_k_silhouette]["recs_top"] \
        .select("userId", "cluster").distinct()
    # Recuperar predicciones completas del modelo
    # (ya las tenemos en recs_top, pero necesitamos avg_rating/num_ratings del scaled)
    full_predictions = (
        scaled.select("userId", "avg_rating", "num_ratings")
        .join(pipeline_results[best_k_silhouette]["user_clusters"], on="userId")
    )
    analyze_clusters(full_predictions, users, best_k_silhouette)

    # Centros del mejor modelo (solo informativo, desde el pipeline)
    # -----------------------------------------------------------------------
    # Comparación de configuraciones
    # -----------------------------------------------------------------------
    print_comparison(pipeline_results, K_VALUES, top_n=TOP_N)

    # -----------------------------------------------------------------------
    # PASO 12: Guardar recommendations.json para el mejor K (API semana 10)
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  PASO 12: GUARDAR RECOMMENDATIONS.JSON (mejor K)")
    print("=" * 60)

    # Usar el mejor K por silhouette score (calidad del clustering)
    best_k = best_k_silhouette
    print(f"\n  Mejor K seleccionado: K={best_k}  "
          f"(silhouette={pipeline_results[best_k]['silhouette']:.4f}  "
          f"precision@{TOP_N}={pipeline_results[best_k]['precision']:.4f})")

    api_records = save_api_recommendations(
        pipeline_results[best_k]["recs_top"],
        movies,
        output_path,
        best_k=best_k,
        spark=spark,
    )

    # Muestra de las primeras 5 entradas en consola
    print(f"\n  Muestra (5 usuarios) del archivo generado:")
    for rec in api_records[:5]:
        print(f"\n  user_id={rec['user_id']}  cluster={rec['cluster']}")
        for item in rec["recommendations"][:3]:
            print(f"    [{item['movie_id']:>4}] {(item['movie_title'] or 'N/A'):<50}  "
                  f"score={item['score']:.4f}")

    spark.stop()
    print("\n✓ Proceso completado exitosamente.")


if __name__ == "__main__":
    main()
