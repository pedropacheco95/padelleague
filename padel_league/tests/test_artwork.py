import io
import json

import pytest
from PIL import Image as PILImage

from padel_league.model import Image
from padel_league.models.v2 import Competition, CompetitionGroup, Stage
from padel_league.tests import factories as f
from padel_league.services import artwork, artwork_generation
from padel_league.services.artwork import (
    ArtworkError,
    attach_file,
    attach_manifest,
    BANNER_SIZE,
    generate_for_edition,
    load_group,
    normalise,
    POSTER_SIZE,
    publish,
)
from padel_league.sql_db import db


@pytest.fixture
def app(pg):
    """Postgres clone of v2_template (conftest.pg); everything is rolled back."""
    return pg


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
    comp = edition or f.competition(name="Artwork test")
    stg = Stage.query.filter_by(competition_id=comp.id, number=1).first() or f.stage(comp)
    group = f.group(stg, tier=1, rating=rating, name=name)
    db.session.commit()
    return group.id


def test_publish_uploads_links_and_records_the_image(app):
    division_id = _make_division(app)
    uploader = FakeUploader()

    with app.app_context():
        division = db.session.get(CompetitionGroup, division_id)
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
        division = db.session.get(CompetitionGroup, division_id)
        assert division.logo_image_id == info["image_id"]
        image = db.session.get(Image, info["image_id"])
        assert image.content_type == "image/jpeg"
        assert image.size_bytes == info["bytes"]
        assert image.is_public is True


def test_publish_banner_targets_the_large_picture_column(app):
    division_id = _make_division(app)
    uploader = FakeUploader()

    with app.app_context():
        division = db.session.get(CompetitionGroup, division_id)
        info = publish(
            division,
            "banner",
            make_image_bytes((1536, 1024)),
            stamp="20260901120001",
            uploader=uploader,
        )

    assert info["object_key"] == "Division/20260901120001_large_picture_id.png"
    with app.app_context():
        division = db.session.get(CompetitionGroup, division_id)
        assert division.large_picture_id == info["image_id"]
        assert division.logo_image_id is None


def test_publish_object_keys_match_the_production_naming(app):
    division_id = _make_division(app)
    uploader = FakeUploader()
    with app.app_context():
        division = db.session.get(CompetitionGroup, division_id)
        publish(
            division,
            "poster",
            make_image_bytes((900, 900)),
            stamp="20991231235900",
            uploader=uploader,
        )
    # Same shape as the existing rows, e.g. Division/20260529084600_logo_image_id.png
    assert "Division/20991231235900_logo_image_id.png" in uploader.uploads


# ── generate_for_edition ─────────────────────────────────────────────────────


