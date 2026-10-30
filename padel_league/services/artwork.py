"""Division artwork: normalise images to the exact sizes the site expects,
publish them to GCS and link them to a division (a v2 CompetitionGroup; the
pre-v2 Division is a read-only compat view and cannot take the image ids).

Two images per division, both stored as JPEG in the uploads bucket under
``Division/``:

- ``logo_image_id``     — the poster,      620 x 875 (portrait)
- ``large_picture_id``  — "ícone da cidade", 640 x 147 (wide strip)

Those numbers come from the images actually in production, not from the old
upload form, whose 1024x340 hint for the banner was stale.

Anything that is not already the exact size is cover-cropped to it (scale to
fill, then centre-crop) rather than stretched. The caller is told which images
were adjusted so it can flag them for a human to replace.
"""

import datetime
import io
import os

from PIL import Image as PILImage

from padel_league.model import Image
from padel_league.sql_db import db

POSTER_SIZE = (620, 875)
BANNER_SIZE = (640, 147)

KINDS = {
    "poster": {"size": POSTER_SIZE, "column": "logo_image_id", "suffix": "logo_image"},
    "banner": {
        "size": BANNER_SIZE,
        "column": "large_picture_id",
        "suffix": "large_picture",
    },
}

JPEG_QUALITY = 88


class ArtworkError(Exception):
    """Artwork could not be normalised, uploaded or linked."""


def _bucket_name():
    bucket = os.environ.get("GCS_UPLOADS_BUCKET")
    if not bucket:
        raise ArtworkError("GCS_UPLOADS_BUCKET is not set")
    return bucket


def normalise(image_bytes, kind):
    """Return (jpeg_bytes, info) with the image at exactly the size for `kind`.

    `info` reports the original size and whether a resize was needed, so the
    caller can flag images that arrived wrong and were cropped.
    """
    if kind not in KINDS:
        raise ArtworkError(
            f"unknown artwork kind {kind!r}; expected one of {sorted(KINDS)}"
        )
    target = KINDS[kind]["size"]

    try:
        source = PILImage.open(io.BytesIO(image_bytes))
        source.load()
    except Exception as exc:
        raise ArtworkError(f"could not read image: {exc}")

    original = source.size
    resized = original != target

    if source.mode != "RGB":
        source = source.convert("RGB")

    if resized:
        source = _cover_crop(source, target)

    buffer = io.BytesIO()
    source.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)

    return buffer.getvalue(), {
        "kind": kind,
        "original_size": list(original),
        "final_size": list(target),
        "was_resized": resized,
    }


def _cover_crop(image, target):
    """Scale to fill `target` preserving aspect ratio, then centre-crop."""
    target_w, target_h = target
    source_w, source_h = image.size

    scale = max(target_w / source_w, target_h / source_h)
    scaled = image.resize(
        (max(1, round(source_w * scale)), max(1, round(source_h * scale))),
        PILImage.LANCZOS,
    )

    scaled_w, scaled_h = scaled.size
    left = (scaled_w - target_w) // 2
    top = (scaled_h - target_h) // 2
    return scaled.crop((left, top, left + target_w, top + target_h))


def _object_key(kind, stamp):
    return f"Division/{stamp}_{KINDS[kind]['suffix']}_id.png"


def publish(division, kind, image_bytes, stamp=None, uploader=None, commit=True):
    """Normalise, upload to GCS, record an Image row and link it to `division`
    (a v2 CompetitionGroup: same logo_image_id / large_picture_id columns, so
    Teams divisions and Shuffle groups take artwork the same way).

    `uploader` is injectable for tests; by default it uploads to the bucket in
    GCS_UPLOADS_BUCKET. Returns the info dict from `normalise` plus the image id
    and object key.
    """
    normalised, info = normalise(image_bytes, kind)

    # Matches the existing production naming, e.g.
    # Division/20260529084600_logo_image_id.png (JPEG bytes, .png key — the
    # site serves these by object key, so keep the convention).
    #
    # Microseconds, not seconds as the old upload form used: object_key is
    # UNIQUE, and generating a whole edition publishes a dozen images inside the
    # same second, which collides.
    stamp = stamp or datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
    object_key = _object_key(kind, stamp)

    (uploader or _upload_to_gcs)(object_key, normalised)

    image = Image(
        object_key=object_key,
        content_type="image/jpeg",
        size_bytes=len(normalised),
        is_public=True,
    )
    db.session.add(image)
    db.session.flush()

    setattr(division, KINDS[kind]["column"], image.id)

    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    else:
        db.session.flush()

    info.update(
        {
            "division_id": division.id,
            "division_name": division.name,
            "image_id": image.id,
            "object_key": object_key,
            "bytes": len(normalised),
        }
    )
    return info


