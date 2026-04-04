import json
import os
import time
import asyncio
from .config import REPORT_CONFIG
from .engine import generate_report


def _load_schedules():
    path = REPORT_CONFIG["schedules_file"]
    if not os.path.exists(path):
        return {"schedules": []}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"schedules": []}


def _save_schedules(data):
    path = REPORT_CONFIG["schedules_file"]
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _next_schedule_id(data):
    schedules = data.get("schedules", [])
    if not schedules:
        return 1
    return max(s["id"] for s in schedules) + 1


def _compute_next_run(schedule):
    """Compute the next run timestamp based on frequency and time_of_day."""
    now = time.time()
    tod_parts = schedule.get("time_of_day", "08:00").split(":")
    hour = int(tod_parts[0])
    minute = int(tod_parts[1]) if len(tod_parts) > 1 else 0

    # Start of today
    lt = time.localtime(now)
    today_start = time.mktime(time.struct_time((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, lt.tm_isdst)))
    target_today = today_start + hour * 3600 + minute * 60

    freq = schedule.get("frequency", "daily")
    if freq == "daily":
        if target_today > now:
            return int(target_today)
        return int(target_today + 86400)
    elif freq == "weekly":
        day_of_week = schedule.get("day_of_week", 0)  # 0=Monday
        days_ahead = day_of_week - lt.tm_wday
        if days_ahead < 0 or (days_ahead == 0 and target_today <= now):
            days_ahead += 7
        return int(target_today + days_ahead * 86400)
    elif freq == "monthly":
        day_of_month = schedule.get("day_of_month", 1)
        import calendar
        year, month = lt.tm_year, lt.tm_mon
        if lt.tm_mday > day_of_month or (lt.tm_mday == day_of_month and target_today <= now):
            month += 1
            if month > 12:
                month = 1
                year += 1
        max_day = calendar.monthrange(year, month)[1]
        actual_day = min(day_of_month, max_day)
        next_start = time.mktime(time.struct_time((year, month, actual_day, 0, 0, 0, 0, 0, lt.tm_isdst)))
        return int(next_start + hour * 3600 + minute * 60)

    return int(now + 86400)


def create_schedule(source_channel_id, channel_name, frequency, time_of_day,
                    report_type="summary", custom_prompt=None,
                    day_of_week=None, day_of_month=None, lookback_days=None):
    """Create a new recurring report schedule."""
    data = _load_schedules()

    lookback_map = {"daily": 1, "weekly": 7, "monthly": 30}
    if lookback_days is None:
        lookback_days = lookback_map.get(frequency, 1)

    schedule = {
        "id": _next_schedule_id(data),
        "source_channel_id": source_channel_id,
        "channel_name": channel_name,
        "frequency": frequency,
        "time_of_day": time_of_day,
        "report_type": report_type,
        "custom_prompt": custom_prompt,
        "lookback_days": lookback_days,
        "enabled": True,
        "last_run": None,
        "next_run": None,
        "created_at": int(time.time()),
    }

    if frequency == "weekly" and day_of_week is not None:
        schedule["day_of_week"] = day_of_week
    if frequency == "monthly" and day_of_month is not None:
        schedule["day_of_month"] = day_of_month

    schedule["next_run"] = _compute_next_run(schedule)

    data["schedules"].append(schedule)
    _save_schedules(data)
    return schedule


def list_schedules():
    """Return all schedules."""
    return _load_schedules().get("schedules", [])


def delete_schedule(schedule_id):
    """Delete a schedule by ID."""
    data = _load_schedules()
    data["schedules"] = [s for s in data["schedules"] if s["id"] != schedule_id]
    _save_schedules(data)


def toggle_schedule(schedule_id):
    """Toggle a schedule's enabled state."""
    data = _load_schedules()
    for s in data["schedules"]:
        if s["id"] == schedule_id:
            s["enabled"] = not s["enabled"]
            if s["enabled"]:
                s["next_run"] = _compute_next_run(s)
            _save_schedules(data)
            return s
    return None


class ReportScheduler:
    """Background scheduler that checks and runs due reports."""

    def __init__(self, db, log_fn=None):
        self.db = db
        self.log_fn = log_fn or print
        self._task = None
        self._running = False
        self._last_reports = {}  # schedule_id -> last report text

    def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        self.log_fn("[REPORTS] Scheduler started")

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        self.log_fn("[REPORTS] Scheduler stopped")

    def get_last_report(self, schedule_id):
        return self._last_reports.get(schedule_id)

    async def _loop(self):
        while self._running:
            try:
                await self._check_due()
            except Exception as e:
                self.log_fn(f"[REPORTS ERR] {e}")
            await asyncio.sleep(60)  # check every minute

    async def _check_due(self):
        now = int(time.time())
        data = _load_schedules()
        changed = False

        for schedule in data.get("schedules", []):
            if not schedule.get("enabled"):
                continue
            next_run = schedule.get("next_run")
            if next_run and next_run <= now:
                await self._run_report(schedule)
                schedule["last_run"] = now
                schedule["next_run"] = _compute_next_run(schedule)
                changed = True

        if changed:
            _save_schedules(data)

    async def _run_report(self, schedule):
        self.log_fn(f"[REPORTS] Running scheduled report '{schedule.get('channel_name', '?')}' ({schedule['frequency']})")

        lookback = schedule.get("lookback_days", 1)
        now = int(time.time())
        start_ts = now - (lookback * 86400)

        messages = await asyncio.to_thread(
            self.db.get_messages_by_date_range,
            schedule["source_channel_id"], start_ts, now
        )

        if not messages:
            self.log_fn(f"[REPORTS] No messages found for last {lookback} day(s)")
            return

        report_type = schedule.get("report_type", "summary")
        custom_prompt = schedule.get("custom_prompt")

        def progress(msg):
            self.log_fn(f"[REPORTS] {msg}")

        report = await generate_report(
            messages,
            report_type=report_type,
            custom_prompt=custom_prompt,
            progress_cb=progress
        )

        self._last_reports[schedule["id"]] = {
            "text": report,
            "generated_at": int(time.time()),
            "message_count": len(messages),
        }

        self.log_fn(f"[REPORTS] Report ready for '{schedule.get('channel_name', '?')}' ({len(messages)} msgs analyzed)")