def _make_edition(app, division_count=3):
    comp = f.competition(name="22ª Edição artwork")
    stg = f.stage(comp)
    for i in range(division_count):
        f.group(stg, tier=i + 1, rating=2000 // (2**i), name=f"Outono 2026 - {i + 1}ª Divisão")
    db.session.commit()
    return comp.id


def _groups(edition_id):
    return CompetitionGroup.query.join(Stage).filter(Stage.competition_id == edition_id).all()


def test_generate_for_edition_covers_every_division_and_kind(app):
    edition_id = _make_edition(app, division_count=3)
    uploader = FakeUploader()
    calls = []

    def fake_generator(kind, extra=None):
        calls.append((kind, extra))
        size = (1024, 1536) if kind == "poster" else (1536, 1024)
        return make_image_bytes(size)

    with app.app_context():
        edition = db.session.get(Competition, edition_id)
        results = generate_for_edition(
            edition, generator=fake_generator, uploader=uploader
        )

    assert len(results) == 6  # 3 divisions x 2 kinds
    assert not [r for r in results if r.get("error")]
    assert len(uploader.uploads) == 6

    with app.app_context():
        for division in _groups(edition_id):
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
        edition = db.session.get(Competition, edition_id)
        generate_for_edition(edition, generator=fake_generator, uploader=uploader)

    first_pass = len(uploader.uploads)

    with app.app_context():
        edition = db.session.get(Competition, edition_id)
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
        edition = db.session.get(Competition, edition_id)
        generate_for_edition(
            edition, kinds=("poster",), generator=fake_generator, uploader=uploader
        )
        first = _groups(edition_id)[0].logo_image_id

    with app.app_context():
        edition = db.session.get(Competition, edition_id)
        generate_for_edition(
            edition,
            kinds=("poster",),
            force=True,
            generator=fake_generator,
            uploader=uploader,
        )
        second = _groups(edition_id)[0].logo_image_id

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
        edition = db.session.get(Competition, edition_id)
        results = generate_for_edition(
            edition, generator=flaky_generator, uploader=uploader
        )

    errors = [r for r in results if r.get("error")]
    assert len(errors) == 1
    assert "image API exploded" in errors[0]["error"]

    with app.app_context():
        linked = [
            d
            for d in _groups(edition_id)
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


# ── attach local files ───────────────────────────────────────────────────────


def _png(tmp_path, name, size):
    path = tmp_path / name
    path.write_bytes(make_image_bytes(size))
    return path


def _group(group_id):
    db.session.expire_all()
    return db.session.get(CompetitionGroup, group_id)


def test_attach_file_publishes_a_local_file_to_a_v2_group(app, tmp_path):
    group_id = _make_division(app, name="1.ª Divisão")
    uploader = FakeUploader()
    path = _png(tmp_path, "poster.png", POSTER_SIZE)

    info = attach_file(_group(group_id), "poster", path, uploader=uploader, stamp="20261030090000")

    assert info["file"] == str(path)
    assert info["was_resized"] is False
    assert info["object_key"] == "Division/20261030090000_logo_image_id.png"
    assert _group(group_id).logo_image_id == info["image_id"]
    assert dimensions(uploader.uploads[info["object_key"]]) == POSTER_SIZE


def test_attach_file_keeps_existing_artwork_unless_forced(app, tmp_path):
    group_id = _make_division(app)
    uploader = FakeUploader()
    path = _png(tmp_path, "banner.png", (1280, 294))

    first = attach_file(_group(group_id), "banner", path, uploader=uploader)
    again = attach_file(_group(group_id), "banner", path, uploader=uploader)
    assert again["skipped"].startswith("already has artwork")
    assert _group(group_id).large_picture_id == first["image_id"]
    assert len(uploader.uploads) == 1

    forced = attach_file(_group(group_id), "banner", path, force=True, uploader=uploader)
    assert forced["image_id"] != first["image_id"]
    assert forced["was_resized"] is True
    assert _group(group_id).large_picture_id == forced["image_id"]
    assert len(uploader.uploads) == 2
    assert dimensions(uploader.uploads[forced["object_key"]]) == BANNER_SIZE


def test_attach_file_refuses_missing_files_bad_kinds_and_unknown_groups(app, tmp_path):
    group_id = _make_division(app)
    uploader = FakeUploader()

    with pytest.raises(ArtworkError, match="could not read"):
        attach_file(_group(group_id), "poster", tmp_path / "missing.png", uploader=uploader)
    with pytest.raises(ArtworkError, match="unknown artwork kind"):
        attach_file(_group(group_id), "cover", _png(tmp_path, "x.png", POSTER_SIZE), uploader=uploader)
    with pytest.raises(ArtworkError, match="was not found"):
        load_group(999_999_999)
    with pytest.raises(ArtworkError, match="was not found"):
        load_group("abc")
    assert uploader.uploads == {}
    assert (_group(group_id).logo_image_id, _group(group_id).large_picture_id) == (None, None)


def test_attach_manifest_commits_each_image_and_isolates_failures(app, tmp_path):
    comp = f.competition(name="Teams manifest")
    stg = f.stage(comp)
    first = f.group(stg, tier=1, name="1.ª Divisão").id
    second = f.group(stg, tier=2, name="2.ª Divisão").id
    db.session.commit()
    uploader = FakeUploader()
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    manifest = [
        {"group_id": first, "kind": "poster", "file": str(_png(tmp_path, "p1.png", POSTER_SIZE))},
        {"group_id": first, "kind": "banner", "file": str(_png(tmp_path, "b1.png", BANNER_SIZE))},
        {"group_id": second, "kind": "poster", "file": str(broken)},
        {"group_id": 999_999_999, "kind": "banner", "file": str(_png(tmp_path, "b2.png", BANNER_SIZE))},
        {"group_id": second, "kind": "banner"},
    ]

    results = attach_manifest(manifest, uploader=uploader)

    assert [bool(r.get("error")) for r in results] == [False, False, True, True, True]
    assert "could not read image" in results[2]["error"]
    assert "was not found" in results[3]["error"]
    assert "group_id or group_ids" in results[4]["error"]
    assert len(uploader.uploads) == 2
    # the two good images are committed (visible to a fresh session), the failed group untouched
    db.session.remove()
    assert (_group(first).logo_image_id, _group(first).large_picture_id) == (results[0]["image_id"], results[1]["image_id"])
    assert (_group(second).logo_image_id, _group(second).large_picture_id) == (None, None)


def test_cli_attach_artwork_single_file(app, tmp_path, monkeypatch):
    group_id = _make_division(app)
    uploader = FakeUploader()
    monkeypatch.setattr(artwork, "_upload_to_gcs", uploader)
    path = _png(tmp_path, "poster.png", POSTER_SIZE)

    comp_id = _group(group_id).stage.competition_id
    result = app.test_cli_runner().invoke(
        args=["attach-artwork", "--competition-id", str(comp_id), "--group-id", str(group_id), "--kind", "poster", "--file", str(path)]
    )

    assert result.exit_code == 0, result.output
    (info,) = json.loads(result.output)
    assert info["division_id"] == group_id and info["kind"] == "poster"
    assert _group(group_id).logo_image_id == info["image_id"]
    assert list(uploader.uploads) == [info["object_key"]]


def test_cli_attach_artwork_manifest_resolves_files_beside_it_and_reports_failures(app, tmp_path, monkeypatch):
    comp = f.competition(name="Teams manifest cli")
    stg = f.stage(comp)
    first = f.group(stg, tier=1, name="1.ª Divisão").id
    second = f.group(stg, tier=2, name="2.ª Divisão").id
    db.session.commit()
    uploader = FakeUploader()
    monkeypatch.setattr(artwork, "_upload_to_gcs", uploader)
    folder = tmp_path / "artwork"
    folder.mkdir()
    _png(folder, "d1_poster.png", POSTER_SIZE)
    _png(folder, "d1_banner.png", (1024, 340))
    manifest = folder / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {"group_id": first, "kind": "poster", "file": "d1_poster.png"},
                {"group_id": first, "kind": "banner", "file": "d1_banner.png"},
                {"group_id": second, "kind": "poster", "file": "does_not_exist.png"},
            ]
        )
    )

    result = app.test_cli_runner().invoke(args=["attach-artwork", "--competition-id", str(comp.id), "--manifest", str(manifest)])

    assert result.exit_code == 1, result.output
    assert "1 image(s) failed" in result.output
    assert "cover-cropped" in result.output  # the 1024x340 banner was resized
    body = result.output[: result.output.rindex("]") + 1]
    results = json.loads(body)
    assert [bool(r.get("error")) for r in results] == [False, False, True]
    assert results[0]["file"] == str(folder / "d1_poster.png")
    assert (_group(first).logo_image_id, _group(first).large_picture_id) == (results[0]["image_id"], results[1]["image_id"])
    assert _group(second).logo_image_id is None
    assert len(uploader.uploads) == 2


