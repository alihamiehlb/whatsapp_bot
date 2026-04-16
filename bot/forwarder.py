# ============================================================
# bot/forwarder.py - WhatsApp Bot using Green API
# ============================================================
# Mirrors messages by re-sending them (sendMessage / sendFileByUrl / etc.)
# so they appear as normal outgoing messages from this account — not as
# WhatsApp "Forwarded" bubbles.

import re
import time
from collections import deque

import requests
import settings as config
from bot.dedupe import forget_outgoing_text, should_send_outgoing_text

_MAX_SEEN_IDS = 5000
_seen_order: deque[str] = deque()
_seen_set: set[str] = set()
_last_auth_error_log_at = 0.0

# ============================================================
# Helpers
# ============================================================

def _get_api_url(method: str) -> str:
    """Build a standard Green API endpoint URL."""
    if not config.INSTANCE_ID or not config.API_TOKEN:
        raise ValueError("INSTANCE_ID or API_TOKEN is missing in environment variables")
    base = getattr(config, "API_URL", "https://api.green-api.com").rstrip("/")
    return f"{base}/waInstance{config.INSTANCE_ID}/{method}/{config.API_TOKEN}"


def _mask_token(token: str) -> str:
    token = token or ""
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


def _normalize_chat_id(chat_id: str) -> str:
    """
    Some Green / WhatsApp payloads use a Cyrillic 'с' (U+0441) instead of Latin 'c'
    in @c.us / @g.us. That makes strict string compare fail against getChats ids.
    """
    if not chat_id:
        return ""
    s = chat_id.strip().replace("\u0441", "c").replace("\u0421", "C")
    return s


def _is_new_message(msg_id: str) -> bool:
    if not msg_id or msg_id in _seen_set:
        return False
    _seen_set.add(msg_id)
    _seen_order.append(msg_id)
    while len(_seen_order) > _MAX_SEEN_IDS:
        old = _seen_order.popleft()
        _seen_set.discard(old)
    return True


def _strip_urls(text: str) -> str:
    """Remove http(s) and www. URLs; collapse leftover whitespace."""
    if not text:
        return ""
    t = re.sub(r"https?://[^\s]+", "", text, flags=re.IGNORECASE)
    t = re.sub(r"\bwww\.[^\s]+", "", t, flags=re.IGNORECASE)
    t = re.sub(r" +", " ", t)
    t = re.sub(r"[ \t]*\n[ \t]*", "\n", t)
    return t.strip()


def _maybe_strip_links(text: str) -> str:
    if not getattr(config, "STRIP_LINKS_FROM_TEXT", True):
        return text
    return _strip_urls(text)


def format_outgoing_message(body: str) -> str:
    content = (body or "").strip()
    group_link = getattr(config, "GROUP_LINK_URL", "").strip()
    if (
        getattr(config, "APPEND_GROUP_LINK_TO_MESSAGES", True)
        and group_link
        and group_link not in content
    ):
        if content:
            content += f"\n\n🔗 {group_link}"
        else:
            content = f"🔗 {group_link}"
    return content.strip()


def _mime_to_ext(mime: str) -> str:
    if not mime:
        return ""
    root = mime.lower().split(";")[0].strip()
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
        "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/msword": ".doc",
    }.get(root, "")


def _default_file_name(msg_type: str, mime: str) -> str:
    ext = _mime_to_ext(mime)
    if ext:
        return f"mirror{ext}"
    if msg_type == "imageMessage":
        return "mirror.jpg"
    if msg_type == "videoMessage":
        return "mirror.mp4"
    if msg_type == "audioMessage":
        return "mirror.ogg"
    if msg_type == "documentMessage":
        return "mirror.bin"
    if msg_type == "stickerMessage":
        return "mirror.webp"
    return "mirror.bin"


# ============================================================
# 1. Finding Chat IDs
# ============================================================

def get_chats() -> list:
    url = _get_api_url("getChats")
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("chats", "dialogs"):
                inner = data.get(key)
                if isinstance(inner, list):
                    return inner
        return []
    except Exception as exc:
        print(f"  [API Error] getChats: {exc}")
        return []


def _chat_row_id(chat: dict) -> str:
    return str(chat.get("id") or chat.get("chatId") or "")


def get_group_id_by_name(group_name: str) -> str:
    if not group_name:
        return ""
    want = group_name.strip()
    for chat in get_chats():
        if not isinstance(chat, dict):
            continue
        name = chat.get("name")
        if name is None:
            continue
        if name == want or name.strip() == want:
            return _normalize_chat_id(_chat_row_id(chat))
    return ""


