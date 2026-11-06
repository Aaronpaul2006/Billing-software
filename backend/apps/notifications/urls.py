from django.urls import path

from . import views

urlpatterns = [
    path("notifications", views.NotificationListView.as_view(), name="notifications"),
    path(
        "notifications/unread-count",
        views.UnreadCountView.as_view(),
        name="notifications-unread-count",
    ),
    path("notifications/read-all", views.ReadAllView.as_view(), name="notifications-read-all"),
    path(
        "notifications/<uuid:notification_id>/read",
        views.ReadView.as_view(),
        name="notification-read",
    ),
]
