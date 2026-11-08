"""Είναι ξεπερασμένη η κύρια σελίδα; (για το live workflow: αν ναι, ξεκινά το «BetBot daily»)

Το GitHub καθυστερεί ή χάνει τα προγραμματισμένα workflows. Το live workflow τρέχει πολύ πιο συχνά, οπότε σε κάθε εκτέλεση ρωτά:
«έτρεξε σήμερα το daily;». Αν όχι, το ξεκινά ο ίδιος (workflow_dispatch). Έτσι αρκεί να τρέξει ΕΝΑ από τα πολλά προγραμματισμένα.

Ξεπερασμένη (exit 1) όταν, μετά τις 06:05 ώρα Ελλάδας:
  - δεν υπάρχει docs/last_run.json, ή
  - η τελευταία εκτέλεση του bot ήταν άλλη μέρα (ώρα Ελλάδας), ή
  - έχουν περάσει πάνω από 10 ώρες και δεν είναι αργά το βράδυ (πριν τις 23:00).
Φρέσκια: exit 0. Χρήση: python -m betbot.freshness [διαδρομή last_run.json]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Athens")


def is_stale(last_iso: str | None, now: datetime) -> tuple[bool, str]:
    local = now.astimezone(TZ)
    if local.hour * 60 + local.minute < 6 * 60 + 5:
        return False, "πριν τις 06:05: δεν περιμένουμε νέα σελίδα"
    if not last_iso:
        return True, "δεν υπάρχει καταγραφή τελευταίας εκτέλεσης"
    last = datetime.fromisoformat(last_iso.replace("Z", "+00:00"))
    if last.astimezone(TZ).date() != local.date():
        return True, f"τελευταία εκτέλεση {last.astimezone(TZ):%d/%m %H:%M} (άλλη μέρα)"
    age = now - last
    if age > timedelta(hours=10) and local.hour < 23:
        return True, f"τελευταία εκτέλεση πριν από {age.total_seconds() / 3600:.0f} ώρες"
    return False, f"τελευταία εκτέλεση {last.astimezone(TZ):%H:%M} (φρέσκια)"


def main(argv=None) -> int:
    path = (argv or sys.argv[1:] or ["docs/last_run.json"])[0]
    try:
        with open(path, encoding="utf-8") as f:
            last = json.load(f).get("generated")
    except (OSError, ValueError):
        last = None
    stale, why = is_stale(last, datetime.now(timezone.utc))
    print(("ΞΕΠΕΡΑΣΜΕΝΗ: " if stale else "ΦΡΕΣΚΙΑ: ") + why)
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
