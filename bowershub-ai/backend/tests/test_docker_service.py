"""
Unit tests for the Docker service.

Tests container listing, port formatting, status normalization, and
graceful handling when the Docker daemon is unreachable.

Validates: Requirements 7.2, 7.3, 10.1
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

from backend.services.docker_service import (
    _format_ports,
    _normalize_status,
    get_containers,
)


# ---------------------------------------------------------------------------
# Port formatting
# ---------------------------------------------------------------------------


def test_format_ports_empty_list():
    """Empty ports list returns empty string."""
    assert _format_ports([]) == ""


def test_format_ports_single_mapped_port():
    """Single port with public mapping formats as 'public->private/type'."""
    ports = [{"IP": "0.0.0.0", "PrivatePort": 5003, "PublicPort": 5003, "Type": "tcp"}]
    assert _format_ports(ports) == "5003->5003/tcp"


def test_format_ports_multiple_ports():
    """Multiple ports joined with commas."""
    ports = [
        {"IP": "0.0.0.0", "PrivatePort": 80, "PublicPort": 8080, "Type": "tcp"},
        {"IP": "0.0.0.0", "PrivatePort": 443, "PublicPort": 8443, "Type": "tcp"},
    ]
    assert _format_ports(ports) == "8080->80/tcp, 8443->443/tcp"


def test_format_ports_unmapped_port():
    """Port without a public mapping shows just private/type."""
    ports = [{"PrivatePort": 5432, "Type": "tcp"}]
    assert _format_ports(ports) == "5432/tcp"


def test_format_ports_deduplicates():
    """Duplicate port entries are deduplicated."""
    ports = [
        {"IP": "0.0.0.0", "PrivatePort": 80, "PublicPort": 80, "Type": "tcp"},
        {"IP": "::", "PrivatePort": 80, "PublicPort": 80, "Type": "tcp"},
    ]
    assert _format_ports(ports) == "80->80/tcp"


# ---------------------------------------------------------------------------
# Status normalization
# ---------------------------------------------------------------------------


def test_normalize_status_running():
    assert _normalize_status("running") == "running"


def test_normalize_status_exited():
    assert _normalize_status("exited") == "exited"


def test_normalize_status_dead():
    assert _normalize_status("dead") == "exited"


def test_normalize_status_restarting():
    assert _normalize_status("restarting") == "restarting"


def test_normalize_status_paused():
    assert _normalize_status("paused") == "stopped"


def test_normalize_status_created():
    assert _normalize_status("created") == "stopped"


# ---------------------------------------------------------------------------
# get_containers — success case
# ---------------------------------------------------------------------------


SAMPLE_DOCKER_RESPONSE = [
    {
        "Id": "abc123",
        "Names": ["/bowershub-ai"],
        "Image": "bowershub-ai:latest",
        "State": "running",
        "Status": "Up 3 days",
        "Ports": [
            {"IP": "0.0.0.0", "PrivatePort": 5003, "PublicPort": 5003, "Type": "tcp"}
        ],
        "Created": 1717171717,
    },
    {
        "Id": "def456",
        "Names": ["/postgres"],
        "Image": "postgres:16",
        "State": "running",
        "Status": "Up 5 days",
        "Ports": [
            {"PrivatePort": 5432, "Type": "tcp"}
        ],
        "Created": 1717000000,
    },
    {
        "Id": "ghi789",
        "Names": ["/old-container"],
        "Image": "nginx:1.25",
        "State": "exited",
        "Status": "Exited (0) 2 days ago",
        "Ports": [],
        "Created": 1716000000,
    },
]


@pytest.mark.asyncio
async def test_get_containers_success():
    """Successfully lists containers from Docker daemon."""
    mock_response = MagicMock()
    mock_response.json.return_value = SAMPLE_DOCKER_RESPONSE
    mock_response.raise_for_status = MagicMock()

    with patch("backend.services.docker_service.httpx.AsyncHTTPTransport"):
        with patch("backend.services.docker_service.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await get_containers()

    assert result["error"] is None
    assert len(result["containers"]) == 3

    # First container
    c0 = result["containers"][0]
    assert c0["name"] == "bowershub-ai"
    assert c0["status"] == "running"
    assert c0["image"] == "bowershub-ai:latest"
    assert c0["ports"] == "5003->5003/tcp"
    assert c0["uptime"] == "Up 3 days"

    # Second container
    c1 = result["containers"][1]
    assert c1["name"] == "postgres"
    assert c1["status"] == "running"
    assert c1["ports"] == "5432/tcp"

    # Third container — exited
    c2 = result["containers"][2]
    assert c2["name"] == "old-container"
    assert c2["status"] == "exited"
    assert c2["ports"] == ""
    assert c2["uptime"] == "Exited (0) 2 days ago"


# ---------------------------------------------------------------------------
# get_containers — error cases (Docker daemon unreachable)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_containers_connect_error():
    """ConnectError (socket missing) returns graceful error response."""
    with patch("backend.services.docker_service.httpx.AsyncHTTPTransport"):
        with patch("backend.services.docker_service.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await get_containers()

    assert result["containers"] == []
    assert result["error"] == "Docker daemon unreachable"


@pytest.mark.asyncio
async def test_get_containers_timeout():
    """Timeout returns graceful error response."""
    with patch("backend.services.docker_service.httpx.AsyncHTTPTransport"):
        with patch("backend.services.docker_service.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await get_containers()

    assert result["containers"] == []
    assert result["error"] == "Docker daemon unreachable"


@pytest.mark.asyncio
async def test_get_containers_permission_error():
    """PermissionError (socket not accessible) returns graceful error."""
    with patch("backend.services.docker_service.httpx.AsyncHTTPTransport", side_effect=PermissionError("access denied")):
        result = await get_containers()

    assert result["containers"] == []
    assert result["error"] == "Docker daemon unreachable"


@pytest.mark.asyncio
async def test_get_containers_file_not_found():
    """FileNotFoundError (socket doesn't exist) returns graceful error."""
    with patch("backend.services.docker_service.httpx.AsyncHTTPTransport", side_effect=FileNotFoundError("/var/run/docker.sock")):
        result = await get_containers()

    assert result["containers"] == []
    assert result["error"] == "Docker daemon unreachable"


@pytest.mark.asyncio
async def test_get_containers_empty_list():
    """Docker daemon with zero containers returns empty list without error."""
    mock_response = MagicMock()
    mock_response.json.return_value = []
    mock_response.raise_for_status = MagicMock()

    with patch("backend.services.docker_service.httpx.AsyncHTTPTransport"):
        with patch("backend.services.docker_service.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await get_containers()

    assert result["containers"] == []
    assert result["error"] is None
