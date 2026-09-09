import logging
import textwrap

from conda_forge_tick.migrators import GenericV0ToV1Migrator
from conda_forge_tick.migrators.v0_to_v1 import (
    _duplicate_top_level_key_reasons,
    _join_folded_quoted_scalars,
    _malformed_output_reasons,
)

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

# A duplicate `script:` key, once per selector - the common `key: val
# # [selector]` / `key: val2  # [other-selector]` pattern conda-forge
# recipes rely on. Note this must actually carry a selector: an unselectored
# duplicate key (e.g. two unconditional `build:` blocks) doesn't merge into
# anything - crm's ALLOW_DUPLICATE_KEYS just permits it through, and the
# genuinely-duplicate key survives into v1 output, which
# _malformed_output_reasons correctly flags as broken.
DUPLICATE_KEY_RECIPE = CLEAN_RECIPE.replace(
    "  script: python setup.py install\n",
    "  script: python setup.py install  # [not win]\n"
    "  script: python setup.py install --old-and-unmanageable  # [win]\n",
)

# A real pattern (from r-loose.rock): two full, unconditional `build:`
# sections with no selector on either - most likely a copy-paste mistake in
# the source recipe (one declares `noarch: generic`, the other doesn't).
UNSELECTORED_DUPLICATE_BUILD_RECIPE = CLEAN_RECIPE.replace(
    "build:\n  number: 0\n  script: python setup.py install\n",
    "build:\n  number: 0\n  noarch: generic\n\n"
    "build:\n  number: 0\n  script: python setup.py install\n",
)

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

# `GPL (>= 2)` is a legacy license string crm's own SPDX matcher can't map at
# all (it just warns "Could not patch unrecognized license" and leaves the
# field as-is) - but this repo's own LicenseMigrator mapping already knows
# `GPL (>= 2)` -> `GPL-2.0-or-later`, so GenericV0ToV1Migrator normalizes it
# before crm ever sees it.
UNRECOGNIZED_LICENSE_RECIPE = CLEAN_RECIPE.replace(
    "  license: MIT\n", "  license: GPL (>= 2)\n"
)

# CRAN's "Unlimited" license (real example: r-presenceabsence). This is
# an R-specific mapping that lives in RV0ToV1Migrator._to_spdx, not here - see
# test_r_v0_to_v1.py for the positive case; the negative case below confirms
# it stays confined to the R subclass.
LICENSEREF_UNLIMITED_RECIPE = CLEAN_RECIPE.replace(
    "  license: MIT\n", "  license: LicenseRef-Unlimited\n"
)

# A real pattern (from r-icenreg): an already-valid compound SPDX
# expression - two real SPDX ids joined by "OR". crm's matcher declines to
# touch *any* license string containing AND/OR/WITH on purpose (to avoid
# mangling a compound expression), so it warns "Could not patch unrecognized
# license" even though this one needs no fixing at all.
COMPOUND_OR_LICENSE_RECIPE = CLEAN_RECIPE.replace(
    "  license: MIT\n", "  license: LGPL-2.0-only OR LGPL-2.1-only\n"
)

# Same shape, but the left side isn't a real SPDX id - crm is right to warn
# here, and we shouldn't wave it through just because it looks like the
# COMPOUND_OR_LICENSE_RECIPE pattern.
INVALID_COMPOUND_OR_LICENSE_RECIPE = CLEAN_RECIPE.replace(
    "  license: MIT\n", "  license: NotARealLicense OR LGPL-2.1-only\n"
)

# A YAML-folded multi-line double-quoted `summary:` whose continuation line
# is itself shaped like `'word' more: words` - crm's line-based reader
# misparses that continuation as its own key/value pair and crashes with a
# raw ParsingException instead of a clean warning (real example: r-stringi's
# `about/summary`, a long description CRAN wraps across two physical lines).
FOLDED_SUMMARY_RECIPE = CLEAN_RECIPE.replace(
    "  summary: Amazon Web Services Library\n",
    "  summary: \"Amazon Web Services Library, supports 'S3', 'EC2',\n"
    "    'SQS' and more. Available regions: us-east-1.\"\n",
)

