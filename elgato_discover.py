"""
Discover Elgato Key Lights on the LAN via mDNS.

Author: Emmanuel Tychon
SPDX-License-Identifier: MIT

The ``leglight`` package's ``discover()`` uses a ServiceBrowser listener without
``update_service``, which triggers a FutureWarning on current zeroconf releases
and will fail once that hook becomes mandatory. This module mirrors the same
discovery behavior with a complete listener and still constructs ``leglight``
``LegLight`` instances for on/off control.
"""

from __future__ import annotations

import logging
import socket
from time import sleep, time
from typing import List, cast

from zeroconf import ServiceBrowser, Zeroconf

from leglight.leglight import LegLight

_ELG_SERVICE = "_elg._tcp.local."


def discover_key_lights(timeout: float = 5) -> List[LegLight]:
    """Return ``LegLight`` instances found within *timeout* seconds."""
    lights: List[LegLight] = []

    class _DiscoveryListener:
        def add_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
            info = zeroconf.get_service_info(type_, name)
            if not info or not info.addresses:
                return
            ip = socket.inet_ntoa(info.addresses[0])
            port = cast(int, info.port)
            logging.debug("Found light @ %s:%s", ip, port)
            lights.append(
                LegLight(
                    address=ip,
                    port=port,
                    name=info.name,
                    server=info.server or "",
                )
            )

        def remove_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
            pass

        def update_service(self, zeroconf: Zeroconf, type_: str, name: str) -> None:
            """Required by zeroconf; service updates do not change our device list."""
            pass

    # ServiceBrowser must be cancelled before Zeroconf.close(); otherwise zeroconf
    # leaks asyncio tasks, sockets, and threads (eventually EMFILE / errno 24).
    with Zeroconf() as zeroconf:
        with ServiceBrowser(zeroconf, _ELG_SERVICE, _DiscoveryListener()):
            start = time()
            while time() - start < timeout:
                sleep(0.1)
    return lights
