# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The single source of truth for the application version."""

__version__ = "0.3.6.3"

#: What this program calls itself when it asks a server for something.
#: Not decoration: Cloudflare answers 403 to Python's default
#: ``Python-urllib/3.x``, so a download that does not say who it is comes
#: back Forbidden — which is how the online component library reached the
#: live site and found nothing.
USER_AGENT = f"IngeTrazo/{__version__} (+https://ingetrazo.com)"
