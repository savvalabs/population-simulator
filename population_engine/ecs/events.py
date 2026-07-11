"""Event system: queue-backed, tick-bounded publish/subscribe.

Events decouple producers (systems/plugins) from consumers. Producers call
:meth:`EventBus.publish` to *queue* an event; nothing is delivered until
:meth:`EventBus.flush` is called, typically once per tick by the engine. This
keeps within-tick processing deterministic: systems publish during a tick and
subscribers observe the full batch at the end of it, so reactions take effect
on the following tick. :meth:`EventBus.clear` drops the queue without
dispatch, useful at tick boundaries where stale events should not survive.

Events are plain data containers (typically ``@dataclass``) subclassing
:class:`Event`. Subscriptions are keyed by the *exact* event type — publishing
a subclass does not route it to its base type's subscribers — which keeps
dispatch deterministic and cheap. Handlers are plain callables taking the
single event argument; an exception raised by a handler propagates (fail-fast)
and aborts the flush.
"""

from __future__ import annotations

from collections import deque
from typing import Callable, Iterable, Tuple

from .errors import EventError

__all__ = ["Event", "EventBus", "Subscription"]

#: A handler is a no-return callable taking one event argument.
Handler = Callable[["Event"], None]

# Internal type alias for a registered handler, paired with its subscription.
_RegisteredHandler = Tuple[Handler, "Subscription"]


class Event:
    """Marker base class for events. Subclass it (typically with ``@dataclass``)."""


class Subscription:
    """A handle to a subscription; call :meth:`cancel` to remove it."""

    __slots__ = ("_bus", "_event_type", "_handler", "_active")

    def __init__(self, bus: "EventBus", event_type: type, handler: Handler) -> None:
        self._bus = bus
        self._event_type = event_type
        self._handler = handler
        self._active = True

    @property
    def active(self) -> bool:
        return self._active

    def cancel(self) -> None:
        """Remove this subscription from its bus. Cannot be called twice."""
        if not self._active:
            raise EventError("subscription already cancelled")
        self._bus._remove(self._event_type, self._handler)  # noqa: SLF001 - bus friendship
        self._active = False


class EventBus:
    """A queue-backed, deferred-delivery pub/sub bus."""

    __slots__ = ("_handlers", "_queue")

    def __init__(self) -> None:
        # event_type -> list of (handler, Subscription) (insertion order).
        self._handlers: dict[type, list[_RegisteredHandler]] = {}
        # Pending events, FIFO.
        self._queue: deque = deque()

    # -- subscription --------------------------------------------------

    def subscribe(self, event_type: type, handler: Handler) -> Subscription:
        """Register ``handler`` for events of ``event_type``; return a subscription."""
        if not isinstance(event_type, type):
            raise TypeError(f"event_type must be a class, got {event_type!r}")
        if not callable(handler):
            raise TypeError(f"handler must be callable, got {handler!r}")
        if not issubclass(event_type, Event):
            raise TypeError(f"{event_type!r} must subclass Event")
        sub = Subscription(self, event_type, handler)
        self._handlers.setdefault(event_type, []).append((handler, sub))
        return sub

    # -- publishing / draining ---------------------------------------

    def publish(self, event: object) -> None:
        """Queue an event for deferred delivery on the next :meth:`flush`."""
        if not isinstance(event, Event):
            raise TypeError(f"event must subclass Event, got {event!r}")
        self._queue.append(event)

    def flush(self) -> int:
        """Dispatch every queued event (FIFO) and clear the queue.

        Returns the number of events dispatched. A handler exception aborts the
        flush and propagates; previously-dispatched handlers have already run.
        """
        count = 0
        # Create a copy of the queue so handlers added/removed during flush
        # don't alter the iteration.
        queue_copy = list(self._queue)
        self._queue.clear()

        for event in queue_copy:
            self._dispatch(event)
            count += 1
        return count

    def clear(self) -> int:
        """Drop all queued events without dispatching; return the count dropped."""
        dropped = len(self._queue)
        self._queue.clear()
        return dropped

    def pending(self) -> int:
        """Number of events queued and awaiting dispatch."""
        return len(self._queue)

    def has_subscribers(self, event_type: type) -> bool:
        """True iff at least one subscriber is registered for ``event_type``."""
        # Filter out inactive subscriptions.
        return any(sub.active for _h, sub in self._handlers.get(event_type, ()))

    # -- internals ----------------------------------------------------

    def _dispatch(self, event: Event) -> None:
        # Snapshot the handler list so a handler cancelling another during
        # dispatch does not mutate the list we are iterating.
        # Only dispatch to active subscriptions.
        for handler, sub in list(self._handlers.get(type(event), ())):
            if sub.active:
                handler(event)

    def _remove(self, event_type: type, handler: Handler) -> None:
        handlers = self._handlers.get(event_type)
        if not handlers:
            return
        # Remove the tuple (handler, subscription) matching the handler.
        for i, (existing_handler, _sub) in enumerate(handlers):
            if existing_handler is handler:
                del handlers[i]
                if not handlers:
                    del self._handlers[event_type]
                return
