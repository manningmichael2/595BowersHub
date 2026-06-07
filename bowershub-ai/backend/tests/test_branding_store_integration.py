"""
Integration test for the branding store upload pipeline.

End-to-end exercises ``backend.services.branding_store.upload_icon`` against
a fresh ephemeral Postgres DB (with migrations applied) and a per-test
on-disk branding root. Asserts the published behavior of R2.2 / R2.4 /
R2.7:

* A real 1024x1024 PNG flows through Pillow → variants written to
  ``$FILES_ROOT/branding/active/`` with correct dimensions for the 192px
  any-purpose icon and the maskable 512px variant.
* On the second upload, the prior active set is moved into ``previous/``
  (the rollback slot, R2.7).
* The cache-busting ``version`` string changes across uploads (R2.4) and
  matches what is stored in ``bh_platform_settings.app_icon_version``.

Validates: Requirements R2.2, R2.4, R2.7
"""

from __future__ import annotations

import io
import time
from pathlib import Path

import pytest
from PIL import Image

from backend.config import Config
from backend.database import close_pool, init_pool, run_migrations


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_png(size: int, color: tuple[int, int, int, int] = (32, 96, 192, 255)) -> bytes:
    """Build a real square RGBA PNG of the given side length, in memory."""
    img = Image.new("RGBA", (size, size), color)
    # Stamp something non-uniform so resize/maskable padding shows visible
    # pixel differences from a flat fill (defensive — not asserted on).
    for x in range(size // 4, 3 * size // 4):
        for y in range(size // 4, 3 * size // 4):
            if (x + y) % 16 == 0:
                img.putpixel((x, y), (255, 255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _read_png_dims(p: Path) -> tuple[int, int]:
    with Image.open(p) as im:
        im.load()
        return im.size


def _wait_until_epoch_past(target_epoch: int, timeout_s: float = 5.0) -> None:
    """
    Block until ``int(time.time()) > target_epoch`` so the next call to
    ``branding_store._new_version()`` produces a strictly-greater epoch
    string. Defensive against clock drift between postgres' ``now()``
    (used in migration 009) and the python wall clock used by
    ``branding_store``.
    """
    deadline = time.monotonic() + timeout_s
    while int(time.time()) <= target_epoch and time.monotonic() < deadline:
        time.sleep(0.2)


async def _apply_migrations_to(db_name: str, db_settings: dict) -> None:
    """Initialize the project pool against ``db_name`` and run all migrations."""
    config = Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]),
        DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name,
        DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test",
        N8N_BASE="http://localhost:5678",
    )
    pool = await init_pool(config)
    await run_migrations(pool)


async def _read_version(pool) -> str:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value_json FROM public.bh_platform_settings "
            "WHERE key = 'app_icon_version'"
        )
        assert row is not None, "app_icon_version row missing — migration 009 broken"
        return str(row["value_json"]["version"])


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