def _mirror_source_id_set(primary_src_id: str) -> set[str]:
    """All normalized source group ids that should be mirrored."""
    raw_ids: list[str] = []
    if primary_src_id:
        raw_ids.append(primary_src_id)
    for extra in getattr(config, "SOURCE_GROUP_CHAT_IDS", None) or []:
        if extra:
            raw_ids.append(extra)
    return {_normalize_chat_id(x) for x in raw_ids if x}


def _webhook_chat_id(body: dict) -> str:
    """Best-effort chat id from Green API webhook body."""
    sender = body.get("senderData") or {}
    cid = sender.get("chatId") or body.get("chatId") or ""
    return str(cid or "").strip()


def init_green_api():
    """Called on startup — returns (source_chat_id, dest_chat_id)."""
    print("\nConnecting to Green API to find groups...")
    print(f"  API URL: {config.API_URL}")
    print(f"  INSTANCE_ID: {config.INSTANCE_ID}")
    print(f"  API_TOKEN: {_mask_token(config.API_TOKEN)} (len={len(config.API_TOKEN)})")
    if getattr(config, "API_URL_HAD_WHITESPACE", False):
        print("  [WARNING] API_URL had leading/trailing whitespace; trimmed automatically.")
    if getattr(config, "INSTANCE_ID_HAD_WHITESPACE", False):
        print("  [WARNING] INSTANCE_ID had leading/trailing whitespace; trimmed automatically.")
    if getattr(config, "API_TOKEN_HAD_WHITESPACE", False):
        print("  [WARNING] API_TOKEN had leading/trailing whitespace/newline; trimmed automatically.")

    src_raw = getattr(config, "SOURCE_GROUP_CHAT_ID", "") or ""
    dst_raw = getattr(config, "DESTINATION_GROUP_CHAT_ID", "") or ""

    if src_raw.strip():
        src_id = _normalize_chat_id(src_raw.strip())
        print(f"  Source: using SOURCE_GROUP_CHAT_ID → {src_id}")
    else:
        src_id = get_group_id_by_name(config.SOURCE_GROUP_NAME)
        if src_id:
            print(f"  Source group found by name: {config.SOURCE_GROUP_NAME!r}")
        else:
            print(f"  [WARNING] Source group not found by name: {config.SOURCE_GROUP_NAME!r}")

    if dst_raw.strip():
        dest_id = _normalize_chat_id(dst_raw.strip())
        print(f"  Destination: using DESTINATION_GROUP_CHAT_ID → {dest_id}")
    else:
        dest_id = get_group_id_by_name(config.DESTINATION_GROUP_NAME)
        if dest_id:
            print(f"  Destination group found by name: {config.DESTINATION_GROUP_NAME!r}")
        else:
            print(f"  [WARNING] Destination group not found by name: {config.DESTINATION_GROUP_NAME!r}")

    if src_id:
        print(f"  Resolved source chat id:     {src_id}")
    extra_sources = getattr(config, "SOURCE_GROUP_CHAT_IDS", None) or []
    if extra_sources:
        print(f"  Extra mirror sources (SOURCE_GROUP_CHAT_IDS): {len(extra_sources)} id(s)")
    if dest_id:
        print(f"  Resolved destination chat id: {dest_id}")

    _validate_mirror_chats(src_id, dest_id)

    return src_id, dest_id


def _validate_mirror_chats(src_id: str, dest_id: str) -> None:
    """Resolve names from getChats and warn on common misconfiguration."""
    if not src_id or not dest_id:
        return
    ns = _normalize_chat_id(src_id)
    nd = _normalize_chat_id(dest_id)
    if ns == nd:
        print("  [ERROR] Source and destination chat ids are identical — fix env vars.")

    chats = get_chats()
    by_id: dict[str, str] = {}
    for c in chats:
        if not isinstance(c, dict):
            continue
        cid = _normalize_chat_id(_chat_row_id(c))
        if cid:
            by_id[cid] = str(c.get("name") or "")

    s_name = by_id.get(ns, "")
    d_name = by_id.get(nd, "")
    print(f"  Validate source:      {ns} → {s_name!r}" if s_name else f"  Validate source:      {ns} → (not listed in getChats)")
    print(f"  Validate destination: {nd} → {d_name!r}" if d_name else f"  Validate destination: {nd} → (not listed in getChats)")

    if nd.endswith("@c.us"):
        print("  [WARNING] Destination is @c.us (private chat). For a WhatsApp group use an id ending in @g.us.")


# ============================================================
# 2. Sending Messages & Media
# ============================================================

def send_file_by_url(chat_id: str, url_file: str, file_name: str, caption: str = "") -> bool:
    url = _get_api_url("sendFileByUrl")
    payload = {
        "chatId": chat_id,
        "urlFile": url_file,
        "fileName": file_name,
        "caption": caption or "",
    }
    try:
        r = requests.post(url, json=payload, timeout=180)
        r.raise_for_status()
        return True
    except Exception as exc:
        print(f"  [API Error] sendFileByUrl: {exc}")
        return False


