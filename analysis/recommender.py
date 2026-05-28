"""
recommender.py
--------------
Recomendador de categorías basado en reglas de asociación (co-ocurrencia).

Algoritmo:
    1. Construye una matriz binaria dispersa (transacciones × categorías).
    2. Calcula la matriz de co-ocurrencia C = X^T · X  (449×449).
    3. Deriva soporte, confianza y lift para cada par ordenado (A → B).
    4. Filtra por umbrales mínimos y construye un índice invertido por categoría.

Parámetros clave:
    MIN_SUPPORT    = 0.02  (2 % de las transacciones)
    MIN_CONFIDENCE = 0.25
    MIN_LIFT       = 1.2

Salida: output/recommendations.json
"""

import os
import json
import time

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix


# ---------------------------------------------------------------------------
# Parámetros de filtrado
# ---------------------------------------------------------------------------
MIN_SUPPORT    = 0.02   # fracción del total de transacciones
MIN_CONFIDENCE = 0.25
MIN_LIFT       = 1.2
TOP_PER_CATEGORY = 15   # máximo de recomendaciones por categoría en el índice
MAX_RULES_JSON   = 1000 # máximo de reglas en la lista completa del JSON


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _build_sparse_matrix(transactions: pd.DataFrame):
    """
    Construye la matriz binaria dispersa X de forma (n_txns × n_cats).

    Retorna
    -------
    X          : csr_matrix  boolean
    txn_ids    : np.ndarray  — IDs únicos de transacción (fila → ID)
    cat_ids    : np.ndarray  — IDs únicos de categoría  (col  → ID)
    cat_names  : dict         — category_id → category_name
    """
    # Índices únicos (necesarios para la numeración de filas/columnas)
    unique_txns = transactions['transaction_id'].unique()
    unique_cats = transactions['category_id'].unique()

    txn_index = {t: i for i, t in enumerate(unique_txns)}
    cat_index = {c: i for i, c in enumerate(unique_cats)}

    rows = transactions['transaction_id'].map(txn_index).values
    cols = transactions['category_id'].map(cat_index).values
    data = np.ones(len(rows), dtype=np.float32)

    X = csr_matrix(
        (data, (rows, cols)),
        shape=(len(unique_txns), len(unique_cats)),
        dtype=np.float32,
    )

    # Binarizar (una categoría puede aparecer varias veces en la misma transacción)
    X.data = np.ones_like(X.data)

    # Mapa categoría_id → nombre
    cat_names = (
        transactions.drop_duplicates('category_id')
        .set_index('category_id')['category_name']
        .to_dict()
        if 'category_name' in transactions.columns
        else {c: str(c) for c in unique_cats}
    )

    return X, unique_txns, unique_cats, cat_index, cat_names


def _build_rules(co_occ: np.ndarray, item_counts: np.ndarray,
                 n_txns: int, unique_cats: np.ndarray,
                 cat_names: dict) -> list[dict]:
    """
    Genera reglas A → B a partir de la matriz de co-ocurrencia.

    Parámetros
    ----------
    co_occ      : (n_cats × n_cats) array de co-ocurrencias  (i,j) = count(A∩B)
    item_counts : (n_cats,) array — count(A)  [diagonal de co_occ]
    n_txns      : número total de transacciones
    """
    rules = []
    n_cats = len(unique_cats)

    # Soportes individuales vectorizados
    supp_a = item_counts / n_txns    # shape (n_cats,)
    supp_b = item_counts / n_txns    # mismos valores

    # Filtrar categorías con soporte mínimo
    freq_mask = supp_a >= MIN_SUPPORT
    freq_indices = np.where(freq_mask)[0]

    # Sub-matriz de categorías frecuentes
    co_sub = co_occ[np.ix_(freq_indices, freq_indices)]
    counts_sub = item_counts[freq_indices]
    cats_sub = unique_cats[freq_indices]

    n_freq = len(freq_indices)
    supp_sub = counts_sub / n_txns

    for i in range(n_freq):
        for j in range(n_freq):
            if i == j:
                continue
            pair_count = co_sub[i, j]
            if pair_count == 0:
                continue

            supp_ij  = pair_count / n_txns
            conf_ij  = pair_count / counts_sub[i]     # P(B|A)
            lift_ij  = supp_ij / (supp_sub[i] * supp_sub[j])

            if supp_ij < MIN_SUPPORT or conf_ij < MIN_CONFIDENCE or lift_ij < MIN_LIFT:
                continue

            ant_id = int(cats_sub[i])
            con_id = int(cats_sub[j])

            rules.append({
                'antecedent_id':  ant_id,
                'antecedent':     cat_names.get(ant_id, str(ant_id)),
                'consequent_id':  con_id,
                'consequent':     cat_names.get(con_id, str(con_id)),
                'support':        round(float(supp_ij),  4),
                'confidence':     round(float(conf_ij),  4),
                'lift':           round(float(lift_ij),  4),
            })

    # Ordenar por lift desc, luego confianza desc
    rules.sort(key=lambda r: (-r['lift'], -r['confidence']))
    return rules


