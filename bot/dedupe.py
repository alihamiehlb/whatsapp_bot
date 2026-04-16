import hashlib
import re
import threading
import time

import settings as config

_SPACE_RE = re.compile(r"\s+")


def _normalize_text(text: str) -> str:
    cleaned = (text or "").strip().lower()
    cleaned = _SPACE_RE.sub(" ", cleaned)
    return cleaned


class OutgoingDeduplicator:
    def __init__(self, window_seconds: int):
        self.window_seconds = max(60, int(window_seconds))
        self._lock = threading.Lock()
        self._seen_at: dict[str, float] = {}

    def _fingerprint(self, text: str) -> str:
        normalized = _normalize_text(text)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def should_send(self, text: str) -> bool:
        if not getattr(config, "ENABLE_OUTGOING_DEDUP", True):
            return True

        now = time.time()
        key = self._fingerprint(text)
        if not key:
            return True

        with self._lock:
            threshold = now - self.window_seconds
            stale = [k for k, ts in self._seen_at.items() if ts < threshold]
            for item in stale:
                self._seen_at.pop(item, None)

            existing = self._seen_at.get(key)
            if existing and existing >= threshold:
                return False
            self._seen_at[key] = now
            return True

    def forget(self, text: str) -> None:
        key = self._fingerprint(text)
        with self._lock:
            self._seen_at.pop(key, None)


_dedupe = OutgoingDeduplicator(getattr(config, "DEDUPE_WINDOW_SECONDS", 10800))


def should_send_outgoing_text(text: str) -> bool:
    return _dedupe.should_send(text)


def forget_outgoing_text(text: str) -> None:
    _dedupe.forget(text)