def send_text_message(chat_id: str, text: str) -> bool:
    url = _get_api_url("sendMessage")
    payload = {"chatId": chat_id, "message": text}
    try:
        r = requests.post(url, json=payload, timeout=60)
        r.raise_for_status()
        return True
    except Exception as exc:
        print(f"  [API Error] sendMessage: {exc}")
        return False


def send_text_message_dedup(chat_id: str, text: str, source: str = "") -> bool | None:
    """Return True if sent, False if API error, None if skipped as duplicate."""
    payload = (text or "").strip()
    if not payload:
        return True
    if not getattr(config, "ENABLE_OUTGOING_DEDUP", True):
        return send_text_message(chat_id, payload)
    if not should_send_outgoing_text(payload):
        if source:
            print(f"  [Dedupe] skipped duplicate outgoing text from {source}.")
        else:
            print("  [Dedupe] skipped duplicate outgoing text.")
        return None
    ok = send_text_message(chat_id, payload)
    if not ok:
        forget_outgoing_text(payload)
    return ok


def send_location(
    chat_id: str,
    latitude: float,
    longitude: float,
    name_location: str = "",
    address: str = "",
) -> bool:
    url = _get_api_url("sendLocation")
    payload = {
        "chatId": chat_id,
        "latitude": latitude,
        "longitude": longitude,
        "nameLocation": name_location or "",
        "address": address or "",
    }
    try:
        r = requests.post(url, json=payload, timeout=30)
        r.raise_for_status()
        return True
    except Exception as exc:
        print(f"  [API Error] sendLocation: {exc}")
        return False


def send_contact_vcard(chat_id: str, display_name: str, vcard: str) -> bool:
    phone = ""
    m = re.search(r"waid=(\d+)", vcard or "")
    if m:
        phone = m.group(1)
    if not phone:
        m = re.search(r"(?:TEL|item\d+\.TEL)[^:]*:([+\d*#]+)", vcard or "", re.I)
        if m:
            phone = re.sub(r"\D", "", m.group(1))
    if not phone or len(phone) < 8:
        note = f"[Contact] {display_name}".strip() or "[Contact]"
        return send_text_message(chat_id, f"{note}\n\n{vcard}" if vcard else note)

    url = _get_api_url("sendContact")
    payload = {
        "chatId": chat_id,
        "contact": {
            "phoneContact": phone,
            "firstName": (display_name or "Contact")[:128],
        },
    }
    try:
        r = requests.post(url, json=payload, timeout=30)
        r.raise_for_status()
        return True
    except Exception as exc:
        print(f"  [API Error] sendContact: {exc}")
        return False


# ============================================================
# 3. Notification Queue  (instant delivery)
# ============================================================

def receive_notification() -> dict | None:
    """
    Pulls the next notification from Green API's queue.
    Returns the notification dict, or None if the queue is empty.
    """
    url = _get_api_url("receiveNotification")
    try:
        r = requests.get(url, timeout=25)
        if r.status_code == 401:
            global _last_auth_error_log_at
            now = time.time()
            if now - _last_auth_error_log_at >= 20:
                print("  [API Error] receiveNotification: 401 Unauthorized.")
                print("  [Hint] Verify API_URL / INSTANCE_ID / API_TOKEN and remove hidden spaces/newlines in env.")
                _last_auth_error_log_at = now
            return None
        r.raise_for_status()
        data = r.json()
        # Empty queue: API may return null, [], or {}
        if data is None or data == {} or data == []:
            return None
        if isinstance(data, dict) and data.get("receiptId") is None and not data.get("body"):
            return None
        return data
    except Exception as exc:
        print(f"  [API Error] receiveNotification: {exc}")
        return None


def delete_notification(receipt_id: int) -> bool:
    base = getattr(config, "API_URL", "https://api.green-api.com").rstrip("/")
    url = (
        f"{base}/waInstance{config.INSTANCE_ID}"
        f"/deleteNotification/{config.API_TOKEN}/{receipt_id}"
    )
    try:
        r = requests.delete(url, timeout=5)
        r.raise_for_status()
        return True
    except Exception as exc:
        print(f"  [API Error] deleteNotification: {exc}")
        return False


# ============================================================
# 4. Mirror by re-sending (no "Forwarded" label)
# ============================================================

