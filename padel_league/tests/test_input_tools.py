import pytest
from datetime import datetime
from werkzeug.security import check_password_hash

from padel_league.tools import image_tools, tools
from padel_league.tools.input_tools import Field, Block, Tab, Form


class DummyRequest:
    """Mimics a Flask request for testing."""

    def __init__(self, form=None, files=None):
        self.form = form or {}
        self.files = files or DummyFiles()


class DummyFiles:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def getlist(self, name):
        return self.mapping.get(name, [])


class DummyFile:
    def __init__(self, filename, mimetype="image/png"):
        self.filename = filename
        self.mimetype = mimetype


@pytest.fixture
def simple_field():
    return Field("1", "TestModel", "My Label", "my_field", "Text", value="abc")


# ---------- Tests for Field ----------
def test_field_requires_label_name_type():
    with pytest.raises(ValueError):
        Field("1", "Model", None, "name", "Text")
    with pytest.raises(ValueError):
        Field("1", "Model", "Label", None, "Text")
    with pytest.raises(ValueError):
        Field("1", "Model", "Label", "name", None)


def test_invalid_type_raises():
    with pytest.raises(ValueError):
        Field("1", "Model", "Label", "name", "InvalidType")


def test_get_field_dict(simple_field):
    d = simple_field.get_field_dict()
    assert d["type"] == "Text"
    assert d["label"] == "My Label"
    assert d["name"] == "my_field"


def test_set_value_text(simple_field):
    req = DummyRequest(form={"my_field": "new_value"})
    simple_field.set_value(req)
    assert simple_field.value == "new_value"


def test_set_boolean_value():
    f = Field("1", "Model", "Bool Label", "is_active", "Boolean")
    f.set_boolean_value(DummyRequest(form={"is_active": "true"}))
    assert f.value is True
    f.set_boolean_value(DummyRequest(form={"is_active": "false"}))
    assert f.value is False


def test_set_password_value():
    f = Field("1", "Model", "Password", "pwd", "Password")
    req = DummyRequest(form={"pwd": "secret"})
    f.set_value(req)
    assert check_password_hash(f.value, "secret")


def test_set_date_value(monkeypatch):
    f = Field("1", "Model", "Date Label", "my_date", "Date")
    monkeypatch.setattr(tools, "str_to_date", lambda s: datetime(2020, 1, 1))
    req = DummyRequest(form={"my_date": "2020-01-01"})
    f.set_value(req)
    assert f.value == datetime(2020, 1, 1)


def test_set_datetime_value(monkeypatch):
    f = Field("1", "Model", "DateTime Label", "my_dt", "DateTime")
    monkeypatch.setattr(tools, "str_to_datetime", lambda s: datetime(2021, 1, 1, 10, 0))
    req = DummyRequest(form={"my_dt": "2021-01-01 10:00"})
    f.set_value(req)
    assert f.value == datetime(2021, 1, 1, 10, 0)


def test_set_relationship_value():
    f = Field("1", "Model", "Relation", "rel_ids", "ManyToMany")

    class DummyForm(dict):
        def getlist(self, key):
            return self[key]

    req = DummyRequest(form=DummyForm({"rel_ids": ["1", "2"]}))
    f.set_value(req)
    assert f.value == [1, 2]


def test_set_picture_value(monkeypatch):
    f = Field("1", "Model", "Pic", "pic", "Picture")

    dummy_file = DummyFile("test.png")

    monkeypatch.setattr(
        image_tools, "file_handler", lambda fs: (dummy_file, "test.png")
    )
    monkeypatch.setattr(image_tools, "save_file", lambda f, k: True)

    class DummyImage:
        id = 123

        def __init__(self, **kwargs):
            pass

        def create(self):
            return True

    monkeypatch.setattr("padel_league.tools.input_tools.Image", DummyImage)

    files = DummyFiles({"pic": [dummy_file]})
    req = DummyRequest(files=files)
    f.set_value(req)
    assert f.value == 123


def test_set_multiple_picture_value(monkeypatch):
    f = Field("1", "Model", "Pics", "pics", "MultiplePictures")

    dummy_file = DummyFile("img.png")

    monkeypatch.setattr(image_tools, "file_handler", lambda fs: (dummy_file, "img.png"))
    monkeypatch.setattr(image_tools, "save_file", lambda f, k: True)

    class DummyImage:
        id = 42

        def __init__(self, **kwargs):
            pass

        def create(self):
            return True

    monkeypatch.setattr("padel_league.tools.input_tools.Image", DummyImage)

    files = DummyFiles({"pics": [dummy_file, dummy_file]})
    req = DummyRequest(files=files)
    f.set_value(req)
    assert f.value == [42, 42]


# ---------- Tests for Block ----------
def test_block_requires_fields():
    with pytest.raises(ValueError):
        Block("test", None)
    with pytest.raises(ValueError):
        Block(None, [])
    with pytest.raises(ValueError):
        Block("test", ["not_a_field"])


def test_block_get_block_dict(simple_field):
    b = Block("info_block", [simple_field])
    d = b.get_block_dict()
    assert d["name"] == "info_block"
    assert simple_field in d["fields"]


# ---------- Tests for Tab ----------
def test_tab_requires_fields():
    with pytest.raises(ValueError):
        Tab("tab1", None)
    with pytest.raises(ValueError):
        Tab(None, [])
    with pytest.raises(ValueError):
        Tab("tab1", ["not_a_field"])


def test_tab_get_tab_dict(simple_field):
    t = Tab("My Tab", [simple_field])
    d = t.get_tab_dict()
    assert d["title"] == "My Tab"
    assert simple_field in d["fields"]


# ---------- Tests for Form ----------
def test_add_block_and_tab(simple_field):
    form = Form()
    block = Block("info_block", [simple_field])
    tab = Tab("Main", [simple_field])

    form.add_block(block)
    form.add_tab(tab)

    assert block in form.blocks
    assert tab in form.tabs
    assert simple_field in form.fields


def test_add_block_invalid(monkeypatch, simple_field):
    form = Form()
    with pytest.raises(ValueError):
        form.add_block("not_a_block")

    with pytest.raises(ValueError):
        form.add_block(Block("invalid_block_name", [simple_field]))

    form.add_block(Block("picture_block", [simple_field]))
    with pytest.raises(ValueError):
        form.add_block(Block("picture_block", [simple_field]))  # duplicate name


def test_add_tab_invalid():
    form = Form()
    with pytest.raises(ValueError):
        form.add_tab("not_a_tab")


def test_get_form_dict(simple_field):
    form = Form()
    form.add_block(Block("info_block", [simple_field]))
    d = form.get_form_dict()
    assert "main" in d and "tabs" in d


def test_set_values(simple_field):
    form = Form()
    form.add_block(Block("info_block", [simple_field]))
    req = DummyRequest(form={"my_field": "hello"})
    values = form.set_values(req)
    assert values["my_field"] == "hello"
