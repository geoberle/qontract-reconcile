import pytest

from reconcile.test.change_owners.fixtures import build_test_datafile


def test_bundle_file_change_sha_presence_on_change() -> None:
    change = build_test_datafile(
        filepath="/another/path.yml",
        content={"hey": "ho"},
        schema="/my/schema.yml",
    ).create_bundle_change({"hey": "you"})

    assert change.new_content_sha
    assert change.old_content_sha


def test_bundle_file_change_sha_presence_on_move() -> None:
    changes = list(
        build_test_datafile(
            filepath="/another/path.yml",
            content={"hey": "ho"},
            schema="/my/schema.yml",
        ).move("/new/path.yml")
    )

    for c in changes:
        if c.is_file_creation():
            assert c.new_content_sha
            assert not c.old_content_sha
        elif c.is_file_deletion():
            assert not c.new_content_sha
            assert c.old_content_sha
        else:
            pytest.fail("Unexpected change")
