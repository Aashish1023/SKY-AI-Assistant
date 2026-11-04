"""A small, thread-safe publish/subscribe hub.

Components never call each other directly. They publish events and subscribe
to the events they care about, so the UI, voice and memory can be developed
and tested separately.

Threading rule: handlers run on the thread that published the event. For Sky
that is usually a background worker thread, so a handler that touches the UI
must hand the work over to the UI thread (Qt signals do this; see step 1.6).
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from app.core.events import Event
from app.utils.logger import get_logger

logger = get_logger("events")

E = TypeVar("E", bound=Event)


@dataclass(eq=False)  # compared by identity, so two identical subscriptions stay distinct
class _Subscription:
    event_type: type[Event]
    handler: Callable[[Any], None]


class EventManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscriptions: list[_Subscription] = []

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> Callable[[], None]:
        """Call ``handler`` for every published event of ``event_type`` (or a subclass).

        Returns a function that removes the subscription again.
        """
        subscription = _Subscription(event_type, handler)
        with self._lock:
            self._subscriptions.append(subscription)

        def unsubscribe() -> None:
            with self._lock:
                if subscription in self._subscriptions:
                    self._subscriptions.remove(subscription)

        return unsubscribe

    def publish(self, event: Event) -> None:
        """Deliver an event to every matching handler, in subscription order.

        A handler that raises is logged and skipped; it can never stop the
        other handlers or the code that published the event.
        """
        with self._lock:
            subscriptions = list(self._subscriptions)  # copy: handlers may (un)subscribe
        for subscription in subscriptions:
            if isinstance(event, subscription.event_type):
                try:
                    subscription.handler(event)
                except Exception:
                    logger.exception(
                        "Handler %r failed while handling %s", subscription.handler, type(event).__name__
                    )
