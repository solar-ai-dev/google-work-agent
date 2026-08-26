"""Default local browser launcher."""

import webbrowser


class DefaultBrowserLauncherAdapter:
    def open(self, url: str) -> None:
        if not url:
            raise ValueError("url must not be blank")
        webbrowser.open(url)
