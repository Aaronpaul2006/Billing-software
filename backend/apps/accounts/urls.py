from django.db import transaction
from django.urls import path

from . import member_views, views

# Sign-in endpoints manage their own transactions: a failed-login counter or
# a revoked token family must be committed even though the response is 401.
public = transaction.non_atomic_requests

urlpatterns = [
    path("auth/signup", public(views.SignupView.as_view()), name="auth-signup"),
    path("auth/login", public(views.LoginView.as_view()), name="auth-login"),
    path("auth/mfa/verify", public(views.MfaVerifyView.as_view()), name="auth-mfa-verify"),
    path("auth/token/refresh", public(views.RefreshView.as_view()), name="auth-refresh"),
    path("auth/logout", views.LogoutView.as_view(), name="auth-logout"),
    path("auth/switch-tenant", views.SwitchTenantView.as_view(), name="auth-switch-tenant"),
    path("auth/sessions", views.SessionListView.as_view(), name="auth-sessions"),
    path(
        "auth/sessions/<uuid:session_id>",
        views.SessionDetailView.as_view(),
        name="auth-session-detail",
    ),
    path("auth/mfa/setup", views.MfaSetupView.as_view(), name="auth-mfa-setup"),
    path("auth/mfa/enable", views.MfaEnableView.as_view(), name="auth-mfa-enable"),
    path("auth/mfa/disable", views.MfaDisableView.as_view(), name="auth-mfa-disable"),
    path("me", views.MeView.as_view(), name="me"),
    path("members", member_views.MemberListView.as_view(), name="members"),
    path("invitations", member_views.InvitationListView.as_view(), name="invitations"),
    path(
        "invitations/<uuid:membership_id>/accept",
        member_views.InvitationAcceptView.as_view(),
        name="invitation-accept",
    ),
    path(
        "invitations/<uuid:membership_id>/decline",
        member_views.InvitationDeclineView.as_view(),
        name="invitation-decline",
    ),
    path(
        "members/<uuid:membership_id>",
        member_views.MemberDetailView.as_view(),
        name="member-detail",
    ),
]