async def test_upload_icon_writes_variants_and_rolls_previous(
    fresh_db, db_settings, tmp_path, monkeypatch
):
    """
    A real 1024x1024 PNG → ``upload_icon`` → assert:

    1. After the first upload:
       - ``active/icon-192.png`` exists and is 192x192.
       - ``active/icon-512.png`` exists and is 512x512.
       - ``active/icon-maskable-512.png`` exists and is 512x512.
       - ``previous/`` is empty (no prior active set existed).
       - ``app_icon_version`` differs from the seed value written by
         migration 009.

    2. After a second upload (with a different source image):
       - ``previous/`` contains the three variants from the *first* upload.
       - ``active/`` contains the new variants.
       - ``app_icon_version`` differs from the first upload's version.

    Validates: Requirements R2.2, R2.4, R2.7
    """
    # Point the branding store at an isolated on-disk root for this test.
    monkeypatch.setenv("FILES_ROOT", str(tmp_path))
    branding_root = tmp_path / "branding"

    await _apply_migrations_to(fresh_db, db_settings)

    # Import lazily so the env-var monkeypatch above is in effect for the
    # module's first lookup of FILES_ROOT (the function reads os.environ
    # at call time, but importing late is still defensive and harmless).
    from backend.database import get_pool
    from backend.services import branding_store

    pool = get_pool()
    seed_version = await _read_version(pool)

    # ------------------------------------------------------------------
    # First upload — fresh state, no previous slot expected
    # ------------------------------------------------------------------

    # The version stamp is unix-epoch *seconds* (text). The migration
    # uses postgres ``now()`` while ``upload_icon`` uses python
    # ``time.time()``, and the two clocks drift by sub-second amounts.
    # Wait until python's wall clock is strictly past the seed second
    # before triggering the upload so the two version strings cannot
    # collide.
    _wait_until_epoch_past(int(seed_version))

    src1 = _make_png(1024)
    result1 = await branding_store.upload_icon(src1)

    assert isinstance(result1, dict)
    assert "version" in result1 and "urls" in result1
    assert result1["version"] != seed_version, (
        f"first upload's version ({result1['version']}) did not change "
        f"from the seeded value ({seed_version})"
    )

    # On-disk shape: active/ has all three variants at correct sizes.
    active = branding_root / "active"
    assert active.is_dir(), f"{active} not created by upload_icon"

    icon_192 = active / "icon-192.png"
    icon_512 = active / "icon-512.png"
    icon_mask_512 = active / "icon-maskable-512.png"

    assert icon_192.is_file(), f"missing {icon_192}"
    assert icon_512.is_file(), f"missing {icon_512}"
    assert icon_mask_512.is_file(), f"missing {icon_mask_512}"

    assert _read_png_dims(icon_192) == (192, 192), (
        f"icon-192.png is {_read_png_dims(icon_192)}, expected (192, 192)"
    )
    assert _read_png_dims(icon_512) == (512, 512), (
        f"icon-512.png is {_read_png_dims(icon_512)}, expected (512, 512)"
    )
    assert _read_png_dims(icon_mask_512) == (512, 512), (
        f"icon-maskable-512.png is {_read_png_dims(icon_mask_512)}, "
        f"expected (512, 512)"
    )

    # First upload should not populate previous/ (no prior active set).
    previous = branding_root / "previous"
    has_prev_files_after_first = previous.exists() and any(previous.iterdir())
    assert not has_prev_files_after_first, (
        f"previous/ unexpectedly populated after the first upload: "
        f"{list(previous.iterdir()) if previous.exists() else 'n/a'}"
    )

    # DB row should match the returned version.
    db_version_1 = await _read_version(pool)
    assert db_version_1 == result1["version"], (
        f"bh_platform_settings.app_icon_version ({db_version_1}) "
        f"does not match returned version ({result1['version']})"
    )

    # Snapshot first-upload bytes so we can verify they migrate to previous/.
    first_active_bytes = {
        name: (active / name).read_bytes()
        for name in ("icon-192.png", "icon-512.png", "icon-maskable-512.png")
    }

    # ------------------------------------------------------------------
    # Second upload — should archive first set into previous/
    # ------------------------------------------------------------------

    # Same wait as before the first upload — guarantee a fresh epoch
    # second so ``app_icon_version`` is strictly greater than the prior.
    _wait_until_epoch_past(int(result1["version"]))

    src2 = _make_png(1024, color=(192, 64, 32, 255))
    result2 = await branding_store.upload_icon(src2)

    assert result2["version"] != result1["version"], (
        f"second upload's version ({result2['version']}) did not change "
        f"from the first upload's version ({result1['version']})"
    )
    assert result2["version"] != seed_version

    # Active contains the new variants at correct sizes.
    assert _read_png_dims(icon_192) == (192, 192)
    assert _read_png_dims(icon_512) == (512, 512)
    assert _read_png_dims(icon_mask_512) == (512, 512)

    # Previous now exists with the *first* upload's bytes (R2.7 rollback slot).
    assert previous.is_dir(), "previous/ not created on second upload"
    for name, expected_bytes in first_active_bytes.items():
        prev_file = previous / name
        assert prev_file.is_file(), f"previous/{name} missing after second upload"
        assert prev_file.read_bytes() == expected_bytes, (
            f"previous/{name} bytes do not match the first upload's active/{name}"
        )

    # Active bytes differ from previous (the second upload's content is new).
    for name in first_active_bytes:
        assert (active / name).read_bytes() != first_active_bytes[name], (
            f"active/{name} bytes equal previous/{name} after second upload — "
            f"new content was not written"
        )

    db_version_2 = await _read_version(pool)
    assert db_version_2 == result2["version"]

    await close_pool()
