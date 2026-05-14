"""
analytical_charts.py
--------------------
Genera los datos para las tres visualizaciones analíticas requeridas:

  1. Serie de tiempo  — ventas diarias y semanales
  2. Boxplot          — distribución de tamaños de cesta por categoría y por cliente
  3. Heatmap          — correlación entre variables numéricas a nivel cliente

Cada función exporta un archivo JSON listo para ser consumido por el frontend
React o por el backend Spring Boot.
"""

import os
import json
import numpy as np
import pandas as pd

DEFAULT_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'output')


# ---------------------------------------------------------------------------
# Helper: serialización de tipos numpy/pandas
# ---------------------------------------------------------------------------

def _json_safe(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return obj.strftime('%Y-%m-%d')
    return str(obj)


# ---------------------------------------------------------------------------
# 1. Serie de tiempo
# ---------------------------------------------------------------------------

def compute_time_series(
    transactions: pd.DataFrame,
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> dict:
    """
    Ventas por día y por semana.

    Genera time_series.json con:
      - daily:   [{date, total_units, num_transactions}, ...]
      - weekly:  [{week_start, total_units, num_transactions}, ...]
      - monthly: [{month, total_units, num_transactions}, ...]
      - by_store_daily: [{date, store_id, total_units, num_transactions}, ...]
    """
    os.makedirs(output_dir, exist_ok=True)

    # Base: una fila por transacción (sin duplicar por categoría)
    txn_base = (
        transactions[['transaction_id', 'date', 'store_id']]
        .drop_duplicates(subset='transaction_id')
    )
    unit_daily = (
        transactions
        .groupby('date')['quantity']
        .sum()
        .reset_index()
        .rename(columns={'quantity': 'total_units'})
    )
    txn_daily = (
        txn_base
        .groupby('date')['transaction_id']
        .count()
        .reset_index()
        .rename(columns={'transaction_id': 'num_transactions'})
    )
    daily = txn_daily.merge(unit_daily, on='date', how='left')
    daily['date'] = daily['date'].dt.strftime('%Y-%m-%d')
    daily = daily.sort_values('date')

    # Semanal
    transactions_w = transactions.copy()
    transactions_w['week_start'] = (
        transactions_w['date'] - pd.to_timedelta(
            transactions_w['date'].dt.dayofweek, unit='D'
        )
    )
    txn_weekly = (
        transactions_w[['transaction_id', 'week_start']]
        .drop_duplicates(subset='transaction_id')
        .groupby('week_start')['transaction_id']
        .count()
        .reset_index()
        .rename(columns={'transaction_id': 'num_transactions'})
    )
    unit_weekly = (
        transactions_w
        .groupby('week_start')['quantity']
        .sum()
        .reset_index()
        .rename(columns={'quantity': 'total_units'})
    )
    weekly = txn_weekly.merge(unit_weekly, on='week_start', how='left')
    weekly['week_start'] = weekly['week_start'].dt.strftime('%Y-%m-%d')
    weekly = weekly.sort_values('week_start')

    # Mensual
    transactions_m = transactions.copy()
    transactions_m['month'] = transactions_m['date'].dt.to_period('M').astype(str)
    txn_monthly = (
        transactions_m[['transaction_id', 'month']]
        .drop_duplicates(subset='transaction_id')
        .groupby('month')['transaction_id']
        .count()
        .reset_index()
        .rename(columns={'transaction_id': 'num_transactions'})
    )
    unit_monthly = (
        transactions_m
        .groupby('month')['quantity']
        .sum()
        .reset_index()
        .rename(columns={'quantity': 'total_units'})
    )
    monthly = txn_monthly.merge(unit_monthly, on='month', how='left')
    monthly = monthly.sort_values('month')

    # Por tienda (diario, para comparar tendencias entre puntos de venta)
    unit_store = (
        transactions
        .groupby(['date', 'store_id'])['quantity']
        .sum()
        .reset_index()
        .rename(columns={'quantity': 'total_units'})
    )
    txn_store = (
        txn_base
        .groupby(['date', 'store_id'])['transaction_id']
        .count()
        .reset_index()
        .rename(columns={'transaction_id': 'num_transactions'})
    )
    by_store = txn_store.merge(unit_store, on=['date', 'store_id'], how='left')
    by_store['date'] = by_store['date'].dt.strftime('%Y-%m-%d')
    by_store = by_store.sort_values(['store_id', 'date'])

    result = {
        'daily':          daily.to_dict(orient='records'),
        'weekly':         weekly.to_dict(orient='records'),
        'monthly':        monthly.to_dict(orient='records'),
        'by_store_daily': by_store.to_dict(orient='records'),
    }

    out = os.path.join(output_dir, 'time_series.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=_json_safe)

    print(f"  Serie de tiempo guardada: {out}")
    print(f"    Días: {len(daily)}  |  Semanas: {len(weekly)}  |  Meses: {len(monthly)}")
    return result


# ---------------------------------------------------------------------------
# 2. Boxplot
# ---------------------------------------------------------------------------

def compute_boxplot_data(
    transactions: pd.DataFrame,
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> dict:
    """
    Distribución de totales por cliente y por categoría.

    Genera boxplot_data.json con:
      - basket_size_distribution:  estadísticas del tamaño de cesta por transacción
      - client_total_distribution: distribución del total acumulado por cliente
      - category_basket_stats:     por cada categoría, stats del nº de transacciones
                                   que la incluyeron (frecuencia de aparición)

    Las estadísticas incluyen: min, q1, median, q3, max, mean, std, count.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Tamaño de cesta: unidades totales por transacción
    basket = (
        transactions
        .groupby('transaction_id')['quantity']
        .sum()
        .reset_index()
        .rename(columns={'quantity': 'basket_size'})
    )

    def describe_series(s: pd.Series, label: str) -> dict:
        return {
            'label': label,
            'min':    float(s.min()),
            'q1':     float(s.quantile(0.25)),
            'median': float(s.median()),
            'q3':     float(s.quantile(0.75)),
            'max':    float(s.max()),
            'mean':   float(s.mean()),
            'std':    float(s.std()),
            'count':  int(s.count()),
        }

    basket_stats = describe_series(basket['basket_size'], 'Tamaño de cesta')

    # Distribución del total de unidades compradas por cliente (a lo largo del tiempo)
    client_totals = (
        transactions
        .groupby('client_id')['quantity']
        .sum()
        .reset_index()
        .rename(columns={'quantity': 'total_units'})
    )
    client_stats = describe_series(client_totals['total_units'], 'Total unidades por cliente')

    # Outliers de clientes (por encima de Q3 + 1.5 * IQR)
    q1, q3 = client_totals['total_units'].quantile([0.25, 0.75])
    iqr = q3 - q1
    outlier_threshold = q3 + 1.5 * iqr
    outlier_clients = (
        client_totals[client_totals['total_units'] > outlier_threshold]
        .sort_values('total_units', ascending=False)
        .head(20)
        .to_dict(orient='records')
    )

    # Por categoría: distribución del número de unidades por transacción
    # (vectorizado con groupby + describe)
    cat_freq = (
        transactions
        .groupby(['category_name', 'transaction_id'])['quantity']
        .sum()
        .reset_index()
    )
    cat_desc = (
        cat_freq
        .groupby('category_name')['quantity']
        .describe(percentiles=[0.25, 0.5, 0.75])
        .reset_index()
        .rename(columns={
            'count': 'count',
            'mean':  'mean',
            'std':   'std',
            'min':   'min',
            '25%':   'q1',
            '50%':   'median',
            '75%':   'q3',
            'max':   'max',
        })
        .sort_values('count', ascending=False)
    )
    cat_stats_list = cat_desc.round(4).to_dict(orient='records')

    # Distribución completa del tamaño de cesta (histograma de frecuencias)
    hist_values = basket['basket_size'].value_counts().sort_index()
    basket_histogram = [
        {'basket_size': int(k), 'frequency': int(v)}
        for k, v in hist_values.items()
        if k <= 50   # limitar para visualización
    ]

    result = {
        'basket_size_stats':         basket_stats,
        'client_total_stats':        client_stats,
        'outlier_clients':           outlier_clients,
        'category_basket_stats':     cat_stats_list,
        'basket_size_histogram':     basket_histogram,
    }

    out = os.path.join(output_dir, 'boxplot_data.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=_json_safe)

    print(f"  Boxplot data guardada: {out}")
    print(f"    Estadísticas por {len(cat_stats_list)} categorías")
    return result


# ---------------------------------------------------------------------------
# 3. Heatmap de correlación
# ---------------------------------------------------------------------------

def compute_heatmap_data(
    transactions: pd.DataFrame,
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> dict:
    """
    Correlación entre variables numéricas a nivel de cliente.

    Variables calculadas por cliente:
      - purchase_frequency    : número de transacciones distintas
      - total_units           : total de unidades compradas
      - avg_basket_size       : promedio de unidades por transacción
      - category_diversity    : número de categorías distintas compradas
      - avg_categories_per_txn: promedio de categorías distintas por transacción
      - num_stores_visited    : número de tiendas distintas visitadas
      - active_days           : número de días distintos con compras

    Genera heatmap_data.json con:
      - correlation_matrix: [[float, ...], ...]
      - labels:             [str, ...]
      - client_features:    [{client_id, feature1, ...}, ...]  (muestra de 500)
    """
    os.makedirs(output_dir, exist_ok=True)

    # Tamaño de cesta y diversidad por transacción
    txn_stats = (
        transactions
        .groupby(['transaction_id', 'client_id', 'store_id', 'date'])
        .agg(
            basket_size  =('quantity',     'sum'),
            num_categories=('category_id', 'nunique'),
        )
        .reset_index()
    )

    # Diversidad total de categorías por cliente (calculada directamente)
    cat_diversity = (
        transactions
        .groupby('client_id')['category_id']
        .nunique()
        .reset_index()
        .rename(columns={'category_id': 'category_diversity'})
    )

    # Agregar a nivel de cliente
    client_features = (
        txn_stats
        .groupby('client_id')
        .agg(
            purchase_frequency    =('transaction_id',  'count'),
            total_units           =('basket_size',      'sum'),
            avg_basket_size       =('basket_size',      'mean'),
            avg_categories_per_txn=('num_categories',  'mean'),
            num_stores_visited    =('store_id',         'nunique'),
            active_days           =('date',             'nunique'),
        )
        .reset_index()
        .merge(cat_diversity, on='client_id', how='left')
    )

    feature_cols = [
        'purchase_frequency',
        'total_units',
        'avg_basket_size',
        'avg_categories_per_txn',
        'category_diversity',
        'num_stores_visited',
        'active_days',
    ]

    labels_es = [
        'Frecuencia de compra',
        'Total unidades',
        'Promedio cesta',
        'Categorías por transacción',
        'Diversidad de categorías',
        'Tiendas visitadas',
        'Días activos',
    ]

    corr_matrix = (
        client_features[feature_cols]
        .corr()
        .round(4)
    )

    # Muestra de clientes para scatter plots en el frontend
    sample = client_features.sample(
        n=min(500, len(client_features)), random_state=42
    )

    result = {
        'labels':           labels_es,
        'feature_keys':     feature_cols,
        'correlation_matrix': corr_matrix.values.tolist(),
        'client_features_sample': sample[['client_id'] + feature_cols].to_dict(
            orient='records'
        ),
        'client_features_count': len(client_features),
    }

    out = os.path.join(output_dir, 'heatmap_data.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=_json_safe)

    print(f"  Heatmap data guardada: {out}")
    print(f"    Clientes analizados: {len(client_features):,}")
    print(f"    Variables: {feature_cols}")
    return result
