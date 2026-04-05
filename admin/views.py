"""
All CLI admin dashboard views.
"""

import time
import asyncio

import bot_forwarder
from bot_database import (
    get_all_users, get_all_tasks, get_all_statistics,
    get_tasks, get_statistics, update_task_status,
)
from admin.helpers import (
    clear, header, section, line, dline, ainput,
    green, red, yellow, cyan, magenta, bold, dim, white,
    phone_display, format_number,
)


# ═══════════════════════════════════════
# 1. Users Overview (interactive)
# ═══════════════════════════════════════

async def view_users():
    """List all users, then let admin drill into a specific user."""
    while True:
        clear()
        header("Users Overview")

        users = await get_all_users()
        all_tasks = await get_all_tasks()
        all_stats = await get_all_statistics()

        stats_by_user = {s["user_id"]: s for s in all_stats}
        tasks_by_user = {}
        for t in all_tasks:
            tasks_by_user.setdefault(t["user_id"], []).append(t)

        if not users:
            print("  {}".format(dim("No users yet.")))
            print()
            await ainput("  Press Enter to go back...")
            return

        # Numbered list
        print("  {:<4} {:<18} {:<18} {:<10} {:<8} {:<8} {:<10} {}".format(
            bold("#"), bold("User ID"), bold("Phone"),
            bold("Status"), bold("Client"), bold("Tasks"),
            bold("Msgs"), bold("Last Active")))
        print("  " + line(90))

        for idx, u in enumerate(users, 1):
            uid = str(u["id"])
            phone = phone_display(u.get("phone"))

            if u["auth_state"] == "CONNECTED":
                status = green("ONLINE")
            elif u["auth_state"] == "PENDING":
                status = yellow("PENDING")
            else:
                status = red("OFFLINE")

            client_on = green("YES") if u["id"] in bot_forwarder.user_clients else red("NO")

            user_tasks = tasks_by_user.get(u["id"], [])
            enabled = sum(1 for t in user_tasks if t["enabled"])
            task_str = "{}/{}".format(enabled, len(user_tasks))

            user_stat = stats_by_user.get(u["id"])
            msg_count = format_number(user_stat["total_messages"]) if user_stat else "0"

            last_active = u.get("last_active")
            la = time.strftime("%m-%d %H:%M", time.localtime(last_active)) if last_active else "Never"

            print("  {:<4} {:<18} {:<18} {:<10} {:<8} {:<8} {:<10} {}".format(
                bold(str(idx)), uid, phone, status, client_on, task_str, msg_count, la))

        print("  " + line(90))
        print()
        print("  Enter {} to view user details, or {} to go back".format(
            bold("user number (1,2,3...)"), bold("0")))
        print()

        try:
            choice = await ainput("  > ")
        except (EOFError, KeyboardInterrupt):
            return

        choice = choice.strip()
        if choice == "0" or choice == "":
            return

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(users):
                await view_user_detail(users[idx])
        except ValueError:
            pass


