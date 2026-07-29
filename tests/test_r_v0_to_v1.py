import textwrap
from pathlib import Path

import pytest

from conda_forge_tick.migrators import GenericV0ToV1Migrator, RV0ToV1Migrator

# A real, single-output R recipe using the compiler('c')/native/posix/m2w64
# templating that's near-universal in R feedstocks, plus the
# `{{ environ["PREFIX"] }}` license_file pattern.
MAGRITTR_RECIPE = textwrap.dedent(
    """\
    {% set version = "2.0.0" %}
    {% set posix = 'm2-' if win else '' %}
    {% set native = 'm2w64-' if win else '' %}

    package:
      name: r-magrittr
      version: {{ version|replace("-", "_") }}

    source:
      url:
        - {{ cran_mirror }}/src/contrib/magrittr_{{ version }}.tar.gz
      sha256: 05c45943ada9443134caa0ab24db4a962b629f00b755ccf039a2a2a7b2c92ae8

    build:
      merge_build_host: true  # [win]
      skip: True   # [win]
      number: 1

    requirements:
      build:
        - {{ compiler('c') }}              # [not win]
        - {{ compiler('m2w64_c') }}        # [win]
        - {{ posix }}filesystem        # [win]
      host:
        - r-base
        - {{native}}gmp
      run:
        - r-base
        - {{ native }}gcc-libs         # [win]

    about:
      home: https://magrittr.tidyverse.org
      license: MIT
      license_family: MIT
      license_file:
        - {{ environ["PREFIX"] }}/lib/R/share/licenses/MIT
        - LICENSE
    """
)

# A real, multi-output R feedstock recipe (r-base itself) checked into this
# repo's test fixtures. crm crashes on it with a raw AttributeError (not a
# BaseParserException) rather than a clean warning/error.
R_BASE_MULTI_OUTPUT_RECIPE = (
    Path(__file__).parent / "r-base-feedstock" / "recipe" / "meta.yaml"
).read_text()


def test_generic_migrator_blocks_on_r_specific_warnings():
    # GenericV0ToV1Migrator has no idea these warnings are safe to ignore;
    # RV0ToV1Migrator is what extends the ignore-list to cover them.
    v1_content, blocking = GenericV0ToV1Migrator()._convert(MAGRITTR_RECIPE)
    assert v1_content is None
    assert blocking
    assert all(
        "ambiguous version constraints" in msg or "license_family" in msg
        for msg in blocking
    )


def test_convert_clean_with_r_specific_tokens():
    v1_content, blocking = RV0ToV1Migrator()._convert(MAGRITTR_RECIPE)
    assert blocking == []
    assert v1_content is not None
    assert "schema_version: 1" in v1_content
    # `{{ environ["PREFIX"] }}` must round-trip to valid v1 syntax, not be
    # left as invalid `${{ environ["PREFIX"] }}`.
    assert 'env.get("PREFIX")' in v1_content
    assert "environ[" not in v1_content


def test_convert_skips_multi_output_recipe_instead_of_crashing():
    v1_content, blocking = RV0ToV1Migrator()._convert(R_BASE_MULTI_OUTPUT_RECIPE)
    assert v1_content is None
    assert len(blocking) == 1
    assert "AttributeError" in blocking[0]


@pytest.mark.parametrize(
    "attrs, should_skip",
    [
        (
            {
                "name": "r-magrittr",
                "feedstock_name": "r-magrittr",
                "raw_meta_yaml": MAGRITTR_RECIPE,
            },
            False,
        ),
        (
            {
                "name": "numpy",
                "feedstock_name": "numpy",
                "raw_meta_yaml": "package:\n  name: numpy\n",
            },
            True,
        ),
        ({"name": "r-foo", "feedstock_name": "r-foo", "raw_meta_yaml": ""}, True),
    ],
)
def test_filter_scopes_to_r_feedstocks(attrs, should_skip):
    assert RV0ToV1Migrator().filter(attrs) is should_skip


def test_migrate_converts_r_recipe(tmp_path):
    (tmp_path / "meta.yaml").write_text(MAGRITTR_RECIPE)

    RV0ToV1Migrator().migrate(str(tmp_path), {"name": "r-magrittr"})

    assert not (tmp_path / "meta.yaml").exists()
    recipe_yaml = tmp_path / "recipe.yaml"
    assert recipe_yaml.exists()
    assert "schema_version: 1" in recipe_yaml.read_text()


def test_migrate_skips_multi_output_recipe(tmp_path):
    (tmp_path / "meta.yaml").write_text(R_BASE_MULTI_OUTPUT_RECIPE)

    RV0ToV1Migrator().migrate(str(tmp_path), {"name": "r-base"})

    assert (tmp_path / "meta.yaml").read_text() == R_BASE_MULTI_OUTPUT_RECIPE
    assert not (tmp_path / "recipe.yaml").exists()
