from django.urls import path

from .moderation_views import (
    ModerationDashboardView,
    ModerationEventApproveView,
    ModerationEventDeleteView,
    ModerationEventListView,
    ModerationEventRejectView,
    ModerationHistoryView,
    ModerationUserApproveView,
    ModerationUserListView,
    ModerationUserRevokeView,
    ModerationUserToggleModeratorView,
)

urlpatterns = [
    path("", ModerationDashboardView.as_view(), name="moderation_dashboard"),
    # Event actions
    path(
        "events/<uuid:pk>/approve/",
        ModerationEventApproveView.as_view(),
        name="moderation_event_approve",
    ),
    path(
        "events/<uuid:pk>/reject/",
        ModerationEventRejectView.as_view(),
        name="moderation_event_reject",
    ),
    path(
        "events/<uuid:pk>/delete/",
        ModerationEventDeleteView.as_view(),
        name="moderation_event_delete",
    ),
    # Event list (all statuses, filtered)
    path("events/", ModerationEventListView.as_view(), name="moderation_events"),
    # History
    path("history/", ModerationHistoryView.as_view(), name="moderation_history"),
    # User management
    path("users/", ModerationUserListView.as_view(), name="moderation_users"),
    path(
        "users/<uuid:pk>/approve/",
        ModerationUserApproveView.as_view(),
        name="moderation_user_approve",
    ),
    path(
        "users/<uuid:pk>/revoke/",
        ModerationUserRevokeView.as_view(),
        name="moderation_user_revoke",
    ),
    path(
        "users/<uuid:pk>/toggle-moderator/",
        ModerationUserToggleModeratorView.as_view(),
        name="moderation_user_toggle_moderator",
    ),
]
