"""AirMini GetLoggedData request and asynchronous notification collector."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

from as11_rpc import Transport, TransportError


DEFAULT_FROM_TIME = "2008-01-01T00:00:00.001Z"


@dataclass(frozen=True)
class LoggedDataResult:
    response: dict
    log_stream_id: int
    requested_data_ids: tuple[str, ...]
    valid_data_ids: tuple[str, ...]
    complete_data_ids: tuple[str, ...]
    notifications: tuple[dict, ...]
    notification_count: int
    timed_out: bool

    @property
    def complete(self) -> bool:
        return set(self.valid_data_ids).issubset(self.complete_data_ids)


def logged_data_params(data_ids: list[str] | tuple[str, ...],
                       from_time: str) -> list[dict[str, str]]:
    if not data_ids:
        raise ValueError("GetLoggedData needs at least one dataId")
    if not from_time:
        raise ValueError("GetLoggedData fromTime cannot be empty")
    return [{"dataId": data_id, "fromTime": from_time}
            for data_id in data_ids]


class _NotificationCollector:
    def __init__(self, requested_data_ids: tuple[str, ...],
                 on_notification: Callable[[dict], None] | None,
                 retain_notifications: bool) -> None:
        self.requested_data_ids = requested_data_ids
        self.on_notification = on_notification
        self.stream_id: int | None = None
        self.valid_data_ids: set[str] = set()
        self.complete_data_ids: set[str] = set()
        self.notifications: list[dict] = []
        self.notification_count = 0
        self.retain_notifications = retain_notifications
        self.early_notifications: list[dict] = []
        self.done = threading.Event()
        self.lock = threading.Lock()

    def configure(self, stream_id: int, valid_data_ids: set[str]) -> None:
        with self.lock:
            self.stream_id = stream_id
            self.valid_data_ids = valid_data_ids
            early, self.early_notifications = self.early_notifications, []
        for message in early:
            self.feed(message)

    def feed(self, message: dict) -> bool:
        callback_message = None
        with self.lock:
            if self.stream_id is None:
                self.early_notifications.append(message)
                return False
            params = message.get("params")
            if not isinstance(params, dict) or params.get("logStreamId") != self.stream_id:
                return False
            data = params.get("data")
            if not isinstance(data, list):
                return False

            self.notification_count += 1
            if self.retain_notifications:
                self.notifications.append(message)
            callback_message = message
            for entry in data:
                if not isinstance(entry, dict) or not entry.get("complete", False):
                    continue
                data_id = entry.get("dataId")
                if isinstance(data_id, str) and data_id:
                    self.complete_data_ids.add(data_id)
            if self.valid_data_ids.issubset(self.complete_data_ids):
                self.done.set()

        if callback_message is not None and self.on_notification is not None:
            self.on_notification(callback_message)
        return self.done.is_set()


def _valid_ids(response_result: dict,
               requested_data_ids: tuple[str, ...]) -> set[str]:
    entries = response_result.get("dataIds")
    if not isinstance(entries, list) or not entries:
        return set(requested_data_ids)
    valid: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        data_id = entry.get("dataId")
        is_valid = entry.get("valid", entry.get("isValid", False))
        if (isinstance(data_id, str) and data_id in requested_data_ids
                and is_valid is True):
            valid.add(data_id)
    return valid


def collect_logged_data(
    transport: Transport,
    data_ids: list[str] | tuple[str, ...],
    *,
    from_time: str = DEFAULT_FROM_TIME,
    rpc_timeout: float = 10.0,
    notification_timeout: float = 60.0,
    on_notification: Callable[[dict], None] | None = None,
    retain_notifications: bool = True,
) -> LoggedDataResult:
    """Call GetLoggedData and collect matching notifications to completion.

    The handler is installed before the request because AirMini can begin
    pushing records before the initial response (and its ``logStreamId``)
    reaches the caller.  Only notifications matching that stream are retained.
    """
    requested = tuple(dict.fromkeys(data_ids))
    params = logged_data_params(requested, from_time)
    collector = _NotificationCollector(
        requested, on_notification, retain_notifications
    )
    transport.set_notification_handler(collector.feed)
    try:
        response = transport.rpc("GetLoggedData", params, timeout=rpc_timeout)
        result = response.get("result")
        if not isinstance(result, dict):
            raise TransportError("GetLoggedData response has no result object")
        stream_id = result.get("logStreamId")
        if not isinstance(stream_id, int) or stream_id < 0:
            raise TransportError("GetLoggedData response has no valid logStreamId")
        valid_ids = _valid_ids(result, requested)
        if not valid_ids:
            raise TransportError("GetLoggedData rejected every requested dataId")

        collector.configure(stream_id, valid_ids)
        if not collector.done.is_set():
            transport.listen_for_notifications(duration=notification_timeout)
        timed_out = not collector.done.is_set()
        with collector.lock:
            notifications = tuple(collector.notifications)
            notification_count = collector.notification_count
            completed = tuple(sorted(collector.complete_data_ids))
        return LoggedDataResult(
            response=response,
            log_stream_id=stream_id,
            requested_data_ids=requested,
            valid_data_ids=tuple(data_id for data_id in requested
                                 if data_id in valid_ids),
            complete_data_ids=completed,
            notifications=notifications,
            notification_count=notification_count,
            timed_out=timed_out,
        )
    finally:
        transport.set_notification_handler(None)


__all__ = [
    "DEFAULT_FROM_TIME", "LoggedDataResult", "logged_data_params",
    "collect_logged_data",
]
