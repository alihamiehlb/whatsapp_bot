# ============================================================
# bot/forwarder.py - WhatsApp Bot using Green API
# ============================================================
# Uses the receiveNotification / deleteNotification queue so
# messages are forwarded instantly the moment they arrive —
# no fixed polling delay.

import time
import requests
import config

# Prevent duplicate forwards if the same message somehow appears twice.
_seen_message_ids = set()

# ============================================================
# Helpers
# ============================================================

def _get_api_url(method: str) -> str:
    """Build a standard Green API endpoint URL."""
    if not config.INSTANCE_ID or not config.API_TOKEN:
        raise ValueError("INSTANCE_ID or API_TOKEN is missing in config.py")
    base = getattr(config, "API_URL", "https://api.green-api.com").rstrip("/")
    return f"{base}/waInstance{config.INSTANCE_ID}/{method}/{config.API_TOKEN}"

# ============================================================
# 1. Finding Chat IDs
# ============================================================

def get_chats() -> list:
    url = _get_api_url("getChats")
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        print(f"  [API Error] getChats: {exc}")
        return []

def get_group_id_by_name(group_name: str) -> str:
    if not group_name:
        return ""
    for chat in get_chats():
        if chat.get("name") == group_name:
            return chat.get("id", "")
    return ""

def init_green_api():
    """Called on startup — returns (source_chat_id, dest_chat_id)."""
    print("\nConnecting to Green API to find groups...")
    src_id  = get_group_id_by_name(config.SOURCE_GROUP_NAME)
    dest_id = get_group_id_by_name(config.DESTINATION_GROUP_NAME)

    if not src_id:
        print(f"  [WARNING] Source group not found: {config.SOURCE_GROUP_NAME}")
    else:
        print(f"  Source group found:      {config.SOURCE_GROUP_NAME}")

    if not dest_id:
        print(f"  [WARNING] Destination group not found: {config.DESTINATION_GROUP_NAME}")
    else:
        print(f"  Destination group found: {config.DESTINATION_GROUP_NAME}")

    return src_id, dest_id

# ============================================================
# 2. Sending Messages & Media
# ============================================================

def send_image(chat_id: str, url_file: str, caption: str = "") -> bool:
    url = _get_api_url("sendFileByUrl")
    payload = {
        "chatId":   chat_id,
        "urlFile":  url_file,
        "fileName": "prayer_times.jpg",
        "caption":  caption,
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
        return True
    except Exception as exc:
        print(f"  [API Error] sendFileByUrl: {exc}")
        return False

def send_text_message(chat_id: str, text: str) -> bool:
    url = _get_api_url("sendMessage")
    payload = {"chatId": chat_id, "message": text}
    try:
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
        return True
    except Exception as exc:
        print(f"  [API Error] sendMessage: {exc}")
        return False

# ============================================================
# 3. Notification Queue  (instant delivery)
# ============================================================

def receive_notification() -> dict | None:
    """
    Pulls the next notification from Green API's queue.
    Returns the notification dict, or None if the queue is empty.

    Green API uses long-polling: it holds the connection open for up to 20 s
    while waiting for a queued message, then returns null when the queue is
    empty.  The timeout must exceed that window or every idle poll times out.
    """
    url = _get_api_url("receiveNotification")
    try:
        r = requests.get(url, timeout=25)
        r.raise_for_status()
        data = r.json()
        # Green API returns null / empty body when the queue is empty
        if not data:
            return None
        return data
    except Exception as exc:
        print(f"  [API Error] receiveNotification: {exc}")
        return None

def delete_notification(receipt_id: int) -> bool:
    """
    Acknowledges and removes a notification from the queue.
    Must be called after every received notification, even ones we ignore.
    """
    base = getattr(config, "API_URL", "https://api.green-api.com").rstrip("/")
    url  = (f"{base}/waInstance{config.INSTANCE_ID}"
            f"/deleteNotification/{config.API_TOKEN}/{receipt_id}")
    try:
        r = requests.delete(url, timeout=5)
        r.raise_for_status()
        return True
    except Exception as exc:
        print(f"  [API Error] deleteNotification: {exc}")
        return False

# ============================================================
# 4. Processing a single notification
# ============================================================

def process_notification(notification: dict, src_id: str, dest_id: str) -> None:
    """
    Inspects one notification from the queue.
    If it is a prayer-times message from the source group, forwards it instantly.
    """
    body = notification.get("body", {})

    # We only care about incoming messages
    if body.get("typeWebhook") != "incomingMessageReceived":
        return

    # Must come from the source group
    chat_id = body.get("senderData", {}).get("chatId", "")
    if chat_id != src_id:
        return

    msg_id = body.get("idMessage", "")
    if msg_id in _seen_message_ids:
        return
    _seen_message_ids.add(msg_id)

    # ── Extract text & optional image URL ──────────────────
    message_data = body.get("messageData", {})
    msg_type     = message_data.get("typeMessage", "")
    text         = ""
    download_url = ""

    if msg_type == "textMessage":
        text = message_data.get("textMessageData", {}).get("textMessage", "")

    elif msg_type == "extendedTextMessage":
        text = message_data.get("extendedTextMessageData", {}).get("text", "")

    elif msg_type == "imageMessage":
        img = message_data.get("imageMessageData", {})
        text         = img.get("caption", "")
        download_url = img.get("downloadUrl", "")

    # ── Check for keyword ───────────────────────────────────
    if config.PRAYER_KEYWORD not in text:
        return

    print(f"\n  *** PRAYER TIMES DETECTED (ID: {msg_id}) — forwarding now! ***")

    ok = True

    if msg_type == "imageMessage" and download_url:
        print("  Step 1/2: Sending image …")
        if not send_image(dest_id, download_url):
            ok = False
    else:
        print("  Step 1/2: No image — skipping.")

    if text:
        print("  Step 2/2: Sending text …")
        if not send_text_message(dest_id, text):
            ok = False
    else:
        print("  Step 2/2: No text — skipping.")

    print("  Forward complete!\n" if ok else "  Forward finished with errors.\n")

# ============================================================
# 5. Main monitoring loop
# ============================================================

def monitor_loop(src_id: str, dest_id: str) -> None:
    """
    Continuously drains Green API's notification queue.
    When the queue is empty it waits 1 second before trying again,
    so messages are forwarded within ~1 second of arrival.
    """
    print("\n" + "=" * 56)
    print("  Bot is running — instant forwarding enabled.")
    print("  Listening via Green API notification queue.")
    print("  Press Ctrl+C to stop.")
    print("=" * 56 + "\n")

    while True:
        try:
            notification = receive_notification()

            if notification is None:
                # Queue was empty — the long-poll already held for ~20 s,
                # so no extra sleep is needed before the next call.
                continue

            receipt_id = notification.get("receiptId")

            # Process before deleting so we never silently lose a message
            process_notification(notification, src_id, dest_id)

            if receipt_id is not None:
                delete_notification(receipt_id)

        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"\n  [monitor_loop] Unexpected error: {exc}")
            print("  Recovering — retrying in 3 s …\n")
            time.sleep(3)
