"""Daily-life connectors (§38, §39, §40): calendar/reminders, email, briefing."""
from .calendar import CalendarStore, Reminder  # noqa: F401
from .email import EmailConnector, StubEmailConnector, Draft  # noqa: F401
from .briefing import build_briefing  # noqa: F401
