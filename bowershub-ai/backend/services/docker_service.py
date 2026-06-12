"""
Docker service — queries the Docker daemon via Unix socket for container info.

Connects to /var/run/docker.sock using httpx with a Unix socket transport.
Returns a structured response with container list or a graceful error if
the Docker daemon is unreachable.

Requirements: 7.2, 7.3, 10.1
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from backend.http_client import get_http_client

logger = logging.getLogger(__name__)

DOCKER_SOCKET = "/var/run/docker.sock"


def _format_ports(ports: list[dict[str, Any]]) -> str:
    """
    Format Docker API port objects into a human-readable string.

    Each port object looks like:
    {"IP": "0.0.0.0", "PrivatePort": 5003, "PublicPort": 5003, "Type": "tcp"}
    """
    if not ports:
        return ""

    formatted: list[str] = []
    seen: set[str] = set()

    for port in ports:
        private = port.get("PrivatePort")
        public = port.get("PublicPort")
        port_type = port.get("Type", "tcp")

        if public and private:
            entry = f"{public}->{private}/{port_type}"
        elif private:
            entry = f"{private}/{port_type}"
        else:
            continue

        if entry not in seen:
            seen.add(entry)
            formatted.append(entry)

    return ", ".join(formatted)


def _normalize_status(state: str) -> str:
    """
    Normalize Docker container state to one of: running, stopped, restarting, exited.
    """
    state_lower = state.lower()
    if state_lower == "running":
        return "running"
    elif state_lower == "restarting":
        return "restarting"
    elif state_lower in ("exited", "dead"):
        return "exited"
    else:
        # paused, created, removing, etc. → stopped
        return "stopped"


async def get_containers() -> dict[str, Any]:
    """
    Fetch the list of Docker containers from the daemon.

    Returns:
        {
            "containers": [...],
            "error": None | str
        }

    If the Docker daemon is unreachable (socket missing, permission denied,
    connection refused), returns an empty list with an error message instead
    of raising an exception.
    """
    try:
        transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCKET)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://docker",
            timeout=5.0,
        ) as client:
            resp = await client.get("/containers/json?all=true")
            resp.raise_for_status()
            raw_containers = resp.json()

        containers = []
        for c in raw_containers:
            # Names come as ["/container-name"] — strip the leading /
            names = c.get("Names", [])
            name = names[0].lstrip("/") if names else "unknown"

            state = c.get("State", "unknown")
            status_text = c.get("Status", "")
            image = c.get("Image", "unknown")
            ports = c.get("Ports", [])

            containers.append({
                "name": name,
                "status": _normalize_status(state),
                "image": image,
                "ports": _format_ports(ports),
                "uptime": status_text,
            })

        return {"containers": containers, "error": None}

    except (
        httpx.ConnectError,
        httpx.TimeoutException,
        FileNotFoundError,
        PermissionError,
        OSError,
    ) as e:
        logger.warning(f"Docker daemon unreachable: {e}")
        return {"containers": [], "error": "Docker daemon unreachable"}
    except Exception as e:
        logger.error(f"Unexpected error querying Docker daemon: {e}")
        return {"containers": [], "error": "Docker daemon unreachable"}
