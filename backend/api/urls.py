from django.urls import path
from . import views

urlpatterns = [
    # Resumen Ejecutivo
    path('summary',                         views.summary,                    name='summary'),
    # Visualizaciones Analíticas
    path('charts/time-series',              views.time_series,                name='time-series'),
    path('charts/boxplot',                  views.boxplot,                    name='boxplot'),
    path('charts/heatmap',                  views.heatmap,                    name='heatmap'),
    # Análisis Avanzado
    path('segments',                        views.segments,                   name='segments'),
    path('recommendations/category',                        views.recommendations_by_category, name='recs-category'),
    path('recommendations/client/<int:client_id>',          views.recommendations_by_client,   name='recs-client'),
    path('recommendations/product/<int:product_id>',        views.recommendations_by_product,  name='recs-product'),
    # Pipeline
    path('analysis/run',                    views.run_analysis,               name='run-analysis'),
    path('analysis/status',                 views.analysis_status,            name='analysis-status'),
    path('analysis/history',               views.analysis_history,            name='analysis-history'),
    # Catálogo ORM
    path('categories',                      views.categories,                 name='categories'),
]
