# Supermercado Analytics

Dashboard de inteligencia de negocio para análisis de transacciones de supermercado. Procesa más de 10 millones de registros, segmenta clientes con K-Means y genera recomendaciones de productos mediante reglas de asociación — todo desde una interfaz web interactiva.



---

## Tabla de contenidos

1. [Qué hace](#qué-hace)
2. [Estructura del proyecto](#estructura-del-proyecto)
3. [Requisitos](#requisitos)
4. [Instalación y ejecución](#instalación-y-ejecución)
5. [Agregar nuevos datos](#agregar-nuevos-datos)
6. [API Reference](#api-reference)

---

## Qué hace

| Módulo | Descripción |
|---|---|
| **Resumen Ejecutivo** | KPIs del negocio: total de ventas, transacciones, top 10 productos y clientes, días pico |
| **Visualizaciones Analíticas** | Serie de tiempo, boxplot de distribuciones, heatmap de correlación entre variables |
| **Segmentación** | K-Means sobre 131 k clientes — 4 perfiles de comportamiento de compra |
| **Recomendaciones** | Reglas de asociación: dado un cliente o una categoría, sugiere qué comprar |
| **Motor seleccionable** | Mismo resultado con pipeline **Local** (pandas/scikit-learn, ~60 s) o **Spark** (PySpark MLlib, escalable a clúster) |
| **Actualización en caliente** | Agrega un CSV nuevo, pulsa "Actualizar análisis" y todo se recalcula desde la UI |

---

## Estructura del proyecto

```
sistemaSupermercado/
├── DataSet/
│   ├── Transactions/          # CSVs de transacciones — uno por tienda
│   │   ├── 102_Tran.csv
│   │   ├── 103_Tran.csv
│   │   ├── 107_Tran.csv
│   │   └── 110_Tran.csv
│   └── Products/
│       ├── Categories.csv
│       └── ProductCategory.csv
│
├── analysis/                  # Pipeline Python (motor de análisis)
│   ├── main.py                # Orquestador — punto de entrada
│   ├── data_loader.py
│   ├── executive_summary.py
│   ├── analytical_charts.py
│   ├── clustering.py          # K-Means (scikit-learn)
│   ├── recommender.py         # Reglas de asociación (local)
│   ├── spark_pipeline.py      # K-Means + FP-Growth (PySpark)
│   └── requirements.txt
│
├── backend/                   # API REST (Django + DRF)
│   ├── api/
│   │   ├── views.py
│   │   └── urls.py
│   ├── supermercado/settings.py
│   └── requirements.txt
│
├── frontend/                  # Dashboard (React + Vite)
│   ├── src/
│   │   ├── pages/
│   │   │   ├── ExecutiveSummary.jsx
│   │   │   ├── AnalyticalCharts.jsx
│   │   │   ├── Segments.jsx
│   │   │   └── Recommendations.jsx
│   │   └── api/client.js
│   └── package.json
│
├── output/                    # JSONs generados por el pipeline (git-ignored)
├── INFORME_TECNICO.md
└── README.md
```

---

## Requisitos

| Herramienta | Versión mínima | Notas |
|---|---|---|
| Python | 3.10+ | |
| Node.js | 18+ | |
| Java | 17–21 | Solo para el pipeline Spark |

> **Windows:** el pipeline Spark requiere Java 17 o 21. Java 22+ no es compatible con Hadoop 3.x.

---

## Instalación y ejecución

### 1. Clonar el repositorio

```bash
git clone <url-del-repositorio>
cd sistemaSupermercado
```

### 2. Instalar dependencias

```bash
# Pipeline de análisis
cd analysis && pip install -r requirements.txt && cd ..

# Backend
cd backend && pip install -r requirements.txt && cd ..

# Frontend
cd frontend && npm install && cd ..
```

### 3. Inicializar la base de datos

```bash
cd backend
python manage.py migrate
```

### 4. Generar los datos por primera vez

```bash
cd analysis
python main.py           # pipeline local (~60 s)
# o
python main.py --spark   # pipeline Spark (~380 s, requiere Java 17-21)
```

Los archivos JSON se generan en `output/`.

### 5. Levantar el backend

```bash
cd backend
python manage.py runserver 8080
# → http://localhost:8080/api/
```

### 6. Levantar el frontend

```bash
cd frontend
npm run dev
# → http://localhost:5173
```

Abre el dashboard en el navegador. El selector **Local / Spark** en la barra superior controla qué motor usa el botón "Actualizar análisis".

---

## Agregar nuevos datos

1. Coloca el nuevo archivo con formato `XXX_Tran.csv` en `DataSet/Transactions/`.
2. En el dashboard, pulsa **"Actualizar análisis"**.
3. Espera a que el pipeline termine (~60 s en modo Local).
4. Todas las visualizaciones se actualizan automáticamente.

No se requiere ningún cambio en el código.

---

## API Reference

Base URL: `http://localhost:8080/api`

| Método | Endpoint | Descripción |
|---|---|---|
| GET | `/summary` | KPIs del resumen ejecutivo |
| GET | `/charts/time-series` | Serie de tiempo diaria / semanal / mensual |
| GET | `/charts/boxplot` | Distribuciones por categoría |
| GET | `/charts/heatmap` | Matriz de correlación de variables |
| GET | `/segments` | Segmentos K-Means con centroides y scatter |
| GET | `/recommendations/category` | Resumen global + listado de categorías con reglas |
| GET | `/recommendations/category?name=LECHE LIQUIDA` | Reglas para una categoría específica |
| GET | `/recommendations/client/<id>` | Recomendaciones personalizadas para un cliente |
| POST | `/analysis/run` | Lanza el pipeline en segundo plano |
| GET | `/analysis/status` | Estado de la última ejecución |
| GET | `/analysis/history` | Historial de las últimas 20 ejecuciones |