def test_cli_attach_artwork_wants_one_mode_and_a_competition(app, tmp_path):
    runner = app.test_cli_runner()
    manifest = tmp_path / "m.json"
    manifest.write_text("[]")
    assert runner.invoke(args=["attach-artwork", "--competition-id", "1"]).exit_code == 2
    no_comp = runner.invoke(args=["attach-artwork", "--manifest", str(manifest)])
    assert no_comp.exit_code == 2 and "--competition-id" in no_comp.output
    mixed = runner.invoke(args=["attach-artwork", "--competition-id", "1", "--manifest", str(manifest), "--group-id", "1"])
    assert mixed.exit_code == 2 and "not both" in mixed.output
    empty = runner.invoke(args=["attach-artwork", "--competition-id", "1", "--manifest", str(manifest)])
    assert empty.exit_code == 0 and json.loads(empty.output) == []


def test_groups_of_another_competition_are_refused_before_any_file_is_touched(app, tmp_path, monkeypatch):
    ours = f.competition(format="teams", name="Teams 27")
    mine = f.group(f.stage(ours), tier=1, name="1.ª Divisão").id
    theirs = f.group(f.stage(f.competition(name="22ª Edição")), tier=1, name="1ª Divisão").id
    db.session.commit()
    uploader = FakeUploader()
    monkeypatch.setattr(artwork, "_upload_to_gcs", uploader)
    missing = tmp_path / "never_read.png"  # does not exist: proves the guard runs before the file is read

    with pytest.raises(ArtworkError, match=f"group {theirs} .* belongs to competition .*, not {ours.id}"):
        load_group(theirs, competition_id=ours.id)
    assert load_group(mine, competition_id=ours.id).id == mine

    results = attach_manifest(
        [
            {"group_id": theirs, "kind": "poster", "file": str(missing)},
            {"group_id": mine, "kind": "poster", "file": str(_png(tmp_path, "ok.png", POSTER_SIZE))},
        ],
        competition_id=ours.id,
    )
    assert "belongs to competition" in results[0]["error"] and "image_id" in results[1]
    assert _group(theirs).logo_image_id is None and _group(mine).logo_image_id == results[1]["image_id"]

    single = app.test_cli_runner().invoke(
        args=["attach-artwork", "--competition-id", str(ours.id), "--group-id", str(theirs), "--kind", "banner", "--file", str(_png(tmp_path, "b.png", BANNER_SIZE))]
    )
    assert single.exit_code == 1 and "belongs to competition" in single.output
    assert _group(theirs).large_picture_id is None
    assert len(uploader.uploads) == 1  # only the manifest's good entry (the service-level attach above used uploader=None → the patched GCS upload)