# A real pattern (from r-kedd): a duplicate `license_file` key, once per
# platform selector, where *both* values contain their own `environ["..."]`
# call. crm's duplicate-key ternary merge mishandles a value that already
# contains a templated expression, producing malformed, mismatched-brace v1
# syntax with no warning at all.
DUPLICATE_ENVIRON_LICENSE_FILE_RECIPE = CLEAN_RECIPE.replace(
    "  summary: Amazon Web Services Library\n",
    "  summary: Amazon Web Services Library\n"
    "  license_file: '{{ environ[\"PREFIX\"] }}/share/licenses/MIT'  # [unix]\n"
    "  license_file: '{{ environ[\"PREFIX\"] }}\\share\\licenses\\MIT'  # [win]\n",
)

# Two separate `environ[...]` calls merged into the *same* duplicated value.
# `_restore_environ_calls` used to only handle the first placeholder in a
# literal, leaving a second one to get blindly expanded into a `${{ ... }}`
# nested *inside* the already-templated expression.
MULTI_ENVIRON_LICENSE_FILE_RECIPE = CLEAN_RECIPE.replace(
    "  summary: Amazon Web Services Library\n",
    "  summary: Amazon Web Services Library\n"
    '  license_file: \'{{ environ["PREFIX"] }}/{{ environ["PKG_NAME"] }}/L\'  # [unix]\n'
    '  license_file: \'{{ environ["PREFIX"] }}\\{{ environ["PKG_NAME"] }}\\L\'  # [win]\n',
)


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


def test_duplicate_top_level_key_reasons_flags_unselectored_duplicate():
    reasons = _duplicate_top_level_key_reasons(UNSELECTORED_DUPLICATE_BUILD_RECIPE)
    assert len(reasons) == 1
    assert "top-level `build:` section appears 2 times" in reasons[0]


def test_duplicate_top_level_key_reasons_ignores_selectored_leaf_duplicates():
    # `script:` is duplicated too, but each occurrence carries a selector -
    # the legitimate, crm-mergeable idiom, not an authoring mistake.
    assert _duplicate_top_level_key_reasons(DUPLICATE_KEY_RECIPE) == []


def test_duplicate_top_level_key_reasons_no_false_positive_on_clean_recipe():
    assert _duplicate_top_level_key_reasons(CLEAN_RECIPE) == []


def test_convert_blocks_on_unselectored_duplicate_top_level_section():
    # Caught before crm even runs, with a clearer reason than crm's own
    # DuplicateKeyException would give (see _malformed_output_reasons).
    v1_content, blocking = GenericV0ToV1Migrator()._convert(
        UNSELECTORED_DUPLICATE_BUILD_RECIPE
    )
    assert v1_content is None
    assert blocking == [
        "top-level `build:` section appears 2 times with no selector to "
        "distinguish them - likely an authoring mistake in the source "
        "recipe that needs manual review"
    ]


def test_convert_preprocesses_environ_syntax():
    v1_content, blocking = GenericV0ToV1Migrator()._convert(ENVIRON_RECIPE)
    assert blocking == []
    assert v1_content is not None
    assert 'env.get("PREFIX")' in v1_content
    assert "environ[" not in v1_content


def test_join_folded_quoted_scalars_joins_multiline_value():
    joined = _join_folded_quoted_scalars(FOLDED_SUMMARY_RECIPE)
    assert (
        "  summary: \"Amazon Web Services Library, supports 'S3', 'EC2',"
        " 'SQS' and more. Available regions: us-east-1.\"\n"
    ) in joined
    # The two folded lines become one - everything else is untouched.
    assert joined.count("\n") == FOLDED_SUMMARY_RECIPE.count("\n") - 1
    assert "  license: MIT\n" in joined


def test_join_folded_quoted_scalars_leaves_single_line_values_alone():
    assert _join_folded_quoted_scalars(CLEAN_RECIPE) == CLEAN_RECIPE


