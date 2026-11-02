from django.urls import path

from . import views

urlpatterns = [
    path("reports/summary", views.SummaryView.as_view(), name="report-summary"),
    path("reports/dashboard", views.DashboardView.as_view(), name="report-dashboard"),
    path(
        "reports/billing-by-month",
        views.BillingByMonthView.as_view(),
        name="report-billing-by-month",
    ),
    path("reports/receivables", views.ReceivablesView.as_view(), name="report-receivables"),
    path("reports/projects", views.ProjectsReportView.as_view(), name="report-projects"),
    path(
        "reports/projects/<uuid:project_id>",
        views.ProjectReportView.as_view(),
        name="report-project",
    ),
    path(
        "parties/<uuid:party_id>/statement",
        views.StatementView.as_view(),
        name="party-statement",
    ),
    path("reports/gst-summary", views.GstSummaryView.as_view(), name="report-gst-summary"),
    path(
        "reports/tds-reconciliation",
        views.TdsReconciliationView.as_view(),
        name="report-tds-reconciliation",
    ),
]