# ── shared artwork: one upload for many groups ───────────────────────────────


def _shuffle_like(stage_count=3, groups_per_stage=2):
    comp = f.competition(format="shuffle", name="Shuffle shared")
    ids = []
    for n in range(1, stage_count + 1):
        stg = f.stage(comp, number=n)
        ids += [f.group(stg, tier=t, name=f"Divisão {t}").id for t in range(1, groups_per_stage + 1)]
    db.session.commit()
    return comp.id, ids


def test_group_ids_entry_uploads_once_and_links_every_group(app, tmp_path):
    comp_id, ids = _shuffle_like()
    uploader = FakeUploader()
    manifest = [
        {"group_ids": ids, "kind": "poster", "file": str(_png(tmp_path, "poster.png", POSTER_SIZE))},
        {"group_ids": ids, "kind": "banner", "file": str(_png(tmp_path, "banner.png", BANNER_SIZE))},
    ]

    results = attach_manifest(manifest, uploader=uploader, competition_id=comp_id)

    assert [r.get("error") for r in results] == [None, None]
    assert len(uploader.uploads) == 2  # one object per entry, not per group
    poster, banner = results
    assert poster["division_ids"] == ids and poster["skipped_group_ids"] == []
    assert Image.query.filter(Image.object_key.in_([poster["object_key"], banner["object_key"]])).count() == 2
    db.session.remove()
    for group_id in ids:
        assert (_group(group_id).logo_image_id, _group(group_id).large_picture_id) == (poster["image_id"], banner["image_id"])