async def view_user_detail(user):
    """Drill-down view for a single user."""
    while True:
        clear()
        uid = user["id"]
        phone = phone_display(user.get("phone"))

        header("User: {} ({})".format(phone, uid))

        # ─── Basic Info ───
        if user["auth_state"] == "CONNECTED":
            status = green("ONLINE")
        elif user["auth_state"] == "PENDING":
            status = yellow("PENDING")
        else:
            status = red("OFFLINE")

        client = bot_forwarder.user_clients.get(uid)
        client_on = green("Active") if client and client.is_connected() else red("Inactive")

        created = time.strftime("%Y-%m-%d %H:%M", time.localtime(user["created_at"])) if user.get("created_at") else "?"
        last_active = time.strftime("%Y-%m-%d %H:%M", time.localtime(user["last_active"])) if user.get("last_active") else "Never"

        print("  {} {}    {} {}".format(bold("Status:"), status, bold("Client:"), client_on))
        print("  {} {}    {} {}".format(bold("Joined:"), created, bold("Last Active:"), last_active))
        print("  {} {}".format(bold("Phone:"), phone))

        # ─── Usage Stats ───
        section("Usage & Stats")

        stats = await get_statistics(uid)
        total_msgs = sum(s.get("total_messages", 0) for s in stats)
        today_msgs = sum(s.get("today_count", 0) for s in stats)
        week_msgs = sum(s.get("week_count", 0) for s in stats)
        total_imgs = sum(s.get("total_images", 0) for s in stats)

        print("  {} {}    {} {}    {} {}".format(
            bold("Total Msgs:"), green(str(total_msgs)),
            bold("Today:"), yellow(str(today_msgs)),
            bold("This Week:"), str(week_msgs)))
        print("  {} {}".format(bold("Images:"), str(total_imgs)))

        # ─── Tasks ───
        section("Tasks")

        user_tasks = await get_tasks(uid)
        if not user_tasks:
            print("  {}".format(dim("No tasks.")))
        else:
            print("  {:<5} {:<22} {:<18} {:<6} {}".format(
                bold("ID"), bold("Name"), bold("Source"), bold("Dests"), bold("Status")))
            print("  " + line(65))
            for t in user_tasks:
                parts = []
                if t["enabled"]:
                    parts.append(green("ON"))
                else:
                    parts.append(red("OFF"))
                if t["paused"]:
                    parts.append(yellow("PAUSED"))
                if t["filters"].get("rewrite_enabled"):
                    parts.append(cyan("AI"))
                dest_count = str(len(t.get("destination_channel_ids", [])))
                print("  {:<5} {:<22} {:<18} {:<6} {}".format(
                    t["id"], t["name"][:20], t["source_channel_id"], dest_count, " ".join(parts)))

        # ─── Channels ───
        section("Channels & Ownership")

        if client and client.is_connected():
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
                        cnt = entity.participants_count
                        members = format_number(cnt)

                    print("  {:<10} {:<30} {:<20} {} subs".format(
                        role, name[:28], str(full_id), members))
                    ch_count += 1
                    if ch_count >= 30:
                        print("  {}".format(dim("...and more")))
                        break
                if ch_count == 0:
                    print("  {}".format(dim("No channels.")))
            except Exception as e:
                print("  {} {}".format(red("Error:"), str(e)[:60]))
        else:
            print("  {}".format(dim("Client not connected — cannot fetch channels.")))

        # ─── Recent Logs ───
        section("Recent Logs")
        logs = bot_forwarder.get_user_logs(uid, 8)
        if logs:
            for entry in logs:
                print("  {}".format(dim(entry)))
        else:
            print("  {}".format(dim("No log entries.")))

        # ─── Actions ───
        print()
        print("  " + dline(50))
        print("  {}  Pause ALL tasks for this user".format(bold("P")))
        print("  {}  Resume ALL tasks for this user".format(bold("R")))
        print("  {}  Go back".format(bold("0")))
        print()

        try:
            choice = await ainput("  > ")
        except (EOFError, KeyboardInterrupt):
            return

        choice = choice.strip().upper()
        if choice == "0" or choice == "":
            return
        elif choice == "P":
            await _pause_all_user_tasks(uid, pause=True)
            print("\n  {}".format(yellow("All tasks PAUSED.")))
            await ainput("  Press Enter to continue...")
        elif choice == "R":
            await _pause_all_user_tasks(uid, pause=False)
            print("\n  {}".format(green("All tasks RESUMED.")))
            await ainput("  Press Enter to continue...")


async def _pause_all_user_tasks(user_id, pause=True):
    """Pause or resume all tasks for a user."""
    user_tasks = await get_tasks(user_id)
    for t in user_tasks:
        await update_task_status(t["id"], user_id, paused=pause)
        if pause:
            state = bot_forwarder.user_state.get(user_id, {})
            state.setdefault("paused_ids", set()).add(t["id"])
        else:
            bot_forwarder.clear_loop_counter(user_id, t["id"])
            state = bot_forwarder.user_state.get(user_id, {})
            state.get("paused_ids", set()).discard(t["id"])
    bot_forwarder.add_user_log(
        user_id,
        "[ADMIN] All tasks {}".format("PAUSED" if pause else "RESUMED"),
    )


# ═══════════════════════════════════════
# 2. All Tasks
# ═══════════════════════════════════════

async def view_tasks():
    clear()
    header("All Tasks")

    all_tasks = await get_all_tasks()

    if not all_tasks:
        print("  {}".format(dim("No tasks created yet.")))
    else:
        print("  {:<5} {:<14} {:<22} {:<18} {:<6} {}".format(
            bold("ID"), bold("User"), bold("Name"), bold("Source"), bold("Dests"), bold("Status")))
        print("  " + line(80))

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

            print("  {:<5} {:<14} {:<22} {:<18} {:<6} {}".format(
                t["id"], str(t["user_id"]), name, t["source_channel_id"], dest_count, " ".join(parts)))

        print("  " + line(80))

    print()
    print("  Total: {} tasks".format(len(all_tasks)))
    print()
    await ainput("  Press Enter to go back...")


# ═══════════════════════════════════════
# 3. Global Stats
# ═══════════════════════════════════════

