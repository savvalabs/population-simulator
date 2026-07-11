"""Tests for :mod:`population_engine.ecs.events`."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from population_engine.ecs.errors import EventError
from population_engine.ecs.events import Event, EventBus

# -- sample events ----------------------------------------------------------


@dataclass
class Spawned(Event):
    entity_id: int = 0


@dataclass
class Died(Event):
    entity_id: int = 0


@dataclass
class _Derived(Spawned):
    pass


# -- subscribe / publish / flush -------------------------------------------


def test_publish_is_deferred_until_flush() -> None:
    bus = EventBus()
    seen: list = []
    bus.subscribe(Spawned, seen.append)
    bus.publish(Spawned(entity_id=1))
    assert seen == []          # not delivered yet
    assert bus.pending() == 1
    assert bus.flush() == 1
    assert [e.entity_id for e in seen] == [1]
    assert bus.pending() == 0


def test_flush_dispatches_in_fifo_order() -> None:
    bus = EventBus()
    order: list = []
    bus.subscribe(Spawned, lambda e: order.append(("s", e.entity_id)))
    bus.subscribe(Died, lambda e: order.append(("d", e.entity_id)))
    for i in (1, 2, 3):
        bus.publish(Spawned(entity_id=i))
    bus.publish(Died(entity_id=9))
    assert bus.flush() == 4
    assert order == [("s", 1), ("s", 2), ("s", 3), ("d", 9)]


def test_flush_returns_zero_when_queue_empty() -> None:
    assert EventBus().flush() == 0


def test_multiple_handlers_same_type_all_called_in_order() -> None:
    bus = EventBus()
    calls: list = []
    bus.subscribe(Spawned, lambda e: calls.append("first"))
    bus.subscribe(Spawned, lambda e: calls.append("second"))
    bus.publish(Spawned())
    bus.flush()
    assert calls == ["first", "second"]


def test_event_without_subscribers_is_dropped_on_flush() -> None:
    bus = EventBus()
    bus.publish(Spawned(entity_id=1))
    assert bus.flush() == 1   # dispatched to nobody, but still drained
    assert bus.pending() == 0


def test_subscription_is_exact_type_only() -> None:
    # A handler on the base event type does not receive derived events.
    bus = EventBus()
    base_seen: list = []
    derived_seen: list = []
    bus.subscribe(Spawned, base_seen.append)
    bus.subscribe(_Derived, derived_seen.append)
    bus.publish(_Derived(entity_id=5))
    bus.flush()
    assert base_seen == []            # base subscribers did NOT receive it
    assert [e.entity_id for e in derived_seen] == [5]


# -- clear -----------------------------------------------------------------


def test_clear_drops_queued_without_dispatch() -> None:
    bus = EventBus()
    seen: list = []
    bus.subscribe(Spawned, seen.append)
    bus.publish(Spawned(entity_id=1))
    bus.publish(Spawned(entity_id=2))
    assert bus.clear() == 2
    assert seen == []
    assert bus.pending() == 0
    # Queue is clean: a later flush dispatches nothing new.
    assert bus.flush() == 0


# -- cancel ----------------------------------------------------------------


def test_cancel_stops_delivery() -> None:
    bus = EventBus()
    seen: list = []
    sub = bus.subscribe(Spawned, seen.append)
    assert sub.active
    bus.publish(Spawned(entity_id=1))
    sub.cancel()
    assert not sub.active
    assert bus.flush() == 1      # drained, but handler is gone
    assert seen == []
    assert not bus.has_subscribers(Spawned)


def test_cancel_twice_raises() -> None:
    bus = EventBus()
    sub = bus.subscribe(Spawned, lambda _e: None)
    sub.cancel()
    with pytest.raises(EventError):
        sub.cancel()


def test_handler_cancels_another_during_dispatch() -> None:
    # Cancelling a not-yet-run handler mid-flush must prevent it from running.
    bus = EventBus()
    calls: list = []

    sub_second: list = [None]

    def first(_e: object) -> None:
        calls.append("first")
        assert sub_second[0] is not None
        sub_second[0].cancel()

    def second(_e: object) -> None:
        calls.append("second")

    bus.subscribe(Spawned, first)
    sub_second[0] = bus.subscribe(Spawned, second)
    bus.publish(Spawned())
    bus.flush()
    assert calls == ["first"]    # second was cancelled before it ran


# -- validation ------------------------------------------------------------


def test_publish_non_event_raises() -> None:
    with pytest.raises(TypeError):
        EventBus().publish(object())  # type: ignore[arg-type]


def test_subscribe_non_event_raises() -> None:
    with pytest.raises(TypeError):
        EventBus().subscribe(int, lambda _e: None)  # type: ignore[arg-type]


def test_subscribe_non_callable_raises() -> None:
    with pytest.raises(TypeError):
        EventBus().subscribe(Spawned, "not callable")  # type: ignore[arg-type]
