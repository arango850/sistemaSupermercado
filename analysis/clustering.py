"""
clustering.py
-------------
Segmentación de clientes mediante K-Means (scikit-learn).

Features por cliente:
    purchase_frequency   — número de transacciones únicas
    total_units          — unidades totales compradas
    avg_basket_size      — promedio de ítems por transacción
    category_diversity   — número de categorías únicas compradas
    active_days          — días únicos con compras

Salida: output/clustering.json
"""

import os
import json
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score


FEATURE_KEYS = [
    'purchase_frequency',
    'total_units',
    'avg_basket_size',
    'category_diversity',
    'active_days',
]

# Rango de k a evaluar para el método del codo
K_VALUES = [3, 4, 5, 6]
DEFAULT_K = 4

# Máximo de clientes en la muestra de scatter del frontend
SAMPLE_SIZE = 2000


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _build_client_features(transactions: pd.DataFrame) -> pd.DataFrame:
    """
    Construye un DataFrame con una fila por cliente y las features definidas
    en FEATURE_KEYS.
    """
    grp = transactions.groupby('client_id')

    features = pd.DataFrame({
        'purchase_frequency': grp['transaction_id'].nunique(),
        'total_units':        grp['category_id'].count(),
        'active_days':        grp['date'].nunique(),
        'category_diversity': grp['category_id'].nunique(),
    })

    # avg_basket_size: media de ítems por transacción para cada cliente
    basket_sizes = (
        transactions
        .groupby(['client_id', 'transaction_id'])['category_id']
        .count()
    )
    features['avg_basket_size'] = basket_sizes.groupby('client_id').mean()

    return features[FEATURE_KEYS].fillna(0)