async def view_stats():
    clear()
    header("Global Statistics")

    users = await get_all_users()
    all_stats = await get_all_statistics()
    stats_by_user = {s["user_id"]: s for s in all_stats}

    total_msgs = sum(s.get("total_messages", 0) for s in all_stats)
    total_today = sum(s.get("today_count", 0) for s in all_stats)
    total_imgs = sum(s.get("total_images", 0) for s in all_stats)
    active_clients = len(bot_forwarder.user_clients)

    print("  {} {}".format(bold("Total Messages:"), green(str(total_msgs))))
    print("  {} {}".format(bold("Today:"), yellow(str(total_today))))
    print("  {} {}".format(bold("Images Forwarded:"), str(total_imgs)))
    print("  {} {}".format(bold("Active Clients:"), green(str(active_clients)) if active_clients else red("0")))

    section("Per-User Breakdown")

    if not all_stats:
        print("  {}".format(dim("No message data yet.")))
    else:
        print("  {:<18} {:<14} {:<10} {:<10}".format(
            bold("Phone"), bold("Total"), bold("Today"), bold("Images")))
        print("  " + line(55))
        for u in users:
            stat = stats_by_user.get(u["id"])
            if not stat:
                continue
            phone = phone_display(u.get("phone"))
            print("  {:<18} {:<14} {:<10} {:<10}".format(
                phone,
                str(stat.get("total_messages", 0)),
                str(stat.get("today_count", 0)),
                str(stat.get("total_images", 0)),
            ))

    print()
    await ainput("  Press Enter to go back...")


# ═══════════════════════════════════════
# 4. User Channels
# ═══════════════════════════════════════

async def view_channels():
    clear()
    header("User Channels Overview")
    print("  {}".format(dim("Fetching channel data from active clients...")))

    users = await get_all_users()
    found_any = False

    for u in users:
        uid = u["id"]
        client = bot_forwarder.user_clients.get(uid)
        if not client or not client.is_connected():
            continue

        phone = phone_display(u.get("phone"))

        section("{} ({})".format(phone, uid))

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
                    members = format_number(entity.participants_count)

                print("  {:<10} {:<30} {:<20} {} subs".format(
                    role, name[:28], str(full_id), members))
                ch_count += 1
                found_any = True

                if ch_count >= 25:
                    print("  {}".format(dim("...and more")))
                    break

            if ch_count == 0:
                print("  {}".format(dim("No channels")))

        except Exception as e:
            print("  {} {}".format(red("Error:"), str(e)[:60]))

    if not found_any:
        print()
        print("  {}".format(dim("No active clients with channels.")))

    print()
    await ainput("  Press Enter to go back...")


# ═══════════════════════════════════════
# 5. Live Logs
# ═══════════════════════════════════════

async def view_logs():
    """Auto-refreshing logs. Ctrl+C to exit."""
    try:
        while True:
            clear()
            header("Live Logs")
            print("  {}".format(dim("Auto-refreshes every 3s. Press Ctrl+C to go back.")))
            print("  " + line(60))

            users = await get_all_users()
            any_logs = False

            for u in users:
                uid = u["id"]
                logs = bot_forwarder.get_user_logs(uid, 10)
                if not logs:
                    continue

                phone = phone_display(u.get("phone"))
                any_logs = True
                print()
                print("  {} {} ({})".format(bold("User:"), phone, uid))
                for entry in logs:
                    print("    {}".format(dim(entry)))

            if not any_logs:
                print()
                print("  {}".format(dim("No log entries yet.")))

            print()
            print("  " + line(60))
            print("  {}".format(dim("  Updated: " + time.strftime("%H:%M:%S"))))

            await asyncio.sleep(3)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass


# ═══════════════════════════════════════
# 6. Messages / Queries
# ═══════════════════════════════════════

