"""
Text replacement engine — username swaps, word replacements, domain-aware URL
replacement, phone number mapping, and Telegram channel link rewriting.

Usage:
    from replacer import apply_replacements
    result = apply_replacements(text, replace_config)
    # result is modified text or None if nothing changed
"""

import re
from urllib.parse import urlparse


def apply_replacements(text, config):
    """Apply all configured replacements to text.

    Args:
        text: The message text to process.
        config: Dict with keys: enabled, usernames, words, urls, phones, channel_links.

    Returns:
        Modified text if any changes were made, None otherwise.
    """
    if not text or not config or not config.get("enabled"):
        return None

    original = text

    # 1. Channel links (t.me/old → t.me/new) — before generic URL handling
    channel_links = config.get("channel_links", {})
    for old_slug, new_slug in channel_links.items():
        pattern = re.compile(
            r'(https?://)?(t\.me|telegram\.me)/' + re.escape(old_slug) + r'\b',
            re.IGNORECASE
        )
        text = pattern.sub(f'https://t.me/{new_slug}', text)

    # 2. URL domain replacement
    url_config = config.get("urls", {})
    domain_map = url_config.get("domain_map", {})
    remove_unmatched = url_config.get("remove_unmatched", False)

    # Collect t.me domains that were already handled by channel_links
    tme_domains = {"t.me", "telegram.me"}

    if domain_map or remove_unmatched:
        def _replace_url(match):
            url = match.group(0)
            try:
                parsed = urlparse(url)
                netloc = parsed.netloc.lower()
                # Skip t.me links — already handled by channel_links step
                if channel_links and any(d in netloc for d in tme_domains):
                    return url
                # Check each domain_map key against the netloc
                for domain, replacement_url in domain_map.items():
                    if domain.lower() in netloc:
                        return replacement_url
                # No domain matched
                if remove_unmatched:
                    return ""
            except Exception:
                if remove_unmatched:
                    return ""
            return url

        text = re.sub(r'https?://\S+', _replace_url, text)

    # 3. Username replacement (@old → @new, case-insensitive)
    usernames = config.get("usernames", {})
    for old_name, new_name in usernames.items():
        old_clean = old_name.lstrip("@")
        new_clean = new_name.lstrip("@")
        pattern = re.compile(r'@' + re.escape(old_clean) + r'\b', re.IGNORECASE)
        text = pattern.sub(f'@{new_clean}', text)

    # 4. Phone replacement
    phones = config.get("phones", {})
    for old_phone, new_phone in phones.items():
        text = text.replace(old_phone, new_phone)

    # 5. Word/phrase replacement (case-sensitive)
    words = config.get("words", {})
    for old_word, new_word in words.items():
        text = text.replace(old_word, new_word)

    # Clean up multiple blank lines left by removals
    text = re.sub(r'\n{3,}', '\n\n', text).strip()

    if text != original:
        return text
    return None
