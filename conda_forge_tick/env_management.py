import os
import threading
from contextlib import contextmanager

THREAD_LOCK = threading.RLock()


class SensitiveEnv:
    SENSITIVE_KEYS = [
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "BOT_TOKEN",
        "MONGODB_CONNECTION_STRING",
        "BOT_APP_ID",
        "BOT_PRIVATE_KEY",
    ]

    def __init__(self):
        self.classified_info = {}

    def hide_env_vars(self):
        """Remove sensitive env vars."""
        self.classified_info.update(
            {
                k: os.environ.pop(k, self.classified_info.get(k, None))
                for k in self.SENSITIVE_KEYS
            },
        )

    def reveal_env_vars(self):
        """Restore sensitive env vars."""
        os.environ.update(
            **{k: v for k, v in self.classified_info.items() if v is not None}
        )

    @contextmanager
    def sensitive_env(self):
        """Add sensitive keys to environ if needed, when ctx is finished remove keys and update the sensitive env
        in case any were updated inside the ctx.
        """
        with THREAD_LOCK:
            self.reveal_env_vars()
            yield os.environ
            self.hide_env_vars()