def test_group_ids_entry_skips_groups_that_already_have_artwork_unless_forced(app, tmp_path):
    comp_id, ids = _shuffle_like(stage_count=2)
    uploader = FakeUploader()
    path = _png(tmp_path, "poster.png", POSTER_SIZE)
    own = attach_file(_group(ids[1]), "poster", path, uploader=uploader)

    shared = attach_manifest([{"group_ids": ids, "kind": "poster", "file": str(path)}], uploader=uploader, competition_id=comp_id)[0]
    assert shared["division_ids"] == [i for i in ids if i != ids[1]] and shared["skipped_group_ids"] == [ids[1]]
    assert len(uploader.uploads) == 2
    assert _group(ids[1]).logo_image_id == own["image_id"]
    assert all(_group(i).logo_image_id == shared["image_id"] for i in ids if i != ids[1])

    nothing = attach_manifest([{"group_ids": ids, "kind": "poster", "file": str(tmp_path / "never.png")}], uploader=uploader, competition_id=comp_id)[0]
    assert nothing["skipped"].startswith("already has artwork") and len(uploader.uploads) == 2  # file never read

    forced = attach_manifest([{"group_ids": ids, "kind": "poster", "file": str(path)}], force=True, uploader=uploader, competition_id=comp_id)[0]
    assert forced["division_ids"] == ids and forced["skipped_group_ids"] == [] and len(uploader.uploads) == 3
    assert all(_group(i).logo_image_id == forced["image_id"] for i in ids)


def test_group_ids_entry_is_all_or_nothing_under_the_competition_guard(app, tmp_path):
    comp_id, ids = _shuffle_like(stage_count=1, groups_per_stage=3)
    foreign = f.group(f.stage(f.competition(name="Other")), tier=1, name="1ª Divisão").id
    db.session.commit()
    uploader = FakeUploader()
    missing = str(tmp_path / "never_read.png")
    manifest = [
        {"group_ids": ids + [foreign], "kind": "poster", "file": missing},
        {"group_ids": ids + [999_999_999], "kind": "poster", "file": missing},
        {"group_ids": [], "kind": "poster", "file": missing},
        {"group_id": ids[0], "group_ids": ids, "kind": "poster", "file": missing},
    ]

    results = attach_manifest(manifest, uploader=uploader, competition_id=comp_id)

    assert "belongs to competition" in results[0]["error"] and results[0]["division_ids"] == ids + [foreign]
    assert "was not found" in results[1]["error"]
    assert "group_id or group_ids" in results[2]["error"] and "group_id or group_ids" in results[3]["error"]
    assert uploader.uploads == {}
    assert all(_group(i).logo_image_id is None for i in ids + [foreign])


def test_cli_manifest_accepts_group_ids(app, tmp_path, monkeypatch):
    comp_id, ids = _shuffle_like(stage_count=2)
    uploader = FakeUploader()
    monkeypatch.setattr(artwork, "_upload_to_gcs", uploader)
    _png(tmp_path, "shuffle_poster.png", POSTER_SIZE)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([{"group_ids": ids, "kind": "poster", "file": "shuffle_poster.png"}]))

    result = app.test_cli_runner().invoke(args=["attach-artwork", "--competition-id", str(comp_id), "--manifest", str(manifest)])

    assert result.exit_code == 0, result.output
    (info,) = json.loads(result.output)
    assert info["division_ids"] == ids and len(uploader.uploads) == 1
    assert all(_group(i).logo_image_id == info["image_id"] for i in ids)
