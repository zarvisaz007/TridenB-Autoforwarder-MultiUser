/**
 * NetGuard — Network connectivity monitor for Ultimate Autoforwarder.
 *
 * Pings a reliable host every few seconds. When connectivity drops,
 * it attempts recovery by toggling Wi-Fi (macOS) and keeps retrying
 * until the network is back — even after 20+ hours of downtime.
 *
 * Exits cleanly when the parent process (main.py) dies (SIGTERM/SIGINT)
 * or when stdin closes (pipe from parent).
 */

const { execSync, exec } = require("child_process");
const dns = require("dns");
const os = require("os");

// ─── Config ───
const PING_INTERVAL_MS = 15_000;       // Check every 15s while online
const RETRY_INTERVAL_MS = 30_000;      // Retry every 30s while offline (avoids rapid process spawning)
const PING_HOSTS = ["1.1.1.1", "8.8.8.8"];
const PING_TIMEOUT_S = 4;
const MAX_FAILS_BEFORE_TOGGLE = 3;     // Toggle Wi-Fi after 3 consecutive failures

// ─── State ───
let consecutiveFails = 0;
let isOnline = true;
let totalReconnects = 0;
let lastOnlineTime = Date.now();
let timer = null;

// ─── Logging ───
function log(msg) {
    const ts = new Date().toLocaleTimeString("en-GB", { hour12: false });
    console.log(`[NetGuard ${ts}] ${msg}`);
}

// ─── Connectivity check ───
function ping(host) {
    return new Promise((resolve) => {
        const cmd =
            os.platform() === "win32"
                ? `ping -n 1 -w ${PING_TIMEOUT_S * 1000} ${host}`
                : `ping -c 1 -W ${PING_TIMEOUT_S} ${host}`;

        exec(cmd, { timeout: (PING_TIMEOUT_S + 2) * 1000 }, (err) => {
            resolve(!err);
        });
    });
}

function dnsCheck() {
    return new Promise((resolve) => {
        dns.resolve("telegram.org", (err) => resolve(!err));
    });
}

async function isConnected() {
    // Try pinging multiple hosts — any success = online
    for (const host of PING_HOSTS) {
        if (await ping(host)) return true;
    }
    // Fallback: DNS resolution
    if (await dnsCheck()) return true;
    return false;
}

// ─── macOS Wi-Fi toggle ───
function getWifiInterface() {
    try {
        const out = execSync("networksetup -listallhardwareports", {
            encoding: "utf8",
            timeout: 5000,
        });
        const match = out.match(
            /Hardware Port: Wi-Fi\nDevice: (\w+)/i
        );
        return match ? match[1] : "en0";
    } catch {
        return "en0";
    }
}

function toggleWifi() {
    if (os.platform() !== "darwin") {
        log("Non-macOS: skipping Wi-Fi toggle, waiting for network...");
        return;
    }

    const iface = getWifiInterface();
    log(`Toggling Wi-Fi (${iface}) OFF → ON ...`);
    try {
        execSync(`networksetup -setairportpower ${iface} off`, { timeout: 10000 });
    } catch { /* ignore */ }

    setTimeout(() => {
        try {
            execSync(`networksetup -setairportpower ${iface} on`, { timeout: 10000 });
            log("Wi-Fi turned back ON — waiting for connection...");
        } catch (e) {
            log(`Wi-Fi ON failed: ${e.message}`);
        }
    }, 3000);
}

// ─── Format duration ───
function formatDuration(ms) {
    const s = Math.floor(ms / 1000);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ${s % 60}s`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ${m % 60}m`;
    const d = Math.floor(h / 24);
    return `${d}d ${h % 24}h ${m % 60}m`;
}

// ─── Main loop ───
async function check() {
    const connected = await isConnected();

    if (connected) {
        if (!isOnline) {
            const downtime = formatDuration(Date.now() - lastOnlineTime);
            totalReconnects++;
            log(`✓ Back ONLINE after ${downtime} (reconnect #${totalReconnects})`);
            isOnline = true;
        }
        consecutiveFails = 0;
        lastOnlineTime = Date.now();
        scheduleNext(PING_INTERVAL_MS);
    } else {
        consecutiveFails++;

        if (isOnline) {
            log(`✗ Connection LOST — starting recovery (attempt ${consecutiveFails})`);
            isOnline = false;
        } else if (consecutiveFails % 4 === 0) {
            // Log every 4th attempt to avoid spamming logs
            const downtime = formatDuration(Date.now() - lastOnlineTime);
            log(`✗ Still offline — attempt ${consecutiveFails}, down for ${downtime}`);
        }

        // Toggle Wi-Fi after repeated failures
        if (consecutiveFails === MAX_FAILS_BEFORE_TOGGLE) {
            toggleWifi();
        }
        // Re-toggle periodically (every MAX_FAILS_BEFORE_TOGGLE*2 attempts)
        if (consecutiveFails > MAX_FAILS_BEFORE_TOGGLE &&
            consecutiveFails % (MAX_FAILS_BEFORE_TOGGLE * 2) === 0) {
            toggleWifi();
        }

        scheduleNext(RETRY_INTERVAL_MS);
    }
}

function scheduleNext(ms) {
    if (timer) clearTimeout(timer);
    timer = setTimeout(check, ms);
}

// ─── Graceful shutdown ───
function shutdown(reason) {
    log(`Shutting down (${reason})`);
    if (timer) clearTimeout(timer);
    process.exit(0);
}

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGHUP", () => shutdown("SIGHUP"));

// Parent process closed stdin pipe → main.py exited
process.stdin.on("end", () => shutdown("parent exited"));
process.stdin.on("error", () => shutdown("parent pipe broken"));
process.stdin.resume(); // Keep stdin open to detect parent exit

// ─── Start ───
log("Started — monitoring network connectivity");
check();
