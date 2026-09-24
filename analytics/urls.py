from django.urls import path

from .views import StatsDashboardView

urlpatterns = [
    path("stats/", StatsDashboardView.as_view(), name="stats_dashboard"),
]