def mirror_message_as_new(body: dict, dest_id: str) -> bool | None:
    md = body.get("messageData") or {}
    mt = md.get("typeMessage", "")

    if mt == "textMessage":
        raw = (md.get("textMessageData") or {}).get("textMessage", "")
        text = _maybe_strip_links(raw)
        if not text:
            return True  # only links / empty after strip — nothing to send
        return send_text_message_dedup(dest_id, format_outgoing_message(text), source="mirror:text")

    if mt == "extendedTextMessage":
        raw = (md.get("extendedTextMessageData") or {}).get("text", "")
        text = _maybe_strip_links(raw)
        if not text:
            return True
        return send_text_message_dedup(dest_id, format_outgoing_message(text), source="mirror:extended")

    file_data = md.get("fileMessageData")
    if not file_data and mt == "imageMessage":
        file_data = md.get("imageMessageData")

    if file_data:
        dl = file_data.get("downloadUrl") or ""
        if not dl:
            return False
        fname = file_data.get("fileName") or _default_file_name(mt, file_data.get("mimeType", ""))
        cap = _maybe_strip_links((file_data.get("caption") or "").strip())
        cap = format_outgoing_message(cap)
        return send_file_by_url(dest_id, dl, fname, cap)

    if mt == "locationMessage":
        loc = md.get("locationMessageData") or {}
        lat, lng = loc.get("latitude"), loc.get("longitude")
        if lat is None or lng is None:
            return False
        ok = send_location(
            dest_id,
            float(lat),
            float(lng),
            str(loc.get("nameLocation") or ""),
            str(loc.get("address") or ""),
        )
        if not ok:
            return False
        location_note = "📍 Shared location"
        return send_text_message_dedup(dest_id, format_outgoing_message(location_note), source="mirror:location")

    if mt == "contactMessage":
        c = md.get("contactMessageData") or {}
        ok = send_contact_vcard(dest_id, c.get("displayName") or "", c.get("vcard") or "")
        if not ok:
            return False
        name = (c.get("displayName") or "").strip()
        contact_note = f"👤 Contact shared: {name}" if name else "👤 Contact shared"
        return send_text_message_dedup(dest_id, format_outgoing_message(contact_note), source="mirror:contact")

    print(
        f"  [Mirror] Unsupported typeMessage={mt!r} — "
        "polls / buttons / some live types cannot be cloned as plain sends."
    )
    return False


# ============================================================
# 5. Processing a single notification
# ============================================================

# Green API puts *other people's* messages in incomingMessageReceived, but
# *your own* messages typed on the linked phone use outgoingMessageReceived.
# If you only handle "incoming", self-tests in the source group never mirror.
_MIRROR_WEBHOOKS = frozenset({"incomingMessageReceived", "outgoingMessageReceived"})


def process_notification(notification: dict, src_id: str, dest_id: str) -> None:
    body = notification.get("body", {})

    tw = body.get("typeWebhook")
    if tw not in _MIRROR_WEBHOOKS:
        return

    chat_id = _webhook_chat_id(body)
    allowed = _mirror_source_id_set(src_id)
    if not allowed:
        return
    if _normalize_chat_id(chat_id) not in allowed:
        return

    msg_id = body.get("idMessage", "")
    if not _is_new_message(msg_id):
        return

    md = body.get("messageData") or {}
    mt = md.get("typeMessage", "?")
    print(f"\n  *** Mirror as new send ({mt}) id={msg_id[:16]}… ***")

    outcome = mirror_message_as_new(body, dest_id)
    if outcome is True:
        print("  Sent OK.\n")
    elif outcome is False:
        print("  Send failed.\n")
    else:
        print("  Skipped (duplicate text vs recent schedule/mirror within window).\n")


# ============================================================
# 6. Main monitoring loop
# ============================================================

def monitor_loop(src_id: str, dest_id: str) -> None:
    print("\n" + "=" * 56)
    print("  Bot is running — mirror (re-send, not WhatsApp forward).")
    print("  In Green API console enable:")
    print("    • Incoming messages and files")
    print("    • Messages sent from phone  (needed if YOU send the test messages)")
    print("  Press Ctrl+C to stop.")
    print("=" * 56 + "\n")

    while True:
        try:
            notification = receive_notification()

            if notification is None:
                time.sleep(1)
                continue

            receipt_id = notification.get("receiptId")
            body = notification.get("body") or {}
            tw = body.get("typeWebhook", "")
            if getattr(config, "MIRROR_DEBUG", True) and tw in _MIRROR_WEBHOOKS:
                cid = _webhook_chat_id(body)
                allowed = _mirror_source_id_set(src_id)
                print(
                    f"  [debug] queue: {tw} chatId={cid!r} "
                    f"allowed_sources={len(allowed)} match={_normalize_chat_id(cid) in allowed}"
                )
            process_notification(notification, src_id, dest_id)

            if receipt_id is not None:
                delete_notification(receipt_id)

        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"\n  [monitor_loop] Unexpected error: {exc}")
            print("  Recovering — retrying in 3 s …\n")
            time.sleep(3)
