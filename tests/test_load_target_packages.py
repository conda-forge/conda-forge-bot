from conda_forge_tick.migrators import core
from conda_forge_tick.migrators.core import load_target_packages


def test_load_target_packages_ignores_comments_and_duplicates(tmp_path, monkeypatch):
    (tmp_path / "targets.txt").write_text(
        "# This file lists the file feedstock\n"
        "  # indented comment\n"
        "numpy\n"
        "scipy  # trailing comment with pandas\n"
        "\n"
        "python matplotlib\n"
        "numpy\n"
        "scipy python\n"
    )
    monkeypatch.setattr(core, "MIGRATION_SUPPORT_DIRS", [tmp_path])

    assert load_target_packages("targets.txt") == {
        "numpy",
        "scipy",
        "python",
        "matplotlib",
    }
