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
import config

_MAX_SEEN_IDS = 5000
_seen_order: deque[str] = deque()
_seen_set: set[str] = set()

# ============================================================
# Helpers
# ============================================================

def _get_api_url(method: str) -> str:
    """Build a standard Green API endpoint URL."""
    if not config.INSTANCE_ID or not config.API_TOKEN:
        raise ValueError("INSTANCE_ID or API_TOKEN is missing in config.py")
    base = getattr(config, "API_URL", "https://api.green-api.com").rstrip("/")
    return f"{base}/waInstance{config.INSTANCE_ID}/{method}/{config.API_TOKEN}"


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


def init_green_api():
    """Called on startup — returns (source_chat_id, dest_chat_id)."""
    print("\nConnecting to Green API to find groups...")

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
    if dest_id:
        print(f"  Resolved destination chat id: {dest_id}")

    return src_id, dest_id


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

def mirror_message_as_new(body: dict, dest_id: str) -> bool:
    md = body.get("messageData") or {}
    mt = md.get("typeMessage", "")

    if mt == "textMessage":
        raw = (md.get("textMessageData") or {}).get("textMessage", "")
        text = _maybe_strip_links(raw)
        if not text:
            return True  # only links / empty after strip — nothing to send
        return send_text_message(dest_id, text)

    if mt == "extendedTextMessage":
        raw = (md.get("extendedTextMessageData") or {}).get("text", "")
        text = _maybe_strip_links(raw)
        if not text:
            return True
        return send_text_message(dest_id, text)

    file_data = md.get("fileMessageData")
    if not file_data and mt == "imageMessage":
        file_data = md.get("imageMessageData")

    if file_data:
        dl = file_data.get("downloadUrl") or ""
        if not dl:
            return False
        fname = file_data.get("fileName") or _default_file_name(mt, file_data.get("mimeType", ""))
        cap = _maybe_strip_links((file_data.get("caption") or "").strip())
        return send_file_by_url(dest_id, dl, fname, cap)

    if mt == "locationMessage":
        loc = md.get("locationMessageData") or {}
        lat, lng = loc.get("latitude"), loc.get("longitude")
        if lat is None or lng is None:
            return False
        return send_location(
            dest_id,
            float(lat),
            float(lng),
            str(loc.get("nameLocation") or ""),
            str(loc.get("address") or ""),
        )

    if mt == "contactMessage":
        c = md.get("contactMessageData") or {}
        return send_contact_vcard(dest_id, c.get("displayName") or "", c.get("vcard") or "")

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

    chat_id = body.get("senderData", {}).get("chatId", "")
    if _normalize_chat_id(chat_id) != _normalize_chat_id(src_id):
        return

    msg_id = body.get("idMessage", "")
    if not _is_new_message(msg_id):
        return

    md = body.get("messageData") or {}
    mt = md.get("typeMessage", "?")
    print(f"\n  *** Mirror as new send ({mt}) id={msg_id[:16]}… ***")

    if mirror_message_as_new(body, dest_id):
        print("  Sent OK.\n")
    else:
        print("  Send failed.\n")


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
                continue

            receipt_id = notification.get("receiptId")
            body = notification.get("body") or {}
            tw = body.get("typeWebhook", "")
            if getattr(config, "MIRROR_DEBUG", True) and tw in _MIRROR_WEBHOOKS:
                cid = (body.get("senderData") or {}).get("chatId", "")
                print(
                    f"  [debug] queue: {tw} chatId={cid!r} "
                    f"source={src_id!r} match={_normalize_chat_id(cid) == _normalize_chat_id(src_id)}"
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
