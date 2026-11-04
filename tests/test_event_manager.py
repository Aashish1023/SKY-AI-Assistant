"""Tests for app.core.event_manager."""
import threading
from dataclasses import dataclass

from app.core.event_manager import EventManager
from app.core.events import AnswerToken, Event, StateChanged, AssistantState


@dataclass(frozen=True)
class Ping(Event):
    n: int = 0


def test_handler_receives_matching_events_only():
    events, seen = EventManager(), []
    events.subscribe(Ping, seen.append)

    events.publish(Ping(1))
    events.publish(AnswerToken("ignored"))

    assert seen == [Ping(1)]


def test_subscribing_to_the_base_class_receives_everything():
    events, seen = EventManager(), []
    events.subscribe(Event, seen.append)

    events.publish(Ping(1))
    events.publish(StateChanged(AssistantState.IDLE))

    assert len(seen) == 2


def test_handlers_run_in_subscription_order():
    events, order = EventManager(), []
    events.subscribe(Ping, lambda e: order.append("first"))
    events.subscribe(Ping, lambda e: order.append("second"))

    events.publish(Ping())

    assert order == ["first", "second"]


def test_unsubscribe_stops_delivery_and_is_safe_to_repeat():
    events, seen = EventManager(), []
    unsubscribe = events.subscribe(Ping, seen.append)

    events.publish(Ping(1))
    unsubscribe()
    unsubscribe()  # second call must not raise
    events.publish(Ping(2))

    assert seen == [Ping(1)]


def test_the_same_handler_subscribed_twice_is_called_twice():
    events, seen = EventManager(), []
    first = events.subscribe(Ping, seen.append)
    events.subscribe(Ping, seen.append)

    events.publish(Ping(1))
    first()
    events.publish(Ping(2))

    assert seen == [Ping(1), Ping(1), Ping(2)]


def test_a_failing_handler_does_not_stop_the_others():
    events, seen = EventManager(), []

    def broken(event):
        raise RuntimeError("handler bug")

    events.subscribe(Ping, broken)
    events.subscribe(Ping, seen.append)

    events.publish(Ping(7))  # must not raise

    assert seen == [Ping(7)]


def test_a_handler_may_unsubscribe_itself_while_handling():
    events, calls = EventManager(), []

    def once(event):
        calls.append(event)
        unsubscribe()

    unsubscribe = events.subscribe(Ping, once)

    events.publish(Ping(1))
    events.publish(Ping(2))

    assert calls == [Ping(1)]


def test_publishing_from_many_threads_loses_nothing():
    events, seen, lock = EventManager(), [], threading.Lock()

    def record(event):
        with lock:
            seen.append(event.n)

    events.subscribe(Ping, record)

    def worker(start):
        for i in range(100):
            events.publish(Ping(start + i))

    threads = [threading.Thread(target=worker, args=(t * 1000,)) for t in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(seen) == 500
