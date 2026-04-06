"""
Terminal colors, formatting helpers, async input.
"""

import asyncio
import re


def sanitize(text):
    """Strip ANSI/control characters to prevent terminal escape injection."""
    if not isinstance(text, str):
        return str(text)
    return re.sub(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]', '', text)


# ─── ANSI Colors ───

def c(text, code):
    return "\033[{}m{}\033[0m".format(code, text)

def green(t):   return c(t, "32")
def red(t):     return c(t, "31")
def yellow(t):  return c(t, "33")
def cyan(t):    return c(t, "36")
def magenta(t): return c(t, "35")
def bold(t):    return c(t, "1")
def dim(t):     return c(t, "2")
def white(t):   return c(t, "97")


def clear():
    print("\033[2J\033[H", end="")


def line(width=65):
    return dim("-" * width)


def dline(width=65):
    return dim("=" * width)


def header(title, width=65):
    """Print a boxed header."""
    pad = width - len(title) - 4
    left = pad // 2
    right = pad - left
    print()
    print(cyan("  +" + "-" * (width - 2) + "+"))
    print(cyan("  |") + " " * left + bold(title) + " " * right + cyan("|"))
    print(cyan("  +" + "-" * (width - 2) + "+"))
    print()


def section(title):
    print()
    print("  " + cyan("--- {} ---".format(title)))
    print()


async def ainput(prompt=""):
    return await asyncio.to_thread(input, prompt)


def phone_display(phone):
    """Show full phone number."""
    return phone if phone else "?"


def phone_masked(phone):
    if not phone or len(phone) <= 6:
        return phone or "?"
    return phone[:4] + "****" + phone[-3:]


def format_number(n):
    """Format large numbers: 1234 -> 1.2K, 1234567 -> 1.2M"""
    if n >= 1_000_000:
        return "{:.1f}M".format(n / 1_000_000)
    if n >= 1000:
        return "{:.1f}K".format(n / 1000)
    return str(n)
