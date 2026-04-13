# ============================================================
# index.py — WhatsApp group mirror (Green API)
# ============================================================
# Run:  python index.py
#
# Fill environment variables with INSTANCE_ID, API_TOKEN, and exact group names.

import os
import sys
import threading

import settings as config
from bot.forwarder import init_green_api, monitor_loop, send_text_message_dedup
from bot.scheduled_messages import MessageSchedulerService, ScheduleStore
from web.panel import create_panel_app


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
    port = int(os.getenv("PORT", "8080"))
    try:
        app.run(host="0.0.0.0", port=port)
    except KeyboardInterrupt:
        print("\n\nStopped.")
    finally:
        print("Goodbye.")


if __name__ == "__main__":
    main()
