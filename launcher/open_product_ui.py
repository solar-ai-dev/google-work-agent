"""Open the loopback product UI through the BrowserLauncherPort boundary."""

from __future__ import annotations

from urllib.parse import urlencode

from google_work_agent.ports.system.browser_launcher_port import BrowserLauncherPort


def open_product_ui(
    browser: BrowserLauncherPort,
    *,
    port: int,
    bootstrap_secret: str | None = None,
    service_instance_id: str | None = None,
) -> str:
    """Open either the one-time bootstrap fragment or the existing-session URL."""

    url = build_product_ui_url(
        port=port,
        bootstrap_secret=bootstrap_secret,
        service_instance_id=service_instance_id,
    )
    browser.open_url(url)
    return url


def build_product_ui_url(
    *,
    port: int,
    bootstrap_secret: str | None = None,
    service_instance_id: str | None = None,
) -> str:
    """Build the loopback URL without logging or opening its secret fragment."""

    if not 1 <= port <= 65535:
        raise ValueError("port must be valid")
    url = f"http://127.0.0.1:{port}/"
    if bootstrap_secret is not None or service_instance_id is not None:
        if not bootstrap_secret or not service_instance_id:
            raise ValueError("bootstrap secret and service instance ID must be supplied together")
        fragment = urlencode(
            {
                "bootstrap_secret": bootstrap_secret,
                "service_instance_id": service_instance_id,
            }
        )
        url = f"{url}#{fragment}"
    return url


__all__ = ["build_product_ui_url", "open_product_ui"]
