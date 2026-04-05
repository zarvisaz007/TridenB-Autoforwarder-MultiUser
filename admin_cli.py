"""
TridenB Autoforwarder — Interactive CLI Admin Dashboard
Runs alongside the bot in the terminal.
"""

import time
import asyncio

import bot_forwarder
from bot_database import (
    get_all_users, get_all_tasks, get_all_statistics, get_all_connected_users,
)


# ─── Colors ───

def c(text, code):
    return "\033[{}m{}\033[0m".format(code, text)

def green(t):  return c(t, "32")
def red(t):    return c(t, "31")
def yellow(t): return c(t, "33")
def cyan(t):   return c(t, "36")
def bold(t):   return c(t, "1")
def dim(t):    return c(t, "2")
def magenta(t): return c(t, "35")


def clear_screen():
    print("\033[2J\033[H", end="")


def divider(width=60):
    return dim("─" * width)


# ─── Async input helper ───

async def ainput(prompt=""):
    return await asyncio.to_thread(input, prompt)


# ─── Main Menu ───

async def run_dashboard():
    """Main dashboard loop — runs until user exits."""
    while True:
        clear_screen()
        _print_header()
        await _print_summary()
        print()
        print("  {}  Users Overview".format(bold("1.")))
        print("  {}  All Tasks".format(bold("2.")))
        print("  {}  Global Stats".format(bold("3.")))
        print("  {}  User Channels".format(bold("4.")))
        print("  {}  Live Logs".format(bold("5.")))
        print("  {}  Refresh".format(bold("6.")))
        print("  {}  Exit Dashboard (bot keeps running)".format(bold("0.")))
        print()

        try:
            choice = await ainput("  > ")
        except (EOFError, KeyboardInterrupt):
            break

        choice = choice.strip()
        if choice == "1":
            await view_users()
        elif choice == "2":
            await view_tasks()
        elif choice == "3":
            await view_stats()
        elif choice == "4":
            await view_channels()
        elif choice == "5":
            await view_logs()
        elif choice == "6":
            continue
        elif choice == "0":
            print("\n  {} Dashboard closed. Bot is still running.".format(dim("*")))
            print("  {} Press Ctrl+C to stop the bot.\n".format(dim("*")))
            break


def _print_header():
    print()
    print(cyan("  ╔══════════════════════════════════════════════════════╗"))
    print(cyan("  ║       TridenB Autoforwarder — Admin Dashboard       ║"))
    print(cyan("  ║                  CLI Control Panel                   ║"))
    print(cyan("  ╚══════════════════════════════════════════════════════╝"))
    print()


async def _print_summary():
    users = await get_all_users()
    all_tasks = await get_all_tasks()
    connected = sum(1 for u in users if u["auth_state"] == "CONNECTED")
    pending = sum(1 for u in users if u["auth_state"] == "PENDING")
    active_clients = len(bot_forwarder.user_clients)
    enabled_tasks = sum(1 for t in all_tasks if t["enabled"])

    print("  {} {} connected, {} pending, {} total".format(
        bold("Users:"), green(str(connected)), yellow(str(pending)), dim(str(len(users)))))
    print("  {} {} active / {} total".format(
        bold("Tasks:"), green(str(enabled_tasks)), dim(str(len(all_tasks)))))
    print("  {} {}".format(
        bold("Clients:"), green(str(active_clients)) if active_clients else red("0")))
    print("  {} {}".format(bold("Time:"), dim(time.strftime("%Y-%m-%d %H:%M:%S"))))


# ─── View: Users ───

async def view_users():
    clear_screen()
    print()
    print(cyan("  ═══ Users Overview ═══"))
    print()

    users = await get_all_users()
    all_tasks = await get_all_tasks()
    all_stats = await get_all_statistics()

    stats_by_user = {s["user_id"]: s for s in all_stats}
    tasks_by_user = {}
    for t in all_tasks:
        tasks_by_user.setdefault(t["user_id"], []).append(t)

    if not users:
        print("  {}".format(dim("No users yet.")))
    else:
        # Header
        print("  {:<18} {:<16} {:<12} {:<10} {:<8} {:<12} {}".format(
            bold("User ID"), bold("Phone"), bold("Status"),
            bold("Client"), bold("Tasks"), bold("Messages"), bold("Last Active")))
        print("  " + divider(85))

        for u in users:
            uid = str(u["id"])
            phone = u.get("phone", "?")
            if len(phone) > 6:
                phone = phone[:4] + "****" + phone[-3:]

            if u["auth_state"] == "CONNECTED":
                status = green("CONNECTED")
            elif u["auth_state"] == "PENDING":
                status = yellow("PENDING")
            else:
                status = red("DISCONN")

            client_active = green("YES") if u["id"] in bot_forwarder.user_clients else red("NO")

            user_tasks = tasks_by_user.get(u["id"], [])
            enabled = sum(1 for t in user_tasks if t["enabled"])
            task_str = "{}/{}".format(enabled, len(user_tasks))

            user_stat = stats_by_user.get(u["id"])
            msg_count = str(user_stat["total_messages"]) if user_stat else "0"

            last_active = u.get("last_active")
            la = time.strftime("%m-%d %H:%M", time.localtime(last_active)) if last_active else "Never"

            print("  {:<18} {:<16} {:<12} {:<10} {:<8} {:<12} {}".format(
                uid, phone, status, client_active, task_str, msg_count, la))

        print("  " + divider(85))

    print()
    print("  Total: {} users".format(len(users)))
    print()
    await ainput("  Press Enter to go back...")


# ─── View: Tasks ───

