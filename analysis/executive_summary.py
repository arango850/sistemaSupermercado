"""
executive_summary.py
--------------------
Calcula todas las métricas del Resumen Ejecutivo y las exporta a JSON.

Métricas generadas:
  1. Total de unidades vendidas
  2. Número total de transacciones
  3. Total de clientes únicos
  4. Total de categorías únicas
  5. Número de tiendas
  6. Top 10 categorías/productos por volumen
  7. Top 10 clientes por número de transacciones
  8. Días pico de compra (top 10 días con más transacciones)
  9. Volumen por categoría (para gráfico de pastel/barras)
 10. Ventas por tienda
 11. Heatmap semanal de transacciones (día de semana × semana)
"""

import os
import json
import pandas as pd

DEFAULT_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'output')


def compute_executive_summary(
    transactions: pd.DataFrame,
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> dict:
    """
    Recibe el DataFrame de transacciones (ya enriquecido con category_name)
    y genera executive_summary.json en output_dir.

    Parámetros:
        transactions: DataFrame con columnas
            [transaction_id, date, store_id, client_id, category_id,
             category_name, quantity]
        output_dir: ruta donde se guardará el JSON

    Retorna el diccionario con todos los resultados.
    """
    os.makedirs(output_dir, exist_ok=True)
    results = {}

    # ------------------------------------------------------------------
    # 1. KPIs globales
    # ------------------------------------------------------------------
    results['total_units_sold']   = int(transactions['quantity'].sum())
    results['total_transactions'] = int(transactions['transaction_id'].nunique())
    results['total_clients']      = int(transactions['client_id'].nunique())
    results['total_categories']   = int(transactions['category_id'].nunique())
    results['total_stores']       = int(transactions['store_id'].nunique())
    results['date_range'] = {
        'start': transactions['date'].min().strftime('%Y-%m-%d'),
        'end':   transactions['date'].max().strftime('%Y-%m-%d'),
    }

    print(f"  Total unidades vendidas : {results['total_units_sold']:,}")
    print(f"  Total transacciones     : {results['total_transactions']:,}")
    print(f"  Total clientes          : {results['total_clients']:,}")
    print(f"  Total categorías        : {results['total_categories']}")
    print(f"  Tiendas                 : {results['total_stores']}")

    # ------------------------------------------------------------------
    # 2. Top 10 categorías/productos por volumen total de unidades
    # ------------------------------------------------------------------
    top_products = (
        transactions
        .groupby(['category_id', 'category_name'], as_index=False)['quantity']
        .sum()
        .rename(columns={'quantity': 'total_units'})
        .sort_values('total_units', ascending=False)
        .head(10)
        .reset_index(drop=True)
    )
    top_products['rank'] = top_products.index + 1
    results['top_10_products'] = top_products.to_dict(orient='records')

    # ------------------------------------------------------------------
    # 3. Top 10 clientes por número de transacciones
    # ------------------------------------------------------------------
    top_clients = (
        transactions
        .groupby('client_id')['transaction_id']
        .nunique()
        .reset_index()
        .rename(columns={'transaction_id': 'num_transactions'})
        .sort_values('num_transactions', ascending=False)
        .head(10)
        .reset_index(drop=True)
    )
    top_clients['rank'] = top_clients.index + 1
    # También añadimos total de unidades por cliente
    client_units = (
        transactions
        .groupby('client_id')['quantity']
        .sum()
        .reset_index()
        .rename(columns={'quantity': 'total_units'})
    )
    top_clients = top_clients.merge(client_units, on='client_id', how='left')
    results['top_10_clients'] = top_clients.to_dict(orient='records')

    # ------------------------------------------------------------------
    # 4. Días pico de compra
    # ------------------------------------------------------------------
    daily_txns = (
        transactions
        .groupby('date')['transaction_id']
        .nunique()
        .reset_index()
        .rename(columns={'transaction_id': 'num_transactions'})
        .sort_values('num_transactions', ascending=False)
    )
    daily_units = (
        transactions
        .groupby('date')['quantity']
        .sum()
        .reset_index()
        .rename(columns={'quantity': 'total_units'})
    )
    daily_txns = daily_txns.merge(daily_units, on='date', how='left')
    daily_txns['date'] = daily_txns['date'].dt.strftime('%Y-%m-%d')
    daily_txns['day_of_week'] = pd.to_datetime(daily_txns['date']).dt.day_name()
    results['peak_days'] = daily_txns.head(10).reset_index(drop=True).to_dict(
        orient='records'
    )

    # ------------------------------------------------------------------
    # 5. Todas las categorías por volumen (para gráfico de pastel/barras)
    # ------------------------------------------------------------------
    category_volume = (
        transactions
        .groupby(['category_id', 'category_name'], as_index=False)['quantity']
        .sum()
        .rename(columns={'quantity': 'total_units'})
        .sort_values('total_units', ascending=False)
        .reset_index(drop=True)
    )
    # Porcentaje relativo
    total = category_volume['total_units'].sum()
    category_volume['percentage'] = (
        (category_volume['total_units'] / total * 100).round(2)
    )
    results['categories_by_volume'] = category_volume.to_dict(orient='records')

    # ------------------------------------------------------------------
    # 6. Ventas por tienda
    # ------------------------------------------------------------------
    store_sales = (
        transactions
        .groupby('store_id')
        .agg(
            total_units     =('quantity',        'sum'),
            num_transactions=('transaction_id',  'nunique'),
            num_clients     =('client_id',       'nunique'),
        )
        .reset_index()
        .sort_values('total_units', ascending=False)
    )
    results['sales_by_store'] = store_sales.to_dict(orient='records')

    # ------------------------------------------------------------------
    # 7. Heatmap diario: transacciones por día de la semana × mes
    #    (para identificar patrones de estacionalidad semanal)
    # ------------------------------------------------------------------
    df_heat = transactions[['transaction_id', 'date']].drop_duplicates(
        subset='transaction_id'
    ).copy()
    df_heat['day_of_week'] = df_heat['date'].dt.dayofweek   # 0=Lunes, 6=Domingo
    df_heat['month']       = df_heat['date'].dt.to_period('M').astype(str)

    heatmap_pivot = (
        df_heat
        .groupby(['month', 'day_of_week'])['transaction_id']
        .count()
        .unstack(fill_value=0)
        .reset_index()
    )
    # Convertir a lista de registros para serialización JSON
    heatmap_records = []
    day_names = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    for col in heatmap_pivot.columns[1:]:
        day_label = day_names[int(col)] if int(col) < len(day_names) else str(col)
        for _, row in heatmap_pivot.iterrows():
            heatmap_records.append({
                'month':       row['month'],
                'day_of_week': int(col),
                'day_name':    day_label,
                'count':       int(row[col]),
            })
    results['weekly_heatmap'] = heatmap_records

    # ------------------------------------------------------------------
    # Guardar JSON
    # ------------------------------------------------------------------
    output_path = os.path.join(output_dir, 'executive_summary.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)

    print(f"  Guardado: {output_path}")
    return results
