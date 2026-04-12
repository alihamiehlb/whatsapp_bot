# ============================================================
# index.py — WhatsApp group mirror (Green API)
# ============================================================
# Run:  python index.py
#
# Fill config.py with INSTANCE_ID, API_TOKEN, and exact group names.

import sys

from bot.forwarder import init_green_api, monitor_loop


def main():
    print("=" * 56)
    print("  WhatsApp group mirror")
    print("=" * 56 + "\n")

    print("[1/2] Connecting to Green API …")
    try:
        src_id, dest_id = init_green_api()
        if not src_id or not dest_id:
            print("\nError: Could not find one or both groups.")
            print("Check API_URL / INSTANCE_ID / API_TOKEN and group names in config.py.")
            sys.exit(1)
    except Exception as exc:
        print(f"\nFATAL: {exc}")
        sys.exit(1)

    print("[2/2] Listening for messages (Ctrl+C to stop) …\n")
    try:
        monitor_loop(src_id, dest_id)
    except KeyboardInterrupt:
        print("\n\nStopped.")
    finally:
        print("Goodbye.")


if __name__ == "__main__":
    main()