def _upload_to_gcs(object_key, data):
    from google.cloud import storage

    client = storage.Client()
    blob = client.bucket(_bucket_name()).blob(object_key)
    blob.upload_from_string(data, content_type="image/jpeg")
    return True


def generate_for_edition(
    edition, kinds=("poster", "banner"), force=False, generator=None, uploader=None
):
    """Generate and attach artwork for every division in `edition`.

    Divisions are processed in ladder order (highest rating first) so the scene
    variations line up with 1ª, 2ª, 3ª... Each division commits on its own:
    generation is slow and paid for per image, so a failure on division 5 must
    not throw away the four already done. Returns one result dict per attempt,
    with `error` set on the ones that failed.
    """
    from padel_league.models.v2 import CompetitionGroup, Stage
    from padel_league.services import artwork_generation

    generator = generator or artwork_generation.generate
    # v2: write to the competition's groups (edition id = competition id); the
    # pre-v2 Division is a read-only view and cannot take the image ids.
    groups = (
        CompetitionGroup.query.join(Stage, Stage.id == CompetitionGroup.stage_id)
        .filter(Stage.competition_id == edition.id)
        .all()
    )
    divisions = sorted(groups, key=lambda d: (-(d.rating or 0), (d.name or "").lower()))

    results = []
    for index, division in enumerate(divisions):
        for kind in kinds:
            column = KINDS[kind]["column"]
            if getattr(division, column) and not force:
                results.append(
                    {
                        "division_id": division.id,
                        "division_name": division.name,
                        "kind": kind,
                        "skipped": "already has artwork; pass force to replace",
                    }
                )
                continue
            try:
                data = generator(
                    kind, extra=artwork_generation.variation_for(kind, index)
                )
                results.append(publish(division, kind, data, uploader=uploader))
            except Exception as exc:
                db.session.rollback()
                results.append(
                    {
                        "division_id": division.id,
                        "division_name": division.name,
                        "kind": kind,
                        "error": str(exc),
                    }
                )
    return results


# --- local files -------------------------------------------------------------


def load_group(group_id, competition_id=None):
    """The v2 CompetitionGroup with `group_id`, else ArtworkError.

    With `competition_id`, a group of any other competition is refused too, so
    a mistyped id cannot land artwork on another edition's division.
    """
    from padel_league.models.v2 import CompetitionGroup

    try:
        group = db.session.get(CompetitionGroup, int(group_id))
    except (TypeError, ValueError):
        group = None
    if group is None:
        raise ArtworkError(f"group {group_id!r} was not found")
    if competition_id is not None and group.stage.competition_id != int(competition_id):
        raise ArtworkError(
            f"group {group.id} ({group.name}) belongs to competition "
            f"{group.stage.competition_id}, not {int(competition_id)}"
        )
    return group


def attach_file(group, kind, path, force=False, uploader=None, stamp=None):
    """Publish the local image file at `path` as the `kind` artwork of `group`.

    One commit. Existing artwork is kept unless `force` (then the group points
    at the new image; the old Image row and object stay, as generate_for_edition
    leaves them). Returns the publish info plus `file`, or a dict with
    `skipped` when nothing was done.
    """
    if kind not in KINDS:
        raise ArtworkError(f"unknown artwork kind {kind!r}; expected one of {sorted(KINDS)}")
    column = KINDS[kind]["column"]
    if getattr(group, column) and not force:
        return {
            "division_id": group.id,
            "division_name": group.name,
            "kind": kind,
            "file": str(path),
            "skipped": "already has artwork; pass force to replace",
        }
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        raise ArtworkError(f"could not read {path}: {exc}")
    info = publish(group, kind, data, stamp=stamp, uploader=uploader)
    info["file"] = str(path)
    return info


def attach_manifest(entries, force=False, uploader=None, competition_id=None):
    """Attach every ``{"group_id", "kind", "file"}`` in `entries`, one commit each.

    Same failure isolation as generate_for_edition: an entry that fails (bad
    file, unknown group, a group outside `competition_id`, upload error) is
    reported with `error` and the others still land. Returns one result dict
    per entry, in order.
    """
    results = []
    for entry in entries:
        if not isinstance(entry, dict) or not all(k in entry for k in ("group_id", "kind", "file")):
            results.append({"entry": entry, "error": "each entry needs group_id, kind and file"})
            continue
        group_id, kind, path = entry["group_id"], entry["kind"], entry["file"]
        try:
            group = load_group(group_id, competition_id=competition_id)
            results.append(attach_file(group, kind, path, force=force, uploader=uploader))
        except Exception as exc:
            db.session.rollback()
            results.append({"division_id": group_id, "kind": kind, "file": str(path), "error": str(exc)})
    return results