def _build_category_index(rules: list[dict]) -> dict:
    """
    Construye un índice invertido: category_name → lista ordenada de sugerencias.
    """
    index: dict[str, list] = {}
    for rule in rules:
        ant = rule['antecedent']
        if ant not in index:
            index[ant] = []
        if len(index[ant]) < TOP_PER_CATEGORY:
            index[ant].append({
                'recommendation': rule['consequent'],
                'confidence':     rule['confidence'],
                'lift':           rule['lift'],
                'support':        rule['support'],
            })
    return index


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def compute_recommendations(
    transactions: pd.DataFrame,
    output_dir: str,
) -> dict:
    """
    Calcula reglas de asociación basadas en co-ocurrencia de categorías y
    guarda output/recommendations.json.

    Parámetros
    ----------
    transactions : pd.DataFrame
        DataFrame explosionado (una fila por transacción × categoría).
    output_dir : str
        Directorio de salida.

    Retorna
    -------
    dict con la misma estructura que recommendations.json.
    """
    os.makedirs(output_dir, exist_ok=True)

    n_total_txns = int(transactions['transaction_id'].nunique())
    n_categories = int(transactions['category_id'].nunique())
    print(f"    {n_total_txns:,} transacciones  ·  {n_categories} categorías")

    # ------------------------------------------------------------------
    # 1. Construcción de la matriz dispersa
    # ------------------------------------------------------------------
    print("    Construyendo matriz dispersa transacciones × categorías...")
    t0 = time.time()
    X, unique_txns, unique_cats, cat_index, cat_names = _build_sparse_matrix(transactions)
    print(f"    Matriz {X.shape[0]:,} × {X.shape[1]}  —  {X.nnz:,} entradas no nulas ({time.time()-t0:.1f}s)")

    # ------------------------------------------------------------------
    # 2. Matriz de co-ocurrencia  C = X^T · X
    # ------------------------------------------------------------------
    print("    Calculando co-ocurrencias (X^T · X)...")
    t0 = time.time()
    co_occ_sparse = X.T @ X
    co_occ = co_occ_sparse.toarray()          # 449×449 — cabe perfectamente en RAM
    item_counts = np.diag(co_occ).astype(float)   # count(A) = C[i,i]
    print(f"    Co-ocurrencias calculadas en {time.time()-t0:.1f}s")

    # ------------------------------------------------------------------
    # 3. Generar reglas
    # ------------------------------------------------------------------
    print("    Generando reglas de asociación...")
    t0 = time.time()
    rules = _build_rules(co_occ, item_counts, len(unique_txns), unique_cats, cat_names)
    print(f"    {len(rules):,} reglas generadas en {time.time()-t0:.1f}s")
    print(f"    (min_support={MIN_SUPPORT}, min_confidence={MIN_CONFIDENCE}, min_lift={MIN_LIFT})")

    # ------------------------------------------------------------------
    # 4. Índice por categoría
    # ------------------------------------------------------------------
    category_index = _build_category_index(rules)
    n_indexed_cats = len(category_index)
    print(f"    {n_indexed_cats} categorías con recomendaciones en el índice")

    # ------------------------------------------------------------------
    # 5. Estadísticas de soporte individual de categorías
    # ------------------------------------------------------------------
    cat_support = []
    for i, cat_id in enumerate(unique_cats):
        cnt = float(item_counts[i])
        supp = cnt / len(unique_txns)
        if supp >= MIN_SUPPORT:
            cat_support.append({
                'category_id':   int(cat_id),
                'category_name': cat_names.get(int(cat_id), str(cat_id)),
                'count':         int(cnt),
                'support':       round(supp, 4),
            })
    cat_support.sort(key=lambda c: -c['support'])

    # ------------------------------------------------------------------
    # 6. Guardar JSON
    # ------------------------------------------------------------------
    result = {
        'generated_at':    pd.Timestamp.now().isoformat(),
        'n_transactions':  n_total_txns,
        'n_categories':    n_categories,
        'min_support':     MIN_SUPPORT,
        'min_confidence':  MIN_CONFIDENCE,
        'min_lift':        MIN_LIFT,
        'total_rules':     len(rules),
        'rules':           rules[:MAX_RULES_JSON],
        'category_support': cat_support,
        'category_index':  category_index,
    }

    out_path = os.path.join(output_dir, 'recommendations.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"    ✓ recommendations.json guardado ({os.path.getsize(out_path) / 1024:.0f} KB)")
    return result