def _label_segment(centroid: dict) -> str:
    """
    Asigna una etiqueta descriptiva a un segmento según sus valores centroidales.
    La lógica se basa en percentiles aproximados del dataset real.
    """
    freq  = centroid['purchase_frequency']
    units = centroid['total_units']
    div   = centroid['category_diversity']

    if freq <= 4 and units <= 25:
        return "Compradores Esporádicos"
    elif freq <= 10 and units <= 80:
        return "Compradores Ocasionales"
    elif div >= 40 and units >= 200:
        return "Compradores Diversificados"
    elif units >= 300:
        return "Compradores VIP"
    else:
        return "Compradores Regulares"


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def compute_clustering(
    transactions: pd.DataFrame,
    output_dir: str,
) -> dict:
    """
    Ejecuta la segmentación K-Means y guarda output/clustering.json.

    Parámetros
    ----------
    transactions : pd.DataFrame
        DataFrame explosionado (una fila por transacción × categoría).
    output_dir : str
        Directorio donde se escribe clustering.json.

    Retorna
    -------
    dict con la misma estructura que clustering.json.
    """
    os.makedirs(output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Features de clientes
    # ------------------------------------------------------------------
    print("    Construyendo features de clientes...")
    features = _build_client_features(transactions)
    n_clients = len(features)
    print(f"    {n_clients:,} clientes con features calculadas")

    X = features[FEATURE_KEYS].values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # ------------------------------------------------------------------
    # 2. Método del codo: evaluar k = 3, 4, 5, 6
    # ------------------------------------------------------------------
    print("    Calculando método del codo (k=3..6)...")
    elbow_data = []
    best_k = DEFAULT_K
    best_sil = -1.0

    sil_sample = min(15_000, n_clients)
    rng = np.random.default_rng(42)

    for k in K_VALUES:
        km = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=300)
        labels_k = km.fit_predict(X_scaled)
        inertia = float(km.inertia_)
        sil = float(
            silhouette_score(X_scaled, labels_k, sample_size=sil_sample, random_state=42)
        )
        elbow_data.append({
            'k': k,
            'inertia': round(inertia, 2),
            'silhouette': round(sil, 4),
        })
        print(f"      k={k}: inertia={inertia:,.0f}  silhouette={sil:.4f}")
        if sil > best_sil:
            best_sil, best_k = sil, k

    # ------------------------------------------------------------------
    # 3. Clustering final con el mejor k
    # ------------------------------------------------------------------
    print(f"    Ajustando KMeans final (k={best_k}, silhouette={best_sil:.4f})...")
    km_final = KMeans(n_clusters=best_k, random_state=42, n_init=10, max_iter=300)
    final_labels = km_final.fit_predict(X_scaled)
    features = features.copy()
    features['segment_id'] = final_labels

    # Centroides en escala original
    centroids_original = scaler.inverse_transform(km_final.cluster_centers_)

    # ------------------------------------------------------------------
    # 4. Perfiles de segmento
    # ------------------------------------------------------------------
    segments = []
    for seg_id in range(best_k):
        mask = final_labels == seg_id
        centroid_dict = {
            key: round(float(val), 2)
            for key, val in zip(FEATURE_KEYS, centroids_original[seg_id])
        }
        # Stats reales del segmento (no solo el centroide)
        seg_features = features.loc[mask, FEATURE_KEYS]
        stats = {}
        for key in FEATURE_KEYS:
            col = seg_features[key]
            stats[key] = {
                'mean':   round(float(col.mean()), 2),
                'median': round(float(col.median()), 2),
                'std':    round(float(col.std()), 2),
                'min':    round(float(col.min()), 2),
                'max':    round(float(col.max()), 2),
            }

        segments.append({
            'segment_id': int(seg_id),
            'label':      _label_segment(centroid_dict),
            'size':       int(mask.sum()),
            'percentage': round(float(mask.sum()) / n_clients * 100, 1),
            'centroid':   centroid_dict,
            'stats':      stats,
        })

    # Ordenar segmentos por tamaño descendente
    segments.sort(key=lambda s: s['size'], reverse=True)

    # Reasignar segment_id secuencial tras el ordenado (para colores en frontend)
    for new_id, seg in enumerate(segments):
        old_id = seg['segment_id']
        seg['segment_id'] = new_id
        # Actualizar labels en features
        features.loc[features['segment_id'] == old_id, 'segment_id'] = -(new_id + 1)
    features['segment_id'] = features['segment_id'].abs() - 1

    # ------------------------------------------------------------------
    # 5. Muestra para scatter en frontend
    # ------------------------------------------------------------------
    sample_idx = rng.choice(n_clients, size=min(SAMPLE_SIZE, n_clients), replace=False)
    sample_rows = features.iloc[sample_idx]
    client_sample = [
        {
            'client_id':  int(sample_rows.index[i]),
            'segment_id': int(sample_rows.iloc[i]['segment_id']),
            **{key: round(float(sample_rows.iloc[i][key]), 2) for key in FEATURE_KEYS},
        }
        for i in range(len(sample_rows))
    ]

    # ------------------------------------------------------------------
    # 6. Guardar JSON
    # ------------------------------------------------------------------
    result = {
        'generated_at':   pd.Timestamp.now().isoformat(),
        'k':              best_k,
        'silhouette_score': round(best_sil, 4),
        'total_clients':  n_clients,
        'feature_keys':   FEATURE_KEYS,
        'elbow_data':     elbow_data,
        'segments':       segments,
        'client_sample':  client_sample,
    }

    out_path = os.path.join(output_dir, 'clustering.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"    ✓ clustering.json guardado ({os.path.getsize(out_path) / 1024:.0f} KB)")

    # ------------------------------------------------------------------
    # 7. Guardar client_segments.json — mapeo cliente → segmento y top cats
    # ------------------------------------------------------------------
    seg_labels = {str(s['segment_id']): s['label'] for s in segments}

    # Top 10 categorías más compradas por segmento (por número de clientes)
    seg_top_cats: dict[str, list] = {}
    if 'category_name' in transactions.columns:
        seg_col = features[['segment_id']].rename_axis('client_id').reset_index()
        merged = transactions[['client_id', 'category_name']].merge(
            seg_col, on='client_id', how='left'
        )
        for sid in range(best_k):
            top = (
                merged[merged['segment_id'] == sid]
                .groupby('category_name')['client_id']
                .nunique()
                .sort_values(ascending=False)
                .head(10)
                .index.tolist()
            )
            seg_top_cats[str(sid)] = top
    else:
        seg_top_cats = {str(i): [] for i in range(best_k)}

    cs_result = {
        'generated_at':           pd.Timestamp.now().isoformat(),
        'n_clients':               n_clients,
        'client_segments':         {str(k): int(v) for k, v in features['segment_id'].items()},
        'segment_top_categories':  seg_top_cats,
        'segment_labels':          seg_labels,
    }
    cs_path = os.path.join(output_dir, 'client_segments.json')
    with open(cs_path, 'w', encoding='utf-8') as f:
        json.dump(cs_result, f, ensure_ascii=False)
    print(f"    ✓ client_segments.json guardado ({os.path.getsize(cs_path) / 1024:.0f} KB)")

    return result