def test_convert_fixes_folded_quoted_scalar_crash():
    # Without _join_folded_quoted_scalars, crm raises a raw ParsingException
    # on this shape rather than a clean, actionable warning.
    v1_content, blocking = GenericV0ToV1Migrator()._convert(FOLDED_SUMMARY_RECIPE)
    assert blocking == []
    assert v1_content is not None
    assert (
        "summary: \"Amazon Web Services Library, supports 'S3', 'EC2',"
        " 'SQS' and more. Available regions: us-east-1.\""
    ) in v1_content


def test_convert_ignores_corrected_legacy_license():
    v1_content, blocking = GenericV0ToV1Migrator()._convert(LEGACY_LICENSE_RECIPE)
    assert blocking == []
    assert v1_content is not None
    assert "license: GPL-2.0-only" in v1_content


def test_convert_normalizes_unrecognized_legacy_license():
    # Without normalization, crm can't map this string at all and warns
    # "Could not patch unrecognized license" - not on the ignore-list, and
    # rightly so, since crm leaves the original (non-SPDX) string in place
    # in that case. GenericV0ToV1Migrator normalizes it first instead, so
    # crm never has a reason to warn.
    v1_content, blocking = GenericV0ToV1Migrator()._convert(UNRECOGNIZED_LICENSE_RECIPE)
    assert blocking == []
    assert v1_content is not None
    assert "license: GPL-2.0-or-later" in v1_content


def test_to_spdx_delegates_to_shared_license_mapping():
    assert GenericV0ToV1Migrator()._to_spdx("GPL-2") == "GPL-2.0-only"
    # Unrecognized strings are a no-op, same as the shared _to_spdx().
    assert GenericV0ToV1Migrator()._to_spdx("nonsense") == "nonsense"


def test_convert_does_not_know_r_specific_licenseref_unlimited():
    # "LicenseRef-Unlimited" -> "Unlimited" is an R-specific mapping (CRAN's
    # "Unlimited" license) that lives in RV0ToV1Migrator._to_spdx, not here.
    # GenericV0ToV1Migrator has no idea it's safe to rewrite, so it still
    # blocks. See test_r_v0_to_v1.py for the positive (RV0ToV1Migrator) case.
    v1_content, blocking = GenericV0ToV1Migrator()._convert(LICENSEREF_UNLIMITED_RECIPE)
    assert v1_content is None
    assert len(blocking) == 1
    assert "Could not patch unrecognized license" in blocking[0]


def test_is_safe_compound_spdx_expression():
    migrator = GenericV0ToV1Migrator()
    assert migrator._is_safe_compound_spdx_expression("LGPL-2.0-only OR LGPL-2.1-only")
    assert migrator._is_safe_compound_spdx_expression("MPL-2.0 OR GPL-3.0-or-later")
    # One side isn't a real SPDX id.
    assert not migrator._is_safe_compound_spdx_expression("NotARealLicense OR MIT")
    # Not a compound expression at all.
    assert not migrator._is_safe_compound_spdx_expression("MIT")
    # More than two parts is out of scope.
    assert not migrator._is_safe_compound_spdx_expression(
        "MIT OR Apache-2.0 OR BSD-3-Clause"
    )


def test_convert_passes_through_valid_compound_or_license():
    v1_content, blocking = GenericV0ToV1Migrator()._convert(COMPOUND_OR_LICENSE_RECIPE)
    assert blocking == []
    assert v1_content is not None
    assert "license: LGPL-2.0-only OR LGPL-2.1-only" in v1_content


def test_convert_still_blocks_invalid_compound_or_license():
    v1_content, blocking = GenericV0ToV1Migrator()._convert(
        INVALID_COMPOUND_OR_LICENSE_RECIPE
    )
    assert v1_content is None
    assert len(blocking) == 1
    assert "Could not patch unrecognized license" in blocking[0]


