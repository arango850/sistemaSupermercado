from django.db import models


class AnalysisRun(models.Model):
    """Registra cada ejecución del pipeline de análisis."""

    STATUS_CHOICES = [
        ('running',   'En ejecución'),
        ('completed', 'Completado'),
        ('error',     'Error'),
    ]

    started_at   = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status       = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running')
    error_msg    = models.TextField(blank=True, default='')

    # Métricas de alto nivel registradas al completar
    total_transactions = models.BigIntegerField(null=True, blank=True)
    total_clients      = models.BigIntegerField(null=True, blank=True)
    total_units        = models.BigIntegerField(null=True, blank=True)
    duration_seconds   = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"AnalysisRun #{self.pk} — {self.status} ({self.started_at:%Y-%m-%d %H:%M})"


class Category(models.Model):
    """Catálogo de categorías de productos cargado desde Categories.csv."""

    category_id   = models.IntegerField(unique=True)
    category_name = models.CharField(max_length=255)

    class Meta:
        ordering = ['category_id']

    def __str__(self):
        return f"{self.category_id} — {self.category_name}"
