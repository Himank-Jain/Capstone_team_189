"""
phase2/alerting/notifiers
==========================================
P2-M14  Explainable Alert API — delivery channels
CAPSTONE-189

Was an empty placeholder module in the pre-P2-M14 tree (this package
is where the Directory Structure's own P2-M14 slot expected the
notifier implementations to live). Populated here with BaseNotifier and
the four channels the ticket asks for: Slack, Email, PagerDuty, and the
DashboardWriter time-series sink.
"""

from .base_notifier import BaseNotifier
from .dashboard_writer import BaseDashboardStore, DashboardWriter, InMemoryDashboardStore, PostgresDashboardStore
from .email_notifier import EmailNotifier
from .pagerduty_notifier import PagerDutyNotifier
from .rate_limiter import AsyncRateLimiter
from .slack_notifier import SlackNotifier

__all__ = [
    "BaseNotifier",
    "SlackNotifier",
    "EmailNotifier",
    "PagerDutyNotifier",
    "DashboardWriter",
    "BaseDashboardStore",
    "InMemoryDashboardStore",
    "PostgresDashboardStore",
    "AsyncRateLimiter",
]
