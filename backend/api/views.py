"""
views.py — Endpoints REST del sistema de análisis de supermercado.

Todos los endpoints GET leen los JSON pre-calculados de output/.
El endpoint POST /analysis/run dispara el pipeline Python en un hilo
de fondo y persiste el estado en el modelo AnalysisRun (ORM Django).
"""

import json
import math
import os
import sys
import threading
import datetime

import django
from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status as http_status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_json(filename: str):
    """Lee un archivo JSON de output/. Retorna None si no existe."""
    path = os.path.join(settings.OUTPUT_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _sanitize(obj):
    """Reemplaza recursivamente float NaN/Inf por None para que JSON no falle."""
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _not_found(msg='Datos no disponibles. Ejecuta el análisis primero.'):
    return Response({'error': msg}, status=http_status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# Pipeline — ejecuta en hilo de fondo, persiste estado en AnalysisRun ORM
# ---------------------------------------------------------------------------

def _run_pipeline_thread(run_id: int, use_spark: bool = False):
    """Ejecuta run_pipeline y actualiza el registro AnalysisRun."""
    # Necesario para acceder al ORM desde un hilo secundario
    django.db.close_old_connections()

    from api.models import AnalysisRun  # importación tardía para evitar ciclos

    try:
        if settings.ANALYSIS_DIR not in sys.path:
            sys.path.insert(0, settings.ANALYSIS_DIR)
        from main import run_pipeline  # noqa: PLC0415

        t0 = datetime.datetime.now()
        run_pipeline(settings.DATA_DIR, settings.OUTPUT_DIR, use_spark=use_spark)
        duration = (datetime.datetime.now() - t0).total_seconds()

        summary = _read_json('executive_summary.json') or {}

        AnalysisRun.objects.filter(pk=run_id).update(
            status='completed',
            completed_at=datetime.datetime.now(datetime.timezone.utc),
            duration_seconds=duration,
            total_transactions=summary.get('total_transactions'),
            total_clients=summary.get('total_clients'),
            total_units=summary.get('total_units_sold'),
            error_msg='',
        )
    except Exception as exc:
        AnalysisRun.objects.filter(pk=run_id).update(
            status='error',
            completed_at=datetime.datetime.now(datetime.timezone.utc),
            error_msg=str(exc),
        )
    finally:
        django.db.close_old_connections()


# ---------------------------------------------------------------------------
# Resumen Ejecutivo
# ---------------------------------------------------------------------------

@api_view(['GET'])
def summary(request):
    data = _read_json('executive_summary.json')
    if data is None:
        return _not_found()
    return Response(data)


# ---------------------------------------------------------------------------
# Visualizaciones Analíticas
# ---------------------------------------------------------------------------

@api_view(['GET'])
def time_series(request):
    data = _read_json('time_series.json')
    if data is None:
        return _not_found()
    return Response(data)


@api_view(['GET'])
def boxplot(request):
    data = _read_json('boxplot_data.json')
    if data is None:
        return _not_found()
    return Response(data)


@api_view(['GET'])
def heatmap(request):
    data = _read_json('heatmap_data.json')
    if data is None:
        return _not_found()
    return Response(data)


# ---------------------------------------------------------------------------
# Análisis Avanzado (disponibles cuando clustering.py y recommender.py existan)
# ---------------------------------------------------------------------------

@api_view(['GET'])
def segments(request):
    data = _read_json('clustering.json')
    if data is None:
        return _not_found('Segmentación no disponible todavía.')
    return Response(data)


@api_view(['GET'])
def recommendations_by_client(request, client_id: int):
    """
    Retorna recomendaciones personalizadas para un cliente específico.
    - Busca el segmento del cliente en client_segments.json
    - Usa las top categorías del segmento como antecedentes
    - Devuelve reglas de asociación relevantes ordenadas por lift
    """
    cs_data = _read_json('client_segments.json')
    if cs_data is None:
        return _not_found('Segmentación de clientes no disponible. Ejecuta el análisis primero.')

    client_segments = cs_data.get('client_segments', {})
    seg_id = client_segments.get(str(client_id))
    if seg_id is None:
        return Response(
            {'error': f'Cliente {client_id} no encontrado en la segmentación.'},
            status=http_status.HTTP_404_NOT_FOUND,
        )

    seg_label = cs_data.get('segment_labels', {}).get(str(seg_id), f'Segmento {seg_id + 1}')
    top_cats  = cs_data.get('segment_top_categories', {}).get(str(seg_id), [])

    rec_data = _read_json('recommendations.json')
    if rec_data is None:
        return _not_found('Recomendaciones no disponibles todavía.')

    cat_index = rec_data.get('category_index', {})

    # Reglas donde el antecedente pertenece al top de categorías del segmento
    personalized: list[dict] = []
    seen_consequents: set[str] = set()
    for cat in top_cats:
        for rule in cat_index.get(cat, []):
            rec = rule['recommendation']
            lift       = rule.get('lift', 0)
            confidence = rule.get('confidence', 0)
            # Descartar reglas con valores no finitos (NaN / inf) que rompen JSON
            if not (math.isfinite(lift) and math.isfinite(confidence)):
                continue
            if rec not in seen_consequents and rec not in top_cats:
                seen_consequents.add(rec)
                personalized.append({'from_category': cat, **rule})

    personalized.sort(key=lambda r: -(r['lift'] or 0))

    return Response(_sanitize({
        'client_id':       client_id,
        'segment_id':      seg_id,
        'segment_label':   seg_label,
        'top_categories':  top_cats,
        'recommendations': personalized[:20],
    }))


@api_view(['GET'])
def recommendations_by_product(request, product_id: int):
    """Retorna recomendaciones para la categoría con category_id = product_id."""
    data = _read_json('recommendations.json')
    if data is None:
        return _not_found('Recomendaciones no disponibles todavía.')
    # Buscar en category_support para obtener el nombre
    support_list = data.get('category_support', [])
    cat_name = next(
        (s['category_name'] for s in support_list if s.get('category_id') == product_id),
        None
    )
    if cat_name is None:
        return Response({'error': f'Categoría {product_id} no encontrada.'}, status=404)
    recs = data.get('category_index', {}).get(cat_name, [])
    return Response({'category_id': product_id, 'category_name': cat_name,
                     'recommendations': recs})


@api_view(['GET'])
def recommendations_by_category(request):
    """
    GET /api/recommendations/category?name=<NOMBRE>
    Retorna recomendaciones para la categoría dada por nombre.
    Sin parámetro retorna el resumen global.
    """
    data = _read_json('recommendations.json')
    if data is None:
        return _not_found('Recomendaciones no disponibles todavía.')

    name = request.query_params.get('name', '').strip()
    if not name:
        # Devolver metadatos y todas las categorías que tienen reglas
        return Response(_sanitize({
            'total_rules':     data.get('total_rules', 0),
            'n_transactions':  data.get('n_transactions', 0),
            'min_support':     data.get('min_support'),
            'min_confidence':  data.get('min_confidence'),
            'min_lift':        data.get('min_lift'),
            'categories_with_rules': sorted(data.get('category_index', {}).keys()),
            'category_support': data.get('category_support', [])[:30],
            'top_rules':       data.get('rules', [])[:30],
        }))

    recs = data.get('category_index', {}).get(name)
    if recs is None:
        return Response({'error': f'No se encontraron reglas para "{name}".'}, status=404)
    return Response(_sanitize({'category_name': name, 'recommendations': recs}))


# ---------------------------------------------------------------------------
# Control del pipeline — usa ORM para tracking
# ---------------------------------------------------------------------------

@api_view(['POST'])
def run_analysis(request):
    from api.models import AnalysisRun

    if AnalysisRun.objects.filter(status='running').exists():
        last = AnalysisRun.objects.filter(status='running').first()
        return Response(
            {'message': 'El análisis ya está en curso.', **_run_to_dict(last)},
            status=http_status.HTTP_409_CONFLICT,
        )

    run = AnalysisRun.objects.create(status='running')
    use_spark = bool(request.data.get('use_spark', False))
    thread = threading.Thread(
        target=_run_pipeline_thread,
        args=(run.pk,),
        kwargs={'use_spark': use_spark},
        daemon=True,
    )
    thread.start()
    return Response({'message': 'Análisis iniciado.', 'use_spark': use_spark, **_run_to_dict(run)})


@api_view(['GET'])
def analysis_status(request):
    from api.models import AnalysisRun

    last = AnalysisRun.objects.first()
    if last is None:
        return Response({'status': 'idle', 'started_at': None, 'completed_at': None, 'error': None})
    return Response(_run_to_dict(last))


@api_view(['GET'])
def analysis_history(request):
    """Historial de las últimas 20 ejecuciones del pipeline (ORM)."""
    from api.models import AnalysisRun

    runs = AnalysisRun.objects.all()[:20]
    return Response([_run_to_dict(r) for r in runs])


# ---------------------------------------------------------------------------
# Catálogo de categorías desde ORM
# ---------------------------------------------------------------------------

@api_view(['GET'])
def categories(request):
    """Devuelve todas las categorías almacenadas en la BD Django."""
    from api.models import Category

    cats = Category.objects.all().values('category_id', 'category_name')
    return Response(list(cats))


# ---------------------------------------------------------------------------
# Helpers ORM
# ---------------------------------------------------------------------------

def _run_to_dict(run) -> dict:
    return {
        'id':                 run.pk,
        'status':             run.status,
        'started_at':         run.started_at.isoformat() if run.started_at else None,
        'completed_at':       run.completed_at.isoformat() if run.completed_at else None,
        'error':              run.error_msg or None,
        'duration_seconds':   run.duration_seconds,
        'total_transactions': run.total_transactions,
        'total_clients':      run.total_clients,
        'total_units':        run.total_units,
    }
