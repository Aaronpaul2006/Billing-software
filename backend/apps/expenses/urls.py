from django.urls import path

from . import views

urlpatterns = [
    path("expenses", views.ExpenseListView.as_view(), name="expenses"),
    path("expenses/<uuid:expense_id>", views.ExpenseDetailView.as_view(), name="expense-detail"),
    path("expenses/<uuid:expense_id>/void", views.ExpenseVoidView.as_view(), name="expense-void"),
]
