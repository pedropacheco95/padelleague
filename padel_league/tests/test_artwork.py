import io
import itertools
import os
import tempfile

import pytest
from PIL import Image as PILImage
from sqlalchemy import event

from padel_league import create_app
from padel_league.model import Image
from padel_league.models import (
    Association_PlayerDivision,
    Association_PlayerMatch,
    Division,
    Edition,
    League,
    Match,
    Player,
)
from padel_league.services import artwork, artwork_generation
from padel_league.services.artwork import (
    BANNER_SIZE,
    POSTER_SIZE,
    ArtworkError,
    generate_for_edition,
    normalise,
    publish,
)
from padel_league.sql_db import db, init_db

_COMPOSITE_PK_TABLES_WITH_AUTOINCREMENT = [
    Association_PlayerMatch.__table__,
    Association_PlayerDivision.__table__,
]


@pytest.fixture
def app():
    db_fd, db_path = tempfile.mkstemp()

    original_autoincrement = [
        table.c.id.autoincrement for table in _COMPOSITE_PK_TABLES_WITH_AUTOINCREMENT
    ]
    for table in _COMPOSITE_PK_TABLES_WITH_AUTOINCREMENT:
        table.c.id.autoincrement = False

    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        }
    )

    with app.app_context():
        init_db(app)
        db.metadata.create_all(
            bind=db.engine,
            tables=[
                League.__table__,
                Edition.__table__,
                Division.__table__,
                Player.__table__,
                Match.__table__,
                Image.__table__,
                Association_PlayerMatch.__table__,
                Association_PlayerDivision.__table__,
            ],
        )

    yield app

    os.close(db_fd)
    os.unlink(db_path)
    for table, autoincrement in zip(
        _COMPOSITE_PK_TABLES_WITH_AUTOINCREMENT, original_autoincrement
    ):
        table.c.id.autoincrement = autoincrement


_assoc_ids = itertools.count(1)


@event.listens_for(Association_PlayerMatch, "before_insert", propagate=True)
@event.listens_for(Association_PlayerDivision, "before_insert", propagate=True)
def _assign_assoc_id(_mapper, _connection, target):
    if target.id is None:
        target.id = next(_assoc_ids)


def make_image_bytes(size, mode="RGB", fmt="PNG"):
    image = PILImage.new(mode, size, color=(120, 60, 30))
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def dimensions(data):
    return PILImage.open(io.BytesIO(data)).size


class FakeUploader:
    def __init__(self):
        self.uploads = {}

    def __call__(self, object_key, data):
        self.uploads[object_key] = data
        return True


# ── normalise ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "kind,expected", [("poster", POSTER_SIZE), ("banner", BANNER_SIZE)]
)
def test_already_correct_size_is_untouched_in_dimensions(kind, expected):
    data, info = normalise(make_image_bytes(expected), kind)
    assert dimensions(data) == expected
    assert info["was_resized"] is False


@pytest.mark.parametrize(
    "kind,expected", [("poster", POSTER_SIZE), ("banner", BANNER_SIZE)]
)
@pytest.mark.parametrize("source", [(1024, 1536), (1536, 1024), (500, 500), (4000, 90)])
def test_any_input_is_cropped_to_the_exact_target(kind, expected, source):
    data, info = normalise(make_image_bytes(source), kind)
    assert dimensions(data) == expected
    assert info["was_resized"] is True
    assert info["original_size"] == list(source)


def test_output_is_always_jpeg_even_from_png():
    data, _ = normalise(make_image_bytes(POSTER_SIZE, fmt="PNG"), "poster")
    assert PILImage.open(io.BytesIO(data)).format == "JPEG"


def test_transparent_png_is_flattened_to_rgb():
    data, _ = normalise(make_image_bytes((800, 800), mode="RGBA"), "poster")
    assert PILImage.open(io.BytesIO(data)).mode == "RGB"
    assert dimensions(data) == POSTER_SIZE


