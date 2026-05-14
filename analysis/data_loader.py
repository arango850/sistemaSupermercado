"""
data_loader.py
--------------
Carga y normaliza todos los archivos CSV del DataSet de supermercado.

Formato de transacciones:
    fecha|tienda_id|cliente_id|códigos_categoría_separados_por_espacio

Cada código en la última columna representa 1 unidad comprada de esa categoría.
"""

import os
import glob
import pandas as pd


# Rutas por defecto relativas al directorio del proyecto
_BASE_DIR = os.path.join(os.path.dirname(__file__), '..')
DEFAULT_DATA_DIR   = os.path.join(_BASE_DIR, 'DataSet')
DEFAULT_OUTPUT_DIR = os.path.join(_BASE_DIR, 'output')


def load_categories(data_dir: str = DEFAULT_DATA_DIR) -> pd.DataFrame:
    """
    Carga Categories.csv.
    Retorna DataFrame con columnas: category_id (int), category_name (str).
    """
    path = os.path.join(data_dir, 'Products', 'Categories.csv')
    df = pd.read_csv(
        path,
        sep='|',
        header=None,
        names=['category_id', 'category_name'],
        dtype={'category_id': int, 'category_name': str},
    )
    return df


def load_product_categories(data_dir: str = DEFAULT_DATA_DIR) -> pd.DataFrame:
    """
    Carga ProductCategory.csv.
    Retorna DataFrame con columnas: product_code (int), category_id (int).
    """
    path = os.path.join(data_dir, 'Products', 'ProductCategory.csv')
    df = pd.read_csv(
        path,
        sep='|',
        header=0,
        dtype=str,
    )
    df.columns = ['product_code', 'category_id']
    df['product_code'] = pd.to_numeric(df['product_code'], errors='coerce')
    df['category_id']  = pd.to_numeric(df['category_id'],  errors='coerce')
    df = df.dropna().astype(int)
    return df


def load_transactions(data_dir: str = DEFAULT_DATA_DIR) -> pd.DataFrame:
    """
    Carga todos los archivos *_Tran.csv de DataSet/Transactions/.

    Retorna un DataFrame "explosionado" con una fila por cada
    (transacción × categoría) con columnas:
        transaction_id  (int)  — índice secuencial de la fila original
        date            (date) — fecha de la compra
        store_id        (int)  — código de tienda (102, 103, 107, 110)
        client_id       (int)  — identificador de cliente
        category_id     (int)  — código de categoría comprada
        quantity        (int)  — siempre 1 (cada aparición = 1 unidad)
    """
    txn_dir = os.path.join(data_dir, 'Transactions')
    files = sorted(glob.glob(os.path.join(txn_dir, '*_Tran.csv')))

    if not files:
        raise FileNotFoundError(
            f"No se encontraron archivos *_Tran.csv en {txn_dir}"
        )

    print(f"  Archivos de transacciones encontrados: {len(files)}")
    for f in files:
        print(f"    {os.path.basename(f)}")

    dfs = []
    for fpath in files:
        df = pd.read_csv(
            fpath,
            sep='|',
            header=None,
            names=['date', 'store_id', 'client_id', 'items_str'],
            dtype={'store_id': int, 'client_id': int, 'items_str': str},
        )
        dfs.append(df)
        print(f"    {os.path.basename(fpath)}: {len(df):,} transacciones")

    raw = pd.concat(dfs, ignore_index=True)

    # El índice del concat es el transaction_id único
    raw['transaction_id'] = raw.index
    raw['date'] = pd.to_datetime(raw['date'], format='%Y-%m-%d')

    # Convertir la columna items_str en lista de enteros y explotar
    raw['category_id'] = raw['items_str'].str.split()
    raw = raw.drop(columns=['items_str'])

    exploded = raw.explode('category_id').copy()
    exploded['category_id'] = pd.to_numeric(
        exploded['category_id'], errors='coerce'
    ).dropna().astype(int)
    exploded = exploded.dropna(subset=['category_id'])
    exploded['category_id'] = exploded['category_id'].astype(int)
    exploded['quantity'] = 1

    exploded = exploded.reset_index(drop=True)
    return exploded


def load_all(data_dir: str = DEFAULT_DATA_DIR):
    """
    Carga todas las fuentes de datos y retorna el DataFrame de transacciones
    enriquecido con nombres de categoría.

    Retorna:
        transactions (pd.DataFrame): datos completos de transacciones con
            category_name incluido.
        categories   (pd.DataFrame): tabla de categorías.
    """
    print("Cargando categorías...")
    categories = load_categories(data_dir)
    print(f"  {len(categories)} categorías cargadas")

    print("Cargando transacciones...")
    transactions = load_transactions(data_dir)
    print(f"  {len(transactions):,} registros (transacción × categoría)")

    # Enriquecer con nombre de categoría; las que no tengan nombre → "Categoría N"
    transactions = transactions.merge(categories, on='category_id', how='left')
    mask_unknown = transactions['category_name'].isna()
    transactions.loc[mask_unknown, 'category_name'] = (
        'Categoría ' + transactions.loc[mask_unknown, 'category_id'].astype(str)
    )

    unique_txns   = transactions['transaction_id'].nunique()
    unique_cats   = transactions['category_id'].nunique()
    unique_clients = transactions['client_id'].nunique()
    unique_stores  = transactions['store_id'].nunique()

    print(f"\n  Resumen del dataset:")
    print(f"    Transacciones únicas : {unique_txns:,}")
    print(f"    Categorías únicas    : {unique_cats}")
    print(f"    Clientes únicos      : {unique_clients:,}")
    print(f"    Tiendas              : {unique_stores}")
    print(f"    Período              : {transactions['date'].min().date()} → "
          f"{transactions['date'].max().date()}")

    return transactions, categories