def test_convert_fixes_duplicate_environ_license_file_merge():
    v1_content, blocking = GenericV0ToV1Migrator()._convert(
        DUPLICATE_ENVIRON_LICENSE_FILE_RECIPE
    )
    assert blocking == []
    assert v1_content is not None
    # Exactly one well-formed `${{ ... }}` block for license_file, not the
    # malformed, mismatched-brace output crm produces without the fix.
    license_file_lines = [
        line for line in v1_content.splitlines() if "license_file" in line
    ]
    assert len(license_file_lines) == 1
    license_file_line = license_file_lines[0]
    assert license_file_line.count("${{") == 1
    assert license_file_line.count("}}") == 1
    assert 'env.get("PREFIX")' in license_file_line
    assert "if win" in license_file_line and "if unix" in license_file_line
    assert "environ[" not in v1_content


def test_convert_fixes_multiple_environ_calls_in_one_duplicated_value():
    v1_content, blocking = GenericV0ToV1Migrator()._convert(
        MULTI_ENVIRON_LICENSE_FILE_RECIPE
    )
    assert blocking == []
    assert v1_content is not None
    license_file_lines = [
        line for line in v1_content.splitlines() if "license_file" in line
    ]
    assert len(license_file_lines) == 1
    license_file_line = license_file_lines[0]
    # Exactly one top-level `${{ ... }}` block - not one nested inside
    # another because a second placeholder got expanded in place.
    assert license_file_line.count("${{") == 1
    assert license_file_line.count("}}") == 1
    # Once per branch (win/unix each build their own path from both vars) -
    # not nested inside one another.
    assert license_file_line.count('env.get("PREFIX")') == 2
    assert license_file_line.count('env.get("PKG_NAME")') == 2
    assert "environ[" not in v1_content
    assert _malformed_output_reasons(v1_content) == []


def test_malformed_output_reasons_catches_mismatched_braces():
    # A real (simplified) example of what crm produces for a duplicate-key
    # merge gone wrong, with no warning attached at all.
    broken = (
        'license_file: ${{ env.get("PREFIX") }}/GPL if unix else '
        "env.get(\"PREFIX\") }}\\GPL if win else '' }}\n"
    )
    reasons = _malformed_output_reasons(broken)
    assert reasons
    assert any("unmatched" in r for r in reasons)


def test_malformed_output_reasons_catches_nested_braces():
    nested = (
        "license_file: ${{ ('${{ env.get(\"PREFIX\") }}/' ~ "
        "env.get(\"PKG_NAME\") ~ '/L') if unix else '' }}\n"
    )
    reasons = _malformed_output_reasons(nested)
    assert reasons
    assert any("nested" in r for r in reasons)


def test_malformed_output_reasons_catches_duplicate_keys():
    duplicate = "about:\n  license_file:\n    - a\n  license_file:\n    - b\n"
    reasons = _malformed_output_reasons(duplicate)
    assert reasons
    assert any("does not re-parse" in r for r in reasons)


def test_malformed_output_reasons_no_false_positive_on_good_output():
    good = textwrap.dedent(
        """\
        schema_version: 1
        about:
          license_file: ${{ (env.get("PREFIX") ~ '/GPL-3') if unix else (env.get("PREFIX") ~ '\\\\GPL-3') if win else '' }}
        requirements:
          build:
            - if: not win
              then: ${{ compiler('c') }}
        """
    )
    assert _malformed_output_reasons(good) == []


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


def test_build_script_review_reasons_is_a_no_op_by_default():
    # Base class knows nothing package-specific; subclasses (e.g.
    # RV0ToV1Migrator) layer their own checks on top - see
    # tests/test_r_v0_to_v1.py.
    assert GenericV0ToV1Migrator()._build_script_review_reasons("anything") == []


def test_migrate_does_not_warn_about_build_sh_by_default(tmp_path, caplog):
    (tmp_path / "meta.yaml").write_text(CLEAN_RECIPE)
    (tmp_path / "build.sh").write_text("#!/bin/bash\n$PYTHON setup.py install\n")

    with caplog.at_level(logging.WARNING):
        GenericV0ToV1Migrator().migrate(str(tmp_path), {"name": "boto"})

    assert (tmp_path / "recipe.yaml").exists()
    assert "manual review" not in caplog.text
