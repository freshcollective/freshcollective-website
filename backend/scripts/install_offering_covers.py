"""Install the curated Offering cover images into storage.

Offerings B6. Idempotent: running it twice is harmless, and running it
after only some files exist installs the rest.

    cd backend
    python -m scripts.install_offering_covers            # report only
    python -m scripts.install_offering_covers --write    # actually install

Why a script and not a migration
--------------------------------

These are bytes, not rows. A migration moves schema and data inside one
transaction against one database; this puts five pairs of image files
into object storage, which no migration can roll back and which is
identical across every environment. It is also the pattern the other
curated-asset work in this repository already uses (``seed_initial_places``,
``backfill_location_thumbnails``).

Where the files go
------------------

``platform-artwork/offering-covers/<name>.webp`` — the **public** bucket,
because ``_bucket_for_key`` routes the ``platform-artwork/`` prefix there
and ``serve_public_upload`` serves it without a session. A cover on a
public Collective card must render for a signed-out visitor.

Running this against production
-------------------------------

Required **before** Offerings is enabled: until it has run, the picker
lists five covers whose images 404, and an Offering cannot satisfy its
cover requirement. It is safe to run at any time beforehand — it writes
only to the five curated keys and touches no creator data, no database
row and no existing object outside that namespace.

``Settings`` reads ``.env`` from the current working directory, so run
this from a directory whose ``.env`` carries the **production** R2
credentials — or from Render's shell, where the environment is already
production's. Running it from a developer checkout installs into that
checkout's storage, which is the right outcome for local work and the
wrong one if you meant production.
"""

from __future__ import annotations

import argparse
import sys

from app.core import storage
from app.services import offering_covers


def _exists(key: str) -> bool:
    """Is the object already in storage?

    ``object_head`` answers for both backends — an R2 ``HeadObject`` or
    a filesystem ``stat`` — so the idempotency check does not care which
    mode it is running in.
    """
    try:
        return storage.object_head(key) is not None
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true",
        help="Actually upload. Without it, report what would happen.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-upload files that are already present.",
    )
    args = parser.parse_args(argv)

    missing = offering_covers.missing_assets()
    if missing:
        print("ERROR — these files are named by the manifest but are not in "
              "the repository:", file=sys.stderr)
        for p in missing:
            print(f"  {p}", file=sys.stderr)
        return 2

    mode = "R2" if storage.settings.is_r2_enabled else "filesystem"
    print(f"storage mode: {mode}")
    print(f"target namespace: {offering_covers.COVER_PREFIX}/")
    print()

    installed = skipped = 0
    for key, path in offering_covers.asset_paths():
        size_kb = path.stat().st_size / 1024
        if _exists(key) and not args.force:
            print(f"  present   {key}")
            skipped += 1
            continue
        if not args.write:
            print(f"  would add {key}  ({size_kb:.0f} KB)")
            installed += 1
            continue
        with open(path, "rb") as fh:
            storage.upload_stream(key, fh, "image/webp")
        print(f"  installed {key}  ({size_kb:.0f} KB)")
        installed += 1

    print()
    verb = "installed" if args.write else "would install"
    print(f"{verb}: {installed}   already present: {skipped}")
    if not args.write and installed:
        print("\nRe-run with --write to install.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