async def view_queries(bot_instance):
    """View and reply to user queries from the terminal."""
    from bot_database import get_all_queries, mark_query_replied

    while True:
        clear()
        header("User Queries / Messages")

        queries = await get_all_queries()

        if not queries:
            print("  {}".format(dim("No queries yet.")))
            print()
            await ainput("  Press Enter to go back...")
            return

        # Show queries
        unreplied = [q for q in queries if not q.get("replied_at")]
        replied = [q for q in queries if q.get("replied_at")]

        if unreplied:
            print("  {} ({})".format(bold("NEW / UNREPLIED"), yellow(str(len(unreplied)))))
            print("  " + line(70))
            for q in unreplied:
                ts = time.strftime("%m-%d %H:%M", time.localtime(q["created_at"]))
                phone = phone_display(q.get("phone", "?"))
                print()
                print("  {}  {} from {} ({})".format(
                    yellow("[#{}]".format(q["id"])),
                    bold(ts),
                    bold(phone),
                    dim(str(q["user_id"])),
                ))
                # Wrap long messages
                msg = q["message"]
                for i in range(0, len(msg), 70):
                    print("    {}".format(msg[i:i+70]))
            print()

        if replied:
            print("  {} ({})".format(bold("REPLIED"), dim(str(len(replied)))))
            print("  " + line(70))
            for q in replied[-10:]:  # Show last 10 replied
                ts = time.strftime("%m-%d %H:%M", time.localtime(q["created_at"]))
                phone = phone_display(q.get("phone", "?"))
                print()
                print("  {}  {} from {} — {}".format(
                    green("[#{}]".format(q["id"])),
                    dim(ts),
                    phone,
                    green("replied"),
                ))
                msg = q["message"]
                print("    Q: {}".format(msg[:80]))
                if q.get("reply"):
                    print("    A: {}".format(q["reply"][:80]))

        print()
        print("  " + dline(50))
        print("  Enter {} to reply to a query".format(bold("query # (e.g. 3)")))
        print("  Enter {} to refresh, {} to go back".format(bold("R"), bold("0")))
        print()

        try:
            choice = await ainput("  > ")
        except (EOFError, KeyboardInterrupt):
            return

        choice = choice.strip().upper()
        if choice == "0" or choice == "":
            return
        elif choice == "R":
            continue

        # Reply to a query
        try:
            query_id = int(choice)
            target_q = None
            for q in queries:
                if q["id"] == query_id:
                    target_q = q
                    break

            if not target_q:
                print("  {}".format(red("Query not found.")))
                await ainput("  Press Enter...")
                continue

            print()
            print("  Replying to query #{} from {}:".format(
                query_id, phone_display(target_q.get("phone", "?"))))
            print("  {}".format(dim("Q: " + target_q["message"][:120])))
            print()

            try:
                reply_text = await ainput("  Your reply: ")
            except (EOFError, KeyboardInterrupt):
                continue

            reply_text = reply_text.strip()
            if not reply_text:
                continue

            # Save reply to DB
            await mark_query_replied(query_id, reply_text)

            # Send reply to user via bot
            if bot_instance:
                try:
                    await bot_instance.send_message(
                        target_q["user_id"],
                        "📩  *Reply from Admin:*\n\n{}".format(reply_text),
                        parse_mode="Markdown",
                    )
                    print("  {}".format(green("Reply sent!")))
                except Exception as e:
                    print("  {} Could not deliver to Telegram: {}".format(
                        yellow("Saved but"), str(e)[:60]))
            else:
                print("  {}".format(yellow("Reply saved. Bot not available to deliver.")))

            await ainput("  Press Enter...")

        except ValueError:
            pass


# ═══════════════════════════════════════
# 7. Pause Everything
# ═══════════════════════════════════════

async def pause_everything():
    """Pause ALL tasks for ALL users."""
    clear()
    header("Pause Everything")

    users = await get_all_users()
    all_tasks = await get_all_tasks()
    active_count = sum(1 for t in all_tasks if t["enabled"] and not t["paused"])

    print("  This will {} for all users.".format(red("PAUSE all {} active tasks".format(active_count))))
    print()

    try:
        confirm = await ainput("  Type {} to confirm, anything else to cancel: ".format(bold("YES")))
    except (EOFError, KeyboardInterrupt):
        return

    if confirm.strip() != "YES":
        print("  {}".format(dim("Cancelled.")))
        await ainput("  Press Enter...")
        return

    paused_count = 0
    for t in all_tasks:
        if t["enabled"] and not t["paused"]:
            await update_task_status(t["id"], t["user_id"], paused=True)
            state = bot_forwarder.user_state.get(t["user_id"], {})
            state.setdefault("paused_ids", set()).add(t["id"])
            paused_count += 1
    bot_forwarder.add_user_log(0, "[ADMIN] Global pause — {} tasks paused".format(paused_count))

    print()
    print("  {} {} tasks paused across all users.".format(yellow("Done!"), paused_count))
    await ainput("  Press Enter...")


async def resume_everything():
    """Resume ALL tasks for ALL users."""
    clear()
    header("Resume Everything")

    all_tasks = await get_all_tasks()
    paused_count = sum(1 for t in all_tasks if t["paused"])

    print("  This will {} for all users.".format(green("RESUME all {} paused tasks".format(paused_count))))
    print()

    try:
        confirm = await ainput("  Type {} to confirm, anything else to cancel: ".format(bold("YES")))
    except (EOFError, KeyboardInterrupt):
        return

    if confirm.strip() != "YES":
        print("  {}".format(dim("Cancelled.")))
        await ainput("  Press Enter...")
        return

    resumed_count = 0
    for t in all_tasks:
        if t["paused"]:
            await update_task_status(t["id"], t["user_id"], paused=False)
            bot_forwarder.clear_loop_counter(t["user_id"], t["id"])
            state = bot_forwarder.user_state.get(t["user_id"], {})
            state.get("paused_ids", set()).discard(t["id"])
            resumed_count += 1

    print()
    print("  {} {} tasks resumed.".format(green("Done!"), resumed_count))
    await ainput("  Press Enter...")
