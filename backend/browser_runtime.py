import os


def env_flag(name: str, default: bool = False) -> bool:
    """Parse boolean environment flags consistently across scrapers."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def fb_headless(default: bool = True) -> bool:
    """Scraping should run in the background by default."""
    return env_flag("FB_HEADLESS", default)


def browser_channel_kwargs() -> dict:
    """Return Playwright channel kwargs.

    Local Windows runs can keep Google Chrome by setting FB_BROWSER_CHANNEL=chrome.
    Docker images should set FB_BROWSER_CHANNEL to an empty value so Playwright
    uses the bundled Chromium from the container image.
    """
    channel = os.getenv("FB_BROWSER_CHANNEL", "chrome").strip()
    return {"channel": channel} if channel else {}