def test_cover_crop_preserves_aspect_ratio_rather_than_stretching():
    # A tall thin source cropped to the wide banner must keep circles round:
    # we check by cropping a source with a known square subject centred.
    source = PILImage.new("RGB", (1000, 1000), (0, 0, 0))
    for x in range(400, 600):
        for y in range(400, 600):
            source.putpixel((x, y), (255, 255, 255))
    buffer = io.BytesIO()
    source.save(buffer, format="PNG")

    data, _ = normalise(buffer.getvalue(), "banner")
    result = PILImage.open(io.BytesIO(data))
    assert result.size == BANNER_SIZE
    # centre pixel came from the white square, so the crop is centred
    assert result.getpixel((BANNER_SIZE[0] // 2, BANNER_SIZE[1] // 2))[0] > 200


def test_unreadable_bytes_raise():
    with pytest.raises(ArtworkError, match="could not read image"):
        normalise(b"definitely not an image", "poster")


def test_unknown_kind_raises():
    with pytest.raises(ArtworkError, match="unknown artwork kind"):
        normalise(make_image_bytes((10, 10)), "billboard")


# ── publish ──────────────────────────────────────────────────────────────────


def _make_division(app, name="Outono 2026 - 1ª Divisão", rating=2000, edition=None):
    with app.app_context():
        division = Division(name=name, rating=rating, edition_id=edition)
        db.session.add(division)
        db.session.commit()
        return division.id


def test_publish_uploads_links_and_records_the_image(app):
    division_id = _make_division(app)
    uploader = FakeUploader()

    with app.app_context():
        division = Division.query.get(division_id)
        info = publish(
            division,
            "poster",
            make_image_bytes((1024, 1536)),
            stamp="20260901120000",
            uploader=uploader,
        )

    assert info["object_key"] == "Division/20260901120000_logo_image_id.png"
    assert info["was_resized"] is True
    assert list(uploader.uploads) == [info["object_key"]]
    assert dimensions(uploader.uploads[info["object_key"]]) == POSTER_SIZE

    with app.app_context():
        division = Division.query.get(division_id)
        assert division.logo_image_id == info["image_id"]
        image = Image.query.get(info["image_id"])
        assert image.content_type == "image/jpeg"
        assert image.size_bytes == info["bytes"]
        assert image.is_public is True


def test_publish_banner_targets_the_large_picture_column(app):
    division_id = _make_division(app)
    uploader = FakeUploader()

    with app.app_context():
        division = Division.query.get(division_id)
        info = publish(
            division,
            "banner",
            make_image_bytes((1536, 1024)),
            stamp="20260901120001",
            uploader=uploader,
        )

    assert info["object_key"] == "Division/20260901120001_large_picture_id.png"
    with app.app_context():
        division = Division.query.get(division_id)
        assert division.large_picture_id == info["image_id"]
        assert division.logo_image_id is None


def test_publish_object_keys_match_the_production_naming(app):
    division_id = _make_division(app)
    uploader = FakeUploader()
    with app.app_context():
        division = Division.query.get(division_id)
        publish(
            division,
            "poster",
            make_image_bytes((900, 900)),
            stamp="20260529084600",
            uploader=uploader,
        )
    # Same shape as the existing rows, e.g. Division/20260529084600_logo_image_id.png
    assert "Division/20260529084600_logo_image_id.png" in uploader.uploads


# ── generate_for_edition ─────────────────────────────────────────────────────


def _make_edition(app, division_count=3):
    with app.app_context():
        league = League(name="Padel League")
        db.session.add(league)
        db.session.flush()
        edition = Edition(name="22ª Edição", league_id=league.id)
        db.session.add(edition)
        db.session.flush()
        for i in range(division_count):
            db.session.add(
                Division(
                    name=f"Outono 2026 - {i + 1}ª Divisão",
                    rating=2000 // (2**i),
                    edition_id=edition.id,
                )
            )
        db.session.commit()
        return edition.id


def test_generate_for_edition_covers_every_division_and_kind(app):
    edition_id = _make_edition(app, division_count=3)
    uploader = FakeUploader()
    calls = []

    def fake_generator(kind, extra=None):
        calls.append((kind, extra))
        size = (1024, 1536) if kind == "poster" else (1536, 1024)
        return make_image_bytes(size)

    with app.app_context():
        edition = Edition.query.get(edition_id)
        results = generate_for_edition(
            edition, generator=fake_generator, uploader=uploader
        )

    assert len(results) == 6  # 3 divisions x 2 kinds
    assert not [r for r in results if r.get("error")]
    assert len(uploader.uploads) == 6

    with app.app_context():
        for division in Edition.query.get(edition_id).divisions:
            assert division.logo_image_id is not None
            assert division.large_picture_id is not None

    # each division got a different scene variation
    poster_extras = [extra for kind, extra in calls if kind == "poster"]
    assert len(set(poster_extras)) == 3


def test_generate_for_edition_skips_divisions_that_already_have_artwork(app):
    edition_id = _make_edition(app, division_count=2)
    uploader = FakeUploader()

    def fake_generator(kind, extra=None):
        size = (1024, 1536) if kind == "poster" else (1536, 1024)
        return make_image_bytes(size)

    with app.app_context():
        edition = Edition.query.get(edition_id)
        generate_for_edition(edition, generator=fake_generator, uploader=uploader)

    first_pass = len(uploader.uploads)

    with app.app_context():
        edition = Edition.query.get(edition_id)
        results = generate_for_edition(
            edition, generator=fake_generator, uploader=uploader
        )

    assert all(r.get("skipped") for r in results)
    assert len(uploader.uploads) == first_pass  # nothing re-uploaded


def test_generate_for_edition_force_replaces(app):
    edition_id = _make_edition(app, division_count=1)
    uploader = FakeUploader()

    def fake_generator(kind, extra=None):
        return make_image_bytes((1024, 1536))

    with app.app_context():
        edition = Edition.query.get(edition_id)
        generate_for_edition(
            edition, kinds=("poster",), generator=fake_generator, uploader=uploader
        )
        first = Division.query.filter_by(edition_id=edition_id).first().logo_image_id

    with app.app_context():
        edition = Edition.query.get(edition_id)
        generate_for_edition(
            edition,
            kinds=("poster",),
            force=True,
            generator=fake_generator,
            uploader=uploader,
        )
        second = Division.query.filter_by(edition_id=edition_id).first().logo_image_id

    assert second != first


def test_one_failing_division_does_not_lose_the_others(app):
    edition_id = _make_edition(app, division_count=3)
    uploader = FakeUploader()
    seen = {"n": 0}

    def flaky_generator(kind, extra=None):
        seen["n"] += 1
        if seen["n"] == 3:  # fail partway through
            raise RuntimeError("image API exploded")
        size = (1024, 1536) if kind == "poster" else (1536, 1024)
        return make_image_bytes(size)

    with app.app_context():
        edition = Edition.query.get(edition_id)
        results = generate_for_edition(
            edition, generator=flaky_generator, uploader=uploader
        )

    errors = [r for r in results if r.get("error")]
    assert len(errors) == 1
    assert "image API exploded" in errors[0]["error"]

    with app.app_context():
        linked = [
            d
            for d in Edition.query.get(edition_id).divisions
            if d.logo_image_id or d.large_picture_id
        ]
        assert len(linked) >= 2  # the successful ones survived


# ── generation prompts ───────────────────────────────────────────────────────


def test_prompts_ask_for_no_text_since_the_site_renders_its_own():
    for kind in ("poster", "banner"):
        assert "No text" in artwork_generation.build_prompt(kind)


def test_generation_sizes_are_ones_the_model_accepts():
    assert set(artwork_generation.GENERATION_SIZES.values()) <= {
        "1024x1024",
        "1024x1536",
        "1536x1024",
    }


def test_variations_cycle_rather_than_running_out():
    first = artwork_generation.variation_for("poster", 0)
    assert artwork_generation.variation_for("poster", 6) == first
    assert artwork_generation.variation_for("poster", 1) != first


def test_generate_decodes_base64_from_the_api(monkeypatch):
    import base64

    payload = make_image_bytes((64, 64))

    class FakeImages:
        def generate(self, **kwargs):
            self.kwargs = kwargs
            return type(
                "R",
                (),
                {
                    "data": [
                        type("D", (), {"b64_json": base64.b64encode(payload).decode()})
                    ]
                },
            )

    class FakeClient:
        images = FakeImages()

    result = artwork_generation.generate("poster", client=FakeClient())
    assert result == payload
    assert FakeClient.images.kwargs["size"] == "1024x1536"


def test_generate_surfaces_api_failures_as_artwork_errors():
    class BoomClient:
        class images:
            @staticmethod
            def generate(**kwargs):
                raise RuntimeError("rate limited")

    with pytest.raises(ArtworkError, match="rate limited"):
        artwork_generation.generate("poster", client=BoomClient())


def test_missing_api_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ArtworkError, match="no image-model API key"):
        artwork_generation.generate("poster")


def test_bucket_name_is_required(monkeypatch):
    monkeypatch.delenv("GCS_UPLOADS_BUCKET", raising=False)
    with pytest.raises(ArtworkError, match="GCS_UPLOADS_BUCKET"):
        artwork._bucket_name()