async def view_tasks():
    clear_screen()
    print()
    print(cyan("  ═══ All Tasks ═══"))
    print()

    all_tasks = await get_all_tasks()

    if not all_tasks:
        print("  {}".format(dim("No tasks created yet.")))
    else:
        print("  {:<5} {:<14} {:<22} {:<18} {:<6} {}".format(
            bold("ID"), bold("User"), bold("Name"), bold("Source"), bold("Dests"), bold("Status")))
        print("  " + divider(80))

        for t in all_tasks:
            parts = []
            if t["enabled"]:
                parts.append(green("ON"))
            else:
                parts.append(red("OFF"))
            if t["paused"]:
                parts.append(yellow("PAUSED"))
            if t["filters"].get("rewrite_enabled"):
                parts.append(cyan("AI"))

            name = t["name"][:20]
            dest_count = str(len(t.get("destination_channel_ids", [])))
            status_str = " ".join(parts)

            print("  {:<5} {:<14} {:<22} {:<18} {:<6} {}".format(
                t["id"], str(t["user_id"]), name, t["source_channel_id"], dest_count, status_str))

        print("  " + divider(80))

    print()
    print("  Total: {} tasks".format(len(all_tasks)))
    print()
    await ainput("  Press Enter to go back...")


# ─── View: Stats ───

async def view_stats():
    clear_screen()
    print()
    print(cyan("  ═══ Global Statistics ═══"))
    print()

    users = await get_all_users()
    all_stats = await get_all_statistics()
    stats_by_user = {s["user_id"]: s for s in all_stats}

    total_msgs = sum(s.get("total_messages", 0) for s in all_stats)
    total_today = sum(s.get("today_count", 0) for s in all_stats)
    total_imgs = sum(s.get("total_images", 0) for s in all_stats)
    active_clients = len(bot_forwarder.user_clients)

    print("  {} {}".format(bold("Total Messages:"), green(str(total_msgs))))
    print("  {} {}".format(bold("Today:"), yellow(str(total_today))))
    print("  {} {}".format(bold("Images:"), str(total_imgs)))
    print("  {} {}".format(bold("Active Clients:"), green(str(active_clients))))
    print()
    print("  " + divider(50))
    print("  {}".format(bold("Per-User Breakdown:")))
    print("  " + divider(50))

    for u in users:
        stat = stats_by_user.get(u["id"])
        if not stat:
            continue
        phone = u.get("phone", "?")
        if len(phone) > 6:
            phone = phone[:4] + "****" + phone[-3:]
        print("  {} — {} msgs ({} today)".format(
            phone,
            stat.get("total_messages", 0),
            stat.get("today_count", 0),
        ))

    if not all_stats:
        print("  {}".format(dim("No message data yet.")))

    print()
    await ainput("  Press Enter to go back...")


# ─── View: Channels ───

async def view_channels():
    clear_screen()
    print()
    print(cyan("  ═══ User Channels ═══"))
    print()
    print("  {}".format(dim("Fetching channel data from active clients...")))

    users = await get_all_users()
    found_any = False

    for u in users:
        uid = u["id"]
        client = bot_forwarder.user_clients.get(uid)
        if not client or not client.is_connected():
            continue

        phone = u.get("phone", "?")
        if len(phone) > 6:
            phone = phone[:4] + "****" + phone[-3:]

        print()
        print("  {} {} ({})".format(bold("User:"), phone, uid))
        print("  " + divider(60))

        try:
            ch_count = 0
            async for dialog in client.iter_dialogs():
                if not dialog.is_channel:
                    continue

                entity = dialog.entity
                name = dialog.name or "(no name)"
                full_id = int("-100{}".format(entity.id))

                role = "Member"
                if hasattr(entity, "creator") and entity.creator:
                    role = magenta("Owner")
                elif hasattr(entity, "admin_rights") and entity.admin_rights:
                    role = cyan("Admin")

                members = "?"
                if hasattr(entity, "participants_count") and entity.participants_count:
                    count = entity.participants_count
                    if count >= 1000:
                        members = "{:.1f}K".format(count / 1000)
                    else:
                        members = str(count)

                print("    {:<8} {:<30} {:<20} {} subs".format(
                    role, name[:28], str(full_id), members))
                ch_count += 1
                found_any = True

                if ch_count >= 25:
                    print("    {}".format(dim("...and more")))
                    break

            if ch_count == 0:
                print("    {}".format(dim("No channels")))

        except Exception as e:
            print("    {} {}".format(red("Error:"), str(e)[:60]))

    if not found_any:
        print()
        print("  {}".format(dim("No active clients with channels.")))

    print()
    await ainput("  Press Enter to go back...")


# ─── View: Logs ───

async def view_logs():
    """Show live logs with auto-refresh."""
    print()
    print(cyan("  ═══ Live Logs ═══"))
    print("  {}".format(dim("Auto-refreshes every 3 seconds. Press Ctrl+C to go back.")))
    print()

    try:
        while True:
            clear_screen()
            print()
            print(cyan("  ═══ Live Logs ═══"))
            print("  {}".format(dim("Press Ctrl+C to go back.")))
            print("  " + divider(60))

            users = await get_all_users()
            any_logs = False

            for u in users:
                uid = u["id"]
                logs = bot_forwarder.get_user_logs(uid, 10)
                if not logs:
                    continue

                phone = u.get("phone", "?")
                if len(phone) > 6:
                    phone = phone[:4] + "****" + phone[-3:]

                any_logs = True
                print()
                print("  {} {} ({})".format(bold("User:"), phone, uid))
                for entry in logs:
                    print("    {}".format(dim(entry)))

            if not any_logs:
                print()
                print("  {}".format(dim("No log entries yet.")))

            print()
            print("  " + divider(60))
            print("  {}".format(dim(time.strftime("  Updated: %H:%M:%S"))))

            await asyncio.sleep(3)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
