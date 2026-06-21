import os


def browser_channel_kwargs() -> dict:
    """Return Playwright channel kwargs.

    Local Windows runs can keep the default Google Chrome channel. Docker images
    normally use Playwright's bundled Chromium, so set FB_BROWSER_CHANNEL to an
    empty value there and this helper omits the channel option.
    """
    channel = os.getenv("FB_BROWSER_CHANNEL", "chrome").strip()
    return {"channel": channel} if channel else {}
