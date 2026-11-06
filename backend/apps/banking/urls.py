from django.urls import path

from . import views

urlpatterns = [
    path(
        "bank-statements/preview",
        views.StatementPreviewView.as_view(),
        name="bank-statement-preview",
    ),
    path(
        "bank-statements/import", views.StatementImportView.as_view(), name="bank-statement-import"
    ),
    path("bank-lines", views.BankLineListView.as_view(), name="bank-lines"),
    path("bank-lines/accounts", views.BankAccountsView.as_view(), name="bank-accounts"),
    path(
        "bank-lines/<uuid:line_id>/match", views.BankLineMatchView.as_view(), name="bank-line-match"
    ),
    path(
        "bank-lines/<uuid:line_id>/record",
        views.BankLineRecordView.as_view(),
        name="bank-line-record",
    ),
    path(
        "bank-lines/<uuid:line_id>/ignore",
        views.BankLineIgnoreView.as_view(),
        name="bank-line-ignore",
    ),
    path(
        "bank-lines/<uuid:line_id>/reopen",
        views.BankLineReopenView.as_view(),
        name="bank-line-reopen",
    ),
]
