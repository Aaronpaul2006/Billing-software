"""Device names for people, from a browser's user agent (as web/src/features/account/devices.ts)."""

import re


def describe_device(user_agent: str | None, label: str | None = None) -> str:
    """ "Chrome on Windows"; the label a device gave itself wins."""
    if label:
        return label
    if not user_agent:
        return "Unknown device"
    ua = user_agent
    browsers = (
        (r"Edg/", "Edge"),
        (r"OPR/", "Opera"),
        (r"Chrome/", "Chrome"),
        (r"Firefox/", "Firefox"),
        (r"Safari/", "Safari"),
        (r"(?i)okhttp|Dart|Expo|CFNetwork", "App"),
    )
    browser = next((name for pattern, name in browsers if re.search(pattern, ua)), "Browser")
    # Order matters: Android says Linux, iPhone says "like Mac OS X".
    systems = (
        (r"Android", "Android"),
        (r"iPhone|iPad|iOS", "iPhone"),
        (r"Windows", "Windows"),
        (r"Mac OS X|Macintosh", "Mac"),
        (r"Linux", "Linux"),
    )
    system = next((name for pattern, name in systems if re.search(pattern, ua)), None)
    return f"{browser} on {system}" if system else browser
