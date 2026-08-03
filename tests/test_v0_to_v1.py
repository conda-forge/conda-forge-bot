import logging
import textwrap

from conda_forge_tick.migrators import GenericV0ToV1Migrator

CLEAN_RECIPE = textwrap.dedent(
    """\
    {% set name = "boto" %}
    {% set version = "2.49.0" %}

    package:
      name: {{ name|lower }}
      version: {{ version }}

    source:
      fn: {{ name }}-{{ version }}.tar.gz
      url: https://pypi.org/packages/source/{{ name[0] }}/{{ name }}/{{ name }}-{{ version }}.tar.gz
      sha256: ea0d3b40a2d852767be77ca343b58a9e3a4b00d9db440efb8da74b4e58025e5a

    requirements:
      host:
        - python
      run:
        - python

    build:
      number: 0
      script: python setup.py install

    test:
      commands:
        - s3put -h
      imports:
        - boto

    about:
      home: https://github.com/boto/boto/
      license: MIT
      summary: Amazon Web Services Library
    """
)

# Only difference from CLEAN_RECIPE: an `about/license_family` field. crm drops
# the field and emits a warning that's on GenericV0ToV1Migrator's ignore-list,
# so this should still be treated as a clean conversion.
IGNORED_WARNING_RECIPE = CLEAN_RECIPE.replace(
    "  license: MIT\n",
    "  license: MIT\n  license_family: MIT\n",
)

# Replaces the tarball source with an `svn_url`, which crm converts but flags
# with a non-ignorable warning ("SVN packages are no longer supported").
BLOCKING_WARNING_RECIPE = CLEAN_RECIPE.replace(
    "source:\n"
    "  fn: {{ name }}-{{ version }}.tar.gz\n"
    "  url: https://pypi.org/packages/source/{{ name[0] }}/{{ name }}/{{ name }}-{{ version }}.tar.gz\n"
    "  sha256: ea0d3b40a2d852767be77ca343b58a9e3a4b00d9db440efb8da74b4e58025e5a\n",
    "source:\n  svn_url: https://example.com/svn/boto\n  svn_rev: 123\n",
)

# Malformed YAML (an unterminated flow sequence) that crm can't parse at all,
# raising before any message table exists. Note a second top-level `build:`
# key would *not* trigger this: GenericV0ToV1Migrator passes
# `ALLOW_DUPLICATE_KEYS`, matching what the `crm convert` CLI always does,
# since that duplicate-key-with-different-selectors pattern is otherwise
# extremely common and legitimate in conda-forge recipes.
UNPARSABLE_RECIPE = "package: [name: boto\n"

# A second top-level `build:` key - the common `key: val  # [selector]` /
# `key: val2  # [other-selector]` pattern conda-forge recipes rely on.
DUPLICATE_KEY_RECIPE = CLEAN_RECIPE + "\nbuild:\n  number: 1\n"

# `{{ environ["PREFIX"] }}` (common in license_file fields, not just R/Bioconda
# recipes) needs crm's pre-processing step to become valid v1 syntax; without
# it, crm leaves behind invalid `${{ environ["PREFIX"] }}` with no warning.
ENVIRON_RECIPE = CLEAN_RECIPE.replace(
    "  summary: Amazon Web Services Library\n",
    '  summary: Amazon Web Services Library\n  license_file: {{ environ["PREFIX"] }}/LICENSE\n',
)

# `GPL-2` is a legacy, non-SPDX license string; crm's own SPDX correction
# pass patches it to `GPL-2.0-only` in the output (matching this repo's own
# LicenseMigrator mapping in migrators/license.py) and just logs the change.
LEGACY_LICENSE_RECIPE = CLEAN_RECIPE.replace("  license: MIT\n", "  license: GPL-2\n")


def test_convert_clean_recipe():
    v1_content, blocking = GenericV0ToV1Migrator()._convert(CLEAN_RECIPE)
    assert blocking == []
    assert v1_content is not None
    assert "schema_version: 1" in v1_content


def test_convert_ignores_known_safe_warnings():
    v1_content, blocking = GenericV0ToV1Migrator()._convert(IGNORED_WARNING_RECIPE)
    assert blocking == []
    assert v1_content is not None
    assert "schema_version: 1" in v1_content


def test_convert_allows_duplicate_keys():
    v1_content, blocking = GenericV0ToV1Migrator()._convert(DUPLICATE_KEY_RECIPE)
    assert blocking == []
    assert v1_content is not None
    assert "schema_version: 1" in v1_content


def test_convert_preprocesses_environ_syntax():
    v1_content, blocking = GenericV0ToV1Migrator()._convert(ENVIRON_RECIPE)
    assert blocking == []
    assert v1_content is not None
    assert 'env.get("PREFIX")' in v1_content
    assert "environ[" not in v1_content


def test_convert_ignores_corrected_legacy_license():
    v1_content, blocking = GenericV0ToV1Migrator()._convert(LEGACY_LICENSE_RECIPE)
    assert blocking == []
    assert v1_content is not None
    assert "license: GPL-2.0-only" in v1_content


def test_convert_blocks_on_unignored_warning():
    v1_content, blocking = GenericV0ToV1Migrator()._convert(BLOCKING_WARNING_RECIPE)
    assert v1_content is None
    assert len(blocking) == 1
    assert "SVN packages are no longer supported" in blocking[0]


def test_convert_blocks_on_parser_exception():
    v1_content, blocking = GenericV0ToV1Migrator()._convert(UNPARSABLE_RECIPE)
    assert v1_content is None
    assert len(blocking) == 1
    assert "ParsingException" in blocking[0]


def test_migrate_writes_recipe_yaml_and_removes_meta_yaml(tmp_path):
    (tmp_path / "meta.yaml").write_text(CLEAN_RECIPE)

    GenericV0ToV1Migrator().migrate(str(tmp_path), {"name": "boto"})

    assert not (tmp_path / "meta.yaml").exists()
    recipe_yaml = tmp_path / "recipe.yaml"
    assert recipe_yaml.exists()
    assert "schema_version: 1" in recipe_yaml.read_text()


def test_migrate_skips_recipe_not_safe_to_convert(tmp_path, caplog):
    (tmp_path / "meta.yaml").write_text(BLOCKING_WARNING_RECIPE)

    with caplog.at_level(logging.WARNING):
        GenericV0ToV1Migrator().migrate(str(tmp_path), {"name": "boto"})

    assert (tmp_path / "meta.yaml").read_text() == BLOCKING_WARNING_RECIPE
    assert not (tmp_path / "recipe.yaml").exists()
    assert "not safe to auto-convert" in caplog.text
    assert "boto" in caplog.text


def test_migrate_skips_unparsable_recipe(tmp_path):
    (tmp_path / "meta.yaml").write_text(UNPARSABLE_RECIPE)

    GenericV0ToV1Migrator().migrate(str(tmp_path), {"name": "boto"})

    assert (tmp_path / "meta.yaml").read_text() == UNPARSABLE_RECIPE
    assert not (tmp_path / "recipe.yaml").exists()


def test_migrate_no_op_when_meta_yaml_missing(tmp_path):
    GenericV0ToV1Migrator().migrate(str(tmp_path), {"name": "boto"})

    assert not (tmp_path / "recipe.yaml").exists()
    assert not (tmp_path / "meta.yaml").exists()
