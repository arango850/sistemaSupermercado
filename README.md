# Sistema de Análisis de Transacciones de Supermercado

Sistema full-stack de inteligencia de negocio para análisis de transacciones de supermercado. Combina un pipeline de análisis en Python con una API REST en Django y un dashboard interactivo en React.

---

## Tabla de contenidos

1. [Descripción general](#descripción-general)
2. [Arquitectura del sistema](#arquitectura-del-sistema)
3. [Dataset](#dataset)
4. [Pipeline de análisis](#pipeline-de-análisis)
   - [Carga de datos](#1-carga-de-datos--data_loaderpy)
   - [Resumen ejecutivo](#2-resumen-ejecutivo--executive_summarypy)
   - [Visualizaciones analíticas](#3-visualizaciones-analíticas--analytical_chartspy)
   - [Segmentación K-Means](#4-segmentación-de-clientes--clusteringpy)
   - [Recomendaciones](#5-recomendador-de-categorías--recommenderpy)
   - [Pipeline Spark](#6-pipeline-alternativo-spark--spark_pipelinepy)
5. [Backend Django](#backend-django)
6. [Frontend React](#frontend-react)
7. [Cómo ejecutar el proyecto](#cómo-ejecutar-el-proyecto)
8. [API Reference](#api-reference)
9. [Resultados obtenidos](#resultados-obtenidos)

---

## Descripción general

El sistema procesa datos de transacciones de 4 tiendas de supermercado durante el primer semestre de 2013 y produce:

- **Resumen ejecutivo** con KPIs del negocio
- **Visualizaciones analíticas** de series de tiempo, distribuciones y correlaciones
- **Segmentación de clientes** mediante K-Means (ML supervisado)
- **Recomendaciones de productos** mediante reglas de asociación (market basket analysis)

El pipeline admite dos motores de procesamiento intercambiables: **pandas/scikit-learn** (uso local) y **Apache Spark / PySpark** (escalable a cluster).

---

## Arquitectura del sistema

```
sistemaSupermercado/
│
├── DataSet/                        # Datos originales (CSV)
│   ├── Transactions/               # Un archivo por tienda
│   │   ├── 102_Tran.csv
│   │   ├── 103_Tran.csv
│   │   ├── 107_Tran.csv
│   │   └── 110_Tran.csv
│   └── Products/
│       ├── Categories.csv          # 50 categorías con nombre
│       └── ProductCategory.csv     # Mapa producto → categoría
│
├── analysis/                       # Pipeline Python
│   ├── data_loader.py
│   ├── executive_summary.py
│   ├── analytical_charts.py
│   ├── clustering.py               # K-Means
│   ├── recommender.py              # Reglas de asociación
│   ├── spark_pipeline.py           # Alternativa PySpark
│   ├── main.py                     # Orquestador
│   └── requirements.txt
│
├── backend/                        # Django + DRF (API REST)
│   ├── api/
│   │   ├── models.py               # ORM: AnalysisRun, Category
│   │   ├── views.py                # Endpoints
│   │   └── urls.py
│   ├── supermercado/settings.py
│   └── requirements.txt
│
├── frontend/                       # Vite + React (dashboard)
│   ├── src/
│   │   ├── pages/
│   │   │   ├── ExecutiveSummary.jsx
│   │   │   ├── AnalyticalCharts.jsx
│   │   │   ├── Segments.jsx
│   │   │   └── Recommendations.jsx
│   │   ├── components/
│   │   └── api/client.js
│   └── package.json
│
└── output/                         # JSONs generados (ignorados en git)
    ├── executive_summary.json
    ├── time_series.json
    ├── boxplot_data.json
    ├── heatmap_data.json
    ├── clustering.json
    └── recommendations.json
```

**Flujo de datos:**

```
CSV files → data_loader.py → módulos de análisis → output/*.json → Django API → React Dashboard
```

El backend Django **no procesa datos**; únicamente sirve los JSON pre-calculados. El pipeline Python corre en un hilo de fondo cuando el usuario pulsa "Actualizar análisis".

---

## Dataset

| Atributo | Valor |
|---|---|
| Período | 2013-01-01 → 2013-06-30 (6 meses) |
| Tiendas | 4 (códigos: 102, 103, 107, 110) |
| Transacciones únicas | 1,108,987 |
| Clientes únicos | 131,186 |
| Categorías referenciadas | 449 |
| Registros explosionados | 10,591,793 (un registro = 1 unidad comprada) |
| Categorías con nombre en CSV | 50 |

**Formato de los archivos de transacciones:**

```
fecha|tienda_id|cliente_id|cod1 cod2 cod3 ...
2013-01-15|102|4823|51 68 23 45
```

Cada código en la última columna es el ID de una categoría comprada (1 código = 1 unidad). Una misma fila puede tener decenas de códigos.

**Para agregar nuevos datos:** colocar un archivo con formato `NUMERO_Tran.csv` en `DataSet/Transactions/` y ejecutar el pipeline. No se requiere ningún otro cambio.

---

## Pipeline de análisis

El orquestador `main.py` ejecuta 6 pasos secuenciales y produce un JSON por paso:

```python
run_pipeline(data_dir, output_dir)
  [1/6] Carga de datos          →  DataFrame en memoria
  [2/6] Resumen ejecutivo       →  executive_summary.json
  [3/6] Visualizaciones         →  time_series.json, boxplot_data.json, heatmap_data.json
  [4/6] Segmentación K-Means    →  clustering.json
  [5/6] Recomendaciones         →  recommendations.json
  [6/6] Índice de archivos      →  index.json
```

Tiempo total de ejecución en el dataset actual: **≈ 103 segundos**.

---

### 1. Carga de datos — `data_loader.py`

Lee todos los archivos `*_Tran.csv` con `glob.glob`, los concatena y los **explota**: transforma cada fila (1 transacción con N categorías) en N filas (1 fila por categoría).

```
Antes: 1 fila  →  2013-01-15 | 102 | 4823 | "51 68 23"
Después: 3 filas → (4823, 51), (4823, 68), (4823, 23)
```

El resultado es un DataFrame con columnas: `transaction_id`, `date`, `store_id`, `client_id`, `category_id`, `quantity`, `category_name`.

---

### 2. Resumen ejecutivo — `executive_summary.py`

Calcula KPIs agregados directamente sobre el DataFrame explosionado:

- Total unidades vendidas, transacciones, clientes, categorías, tiendas
- Top 10 productos y clientes por volumen
- Ventas por tienda, por día de la semana y por mes (heatmap semanal)
- Días pico de actividad

---

### 3. Visualizaciones analíticas — `analytical_charts.py`

Genera tres conjuntos de datos:

**Series de tiempo:** agrupaciones diarias, semanales, mensuales y por tienda de `num_transactions` y `total_units`.

**Distribuciones (boxplot):** histograma del tamaño de cesta (ítems por transacción) y estadísticas descriptivas por categoría.

**Matriz de correlación:** calcula 7 features por cliente y produce una matriz de correlación de Pearson 7×7. Features: `purchase_frequency`, `total_units`, `avg_basket_size`, `avg_categories_per_txn`, `category_diversity`, `num_stores_visited`, `active_days`.

---

### 4. Segmentación de clientes — `clustering.py`

**Algoritmo:** K-Means (scikit-learn)

**Features por cliente (5 dimensiones):**

| Feature | Descripción |
|---|---|
| `purchase_frequency` | Número de transacciones únicas en el período |
| `total_units` | Total de unidades compradas |
| `avg_basket_size` | Promedio de ítems por transacción |
| `category_diversity` | Número de categorías distintas compradas |
| `active_days` | Días únicos en los que realizó compras |

**Pre-procesamiento:** `StandardScaler` — estandariza cada feature a media=0, desviación estándar=1. Esto es crítico para K-Means porque el algoritmo usa distancias euclidianas; sin escalar, `total_units` (escala 0–1000) dominaría sobre `active_days` (escala 0–180).

**Selección de k — Método del Codo:**

Se evalúan k ∈ {3, 4, 5, 6} calculando dos métricas:

- **Inercia (Within-Cluster Sum of Squares):** suma de distancias al cuadrado de cada punto a su centroide. A menor inercia, más compactos los clusters.
- **Silhouette Score:** mide qué tan bien separado está cada punto de su propio cluster vs. los demás clusters. Rango [-1, 1]; >0.5 indica buena cohesión.

El k con **mayor Silhouette Score** es seleccionado automáticamente.

**Resultados con el dataset:**

```
k=3: inercia=236,219  silhouette=0.5079
k=4: inercia=187,811  silhouette=0.5303  ← seleccionado
k=5: inercia=156,441  silhouette=0.4685
k=6: inercia=137,188  silhouette=0.4322
```

**Segmentos encontrados (k=4):**

| Segmento | Etiqueta | Clientes | % | Frec. compra | Total unid. | Tamaño cesta |
|---|---|---|---|---|---|---|
| 0 | Compradores Esporádicos | 84,490 | 64.4% | 3.26 | 16.97 | 4.96 |
| 1 | Compradores Regulares | 25,266 | 19.3% | 17.43 | 153.54 | 9.14 |
| 2 | Compradores Regulares | 13,433 | 10.2% | 5.22 | 112.78 | 22.27 |
| 3 | Compradores Diversificados | 7,997 | 6.1% | 40.33 | 469.3 | 12.85 |

> **Nota:** El segmento 2 ("Compradores Regulares") tiene frecuencia baja pero un tamaño de cesta muy grande (22 ítems). Son clientes que visitan poco el supermercado pero hacen compras grandes cada vez, posiblemente compras de despensa mensual.

**Salida — `clustering.json`:**
```json
{
  "k": 4,
  "silhouette_score": 0.5303,
  "total_clients": 131186,
  "feature_keys": [...],
  "elbow_data": [{"k": 3, "inertia": 236219, "silhouette": 0.5079}, ...],
  "segments": [{"segment_id": 0, "label": "...", "size": 84490, "centroid": {...}, "stats": {...}}, ...],
  "client_sample": [{"client_id": ..., "segment_id": ..., "purchase_frequency": ...}, ...]
}
```

---

### 5. Recomendador de categorías — `recommender.py`

**Algoritmo:** Reglas de asociación por co-ocurrencia (market basket analysis).

A diferencia de Apriori (que enumera itemsets de forma recursiva), este módulo usa **álgebra matricial dispersa** para calcular co-ocurrencias de forma eficiente:

**Paso 1 — Matriz dispersa binaria X (transacciones × categorías):**

```
X[i, j] = 1  si la transacción i incluye la categoría j
X[i, j] = 0  en caso contrario

Dimensiones: 1,108,987 × 449
Entradas no nulas: 10,591,793
Tipo: scipy.sparse.csr_matrix (boolean)
```

**Paso 2 — Matriz de co-ocurrencia C = X^T · X:**

```
C[a, b] = número de transacciones que contienen tanto A como B
Dimensiones: 449 × 449  (cabe completamente en RAM: ~1.6 MB)
```

La diagonal `C[a, a]` es el conteo individual de cada categoría.

**Paso 3 — Derivación de métricas:**

Para cada par ordenado (A → B):

$$\text{support}(A,B) = \frac{C[a,b]}{N}$$

$$\text{confidence}(A \to B) = \frac{C[a,b]}{C[a,a]} = \frac{support(A,B)}{support(A)}$$

$$\text{lift}(A \to B) = \frac{support(A,B)}{support(A) \cdot support(B)}$$

**Umbrales de filtrado:**

| Parámetro | Valor | Significado |
|---|---|---|
| `MIN_SUPPORT` | 0.02 | La co-ocurrencia debe aparecer en al menos el 2% de las transacciones (≈22,180 txn) |
| `MIN_CONFIDENCE` | 0.25 | Al menos 25% de las veces que se compra A, también se compra B |
| `MIN_LIFT` | 1.2 | La asociación debe ser 1.2× más probable que la coincidencia aleatoria |

**Resultados:**
- 1,283 reglas de asociación generadas
- 61 categorías con al menos una recomendación
- Tiempo de cómputo: ~5 segundos (incluyendo multiplicación matricial)

**Interpretación del lift:**
- `lift = 1.0` → comprar A y comprar B son eventos independientes (regla inútil)
- `lift = 3.9` → comprar A hace 3.9× más probable que también se compre B
- Regla más fuerte encontrada: `Categoría 51 ↔ Categoría 68`, lift ≈ 6.95

**Salida — `recommendations.json`:**
```json
{
  "total_rules": 1283,
  "n_transactions": 1108987,
  "min_support": 0.02,
  "min_confidence": 0.25,
  "min_lift": 1.2,
  "rules": [{"antecedent": "MARGARINAS", "consequent": "LEGUMBRES VERDES",
             "support": 0.0312, "confidence": 0.41, "lift": 3.87}, ...],
  "category_index": {
    "LECHE LIQUIDA": [{"recommendation": "QUESO", "confidence": 0.54, "lift": 2.3}, ...]
  },
  "category_support": [{"category_name": "LECHE LIQUIDA", "support": 0.279}, ...]
}
```

---

### 6. Pipeline alternativo Spark — `spark_pipeline.py`

Implementa el mismo análisis (clustering + recomendaciones) usando **Apache Spark / PySpark**, pensado para escalar a clusters con datasets de millones de registros.

| Componente | Pandas pipeline | Spark pipeline |
|---|---|---|
| K-Means | `sklearn.cluster.KMeans` | `pyspark.ml.clustering.KMeans` |
| Selección de k | `sklearn.metrics.silhouette_score` | `pyspark.ml.evaluation.ClusteringEvaluator` |
| Escalado | `sklearn.preprocessing.StandardScaler` | `pyspark.ml.feature.StandardScaler` |
| Reglas de asociación | Álgebra matricial (scipy) | `pyspark.ml.fpm.FPGrowth` |
| Vectorización | `VectorAssembler` manual | `pyspark.ml.feature.VectorAssembler` |

**Fix de Windows** (incluido en el script): Spark requiere que `SPARK_HOME` no tenga caracteres no-ASCII en la ruta. El script usa `ctypes.windll.kernel32.GetShortPathNameW` para obtener la ruta corta del sistema antes de establecer la variable de entorno.

```python
# Invocación
python spark_pipeline.py [data_dir] [output_dir]
```

Produce los mismos archivos `clustering.json` y `recommendations.json` que el pipeline pandas, por lo que el backend y frontend no requieren cambios.

---

## Backend Django

**Stack:** Django 5.x + Django REST Framework + django-cors-headers  
**Base de datos:** SQLite (solo para tracking del pipeline)  
**Puerto por defecto:** 8080

### Modelos ORM

**`AnalysisRun`** — registra cada ejecución del pipeline:
- `status`: `running` | `completed` | `error`
- `started_at`, `completed_at`, `duration_seconds`
- `total_transactions`, `total_clients`, `total_units`
- `error_msg`

**`Category`** — catálogo de categorías cargado desde `Categories.csv`.

### Patrón de servicio

El backend **no ejecuta análisis en los endpoints GET**. Los módulos Python corren en un **hilo de fondo** (`threading.Thread`) disparado por `POST /api/analysis/run`. El estado se persiste en `AnalysisRun` y los endpoints GET simplemente leen los JSON del directorio `output/`.

```
POST /api/analysis/run
  └─ crea registro AnalysisRun (status=running)
  └─ lanza hilo → run_pipeline() → escribe JSONs
  └─ actualiza registro (status=completed)

GET /api/summary
  └─ lee output/executive_summary.json
  └─ retorna JSON directo
```

---

## Frontend React

**Stack:** Vite 5 + React 18 + React Router 6 + Recharts 2 + Axios  
**Puerto por defecto:** 3001 (proxy `/api` → `http://localhost:8080`)

### Páginas

| Ruta | Componente | Datos |
|---|---|---|
| `/summary` | `ExecutiveSummary.jsx` | `executive_summary.json` |
| `/charts` | `AnalyticalCharts.jsx` | `time_series.json`, `boxplot_data.json`, `heatmap_data.json` |
| `/segments` | `Segments.jsx` | `clustering.json` |
| `/recommendations` | `Recommendations.jsx` | `recommendations.json` |

### Visualizaciones en `/segments`

- Tarjetas KPI: k óptimo, silhouette score, total clientes, % por segmento
- Perfiles por segmento: centroide y media real de cada feature
- **Radar chart:** superpone los 5 features normalizados de todos los segmentos para comparación visual
- **Método del codo:** barras de inercia y silhouette por valor de k (la barra verde = k seleccionado)
- **Scatter plot:** muestra de 2,000 clientes con ejes `purchase_frequency` vs `total_units`, coloreados por segmento

### Visualizaciones en `/recommendations`

- KPI cards: total reglas, parámetros de filtrado, categorías con reglas
- **Buscador con autocompletado:** filtra en tiempo real sobre las 61 categorías con reglas
- **Tabla de resultados:** muestra confianza (con barra visual proporcional) y lift (con badge de color según intensidad)
- **Top 15 reglas por lift:** gráfico horizontal con colores según nivel de lift
- **Top 20 categorías más frecuentes:** soporte individual de cada categoría

---

## Cómo ejecutar el proyecto

### Requisitos previos

- Python 3.10+
- Node.js 18+
- Java 8/11/17 (solo para el pipeline Spark)

### 1. Instalar dependencias

```bash
# Dependencias del análisis
cd analysis
pip install -r requirements.txt

# Dependencias del backend
cd ../backend
pip install -r requirements.txt

# Dependencias del frontend
cd ../frontend
npm install
```

### 2. Preparar la base de datos Django

```bash
cd backend
python manage.py migrate
```

### 3. Generar los JSON de análisis (primera vez)

```bash
cd analysis
python main.py
# Tiempo estimado: ~103 segundos
# Salida: ../output/*.json
```

### 4. Levantar el backend

```bash
cd backend
python manage.py runserver 8080
# API disponible en http://localhost:8080/api/
```

### 5. Levantar el frontend

```bash
cd frontend
npm run dev
# Dashboard disponible en http://localhost:3001
```

### 6. (Opcional) Pipeline con Spark

```bash
cd analysis
python spark_pipeline.py
# Requiere Java instalado y JAVA_HOME configurado
```

### Actualizar con nuevos datos

1. Colocar el nuevo archivo `XXX_Tran.csv` en `DataSet/Transactions/`
2. En el dashboard, pulsar el botón **"Actualizar análisis"** (esquina superior derecha)
3. Esperar ~2 minutos mientras el pipeline recalcula todo
4. Las visualizaciones se actualizan automáticamente al completarse

---

## API Reference

Base URL: `http://localhost:8080/api`

| Método | Endpoint | Descripción |
|---|---|---|
| GET | `/summary` | KPIs ejecutivos, top productos/clientes, heatmap semanal |
| GET | `/charts/time-series` | Series de tiempo diaria/semanal/mensual y por tienda |
| GET | `/charts/boxplot` | Histograma de cestas, estadísticas por categoría |
| GET | `/charts/heatmap` | Matriz de correlación 7×7, muestra de features de clientes |
| GET | `/segments` | Segmentos K-Means, centroides, elbow data, muestra scatter |
| GET | `/recommendations/category` | Metadata + índice completo de categorías con reglas |
| GET | `/recommendations/category?name=LECHE LIQUIDA` | Recomendaciones para una categoría específica |
| GET | `/recommendations/product/<id>` | Recomendaciones por category_id numérico |
| POST | `/analysis/run` | Dispara el pipeline en hilo de fondo |
| GET | `/analysis/status` | Estado de la última ejecución del pipeline |
| GET | `/analysis/history` | Historial de las últimas 20 ejecuciones |
| GET | `/categories` | Catálogo de categorías desde la BD |

---

## Resultados obtenidos

### Dataset procesado

| Métrica | Valor |
|---|---|
| Período analizado | 6 meses (enero–junio 2013) |
| Total unidades vendidas | 10,591,793 |
| Promedio diario de transacciones | ~6,126 |
| Categoría más comprada | LECHE LIQUIDA (≈28% de las transacciones) |
| Tienda con mayor volumen | 103 (407,130 transacciones) |

### Segmentación

| Segmento | Clientes | Característica diferenciadora |
|---|---|---|
| Compradores Esporádicos | 84,490 (64%) | 3 visitas en 6 meses, cesta pequeña |
| Compradores Regulares A | 25,266 (19%) | 17 visitas, cesta media |
| Compradores Regulares B | 13,433 (10%) | 5 visitas pero cesta muy grande (22 ítems) |
| Compradores Diversificados | 7,997 (6%) | 40 visitas, 105 categorías distintas, 469 unidades |

### Recomendaciones

| Métrica | Valor |
|---|---|
| Reglas generadas | 1,283 |
| Categorías con recomendaciones | 61 de 449 |
| Regla más fuerte | Categoría 51 ↔ Categoría 68, lift ≈ 6.95 |
| Tiempo de cómputo | ~5 segundos (multiplicación matricial dispersa) |
| Par más frecuente nombrado | MARGARINAS ↔ LEGUMBRES VERDES, lift ≈ 3.9 |
