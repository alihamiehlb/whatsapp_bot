# ============================================================
# index.py — WhatsApp group mirror (Green API)
# ============================================================
# Run:  python index.py
#
# Fill environment variables with INSTANCE_ID, API_TOKEN, and exact group names.

import os
import socket
import sys
import threading

import settings as config
from bot.forwarder import init_green_api, monitor_loop, send_text_message_dedup
from bot.scheduled_messages import MessageSchedulerService, ScheduleStore
from waitress import serve
from web.panel import create_panel_app


def _best_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _is_port_free(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _resolve_port() -> int:
    raw_port = os.getenv("PORT")
    if raw_port:
        return int(raw_port)

    preferred = 8080
    if _is_port_free(preferred):
        return preferred

    for port in range(8081, 8101):
        if _is_port_free(port):
            print(f"[WARNING] Port 8080 is busy, using {port} instead.")
            return port
    raise RuntimeError("No free port found in 8080-8100.")


def main():
    print("=" * 56)
    print("  WhatsApp group mirror + scheduler panel")
    print("=" * 56 + "\n")

    print("[1/3] Connecting to Green API …")
    try:
        src_id, dest_id = init_green_api()
        if not src_id or not dest_id:
            print("\nError: Could not find one or both groups.")
            print("Check API_URL / INSTANCE_ID / API_TOKEN and group names in environment variables.")
            sys.exit(1)
    except Exception as exc:
        print(f"\nFATAL: {exc}")
        sys.exit(1)

    print("[2/3] Starting mirror and scheduler workers …")
    store = ScheduleStore(config.SCHEDULE_DB_PATH)
    scheduler = MessageSchedulerService(store, dest_id, send_text_message_dedup)

    mirror_thread = threading.Thread(
        target=monitor_loop,
        args=(src_id, dest_id),
        name="mirror-loop",
        daemon=True,
    )
    scheduler_thread = threading.Thread(
        target=scheduler.run_forever,
        name="scheduler-loop",
        daemon=True,
    )
    mirror_thread.start()
    scheduler_thread.start()

    print("[3/3] Starting admin panel web server …\n")
    app = create_panel_app(store, dest_id, send_text_message_dedup)
    port = _resolve_port()
    lan_ip = _best_lan_ip()
    print(f"Panel local URL:  http://127.0.0.1:{port}/")
    print(f"Panel LAN URL:    http://{lan_ip}:{port}/")
    print("Serving panel with Waitress (production WSGI).\n")
    try:
        serve(app, host="0.0.0.0", port=port, threads=8)
    except KeyboardInterrupt:
        print("\n\nStopped.")
    finally:
        print("Goodbye.")


if __name__ == "__main__":
    main()
