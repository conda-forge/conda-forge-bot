import logging
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

# A real pattern (from r-presenceabsence): CRAN's "Unlimited" license,
# pre-wrapped as the SPDX custom-license reference "LicenseRef-Unlimited".
# crm's own matcher maps the *bare* string "Unlimited" -> "NOASSERTION", but
# doesn't recognize the "LicenseRef-" wrapped form, so it warns "Could not
# patch unrecognized license" unless we strip the wrapper first.
LICENSEREF_UNLIMITED_RECIPE = textwrap.dedent(
    """\
    package:
      name: r-presenceabsence
      version: "1.0"

    requirements:
      host:
        - r-base
      run:
        - r-base

    about:
      home: https://CRAN.R-project.org/package=PresenceAbsence
      license: LicenseRef-Unlimited
      license_family: other
      summary: test
    """
)


def test_to_spdx_overrides_r_specific_mapping_and_falls_back_to_shared_one():
    migrator = RV0ToV1Migrator()
    # R-specific override.
    assert migrator._to_spdx("LicenseRef-Unlimited") == "Unlimited"
    # Falls back to GenericV0ToV1Migrator._to_spdx() -> the shared mapping.
    assert migrator._to_spdx("GPL-2") == "GPL-2.0-only"
    # Unrecognized strings are still a no-op.
    assert migrator._to_spdx("nonsense") == "nonsense"


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


def test_convert_normalizes_licenseref_unlimited():
    # Mapping straight to "NOASSERTION" ourselves would backfire: it isn't
    # itself a recognized SPDX license ID, so crm would just reject it right
    # back as "unrecognized". Stripping down to the bare "Unlimited" lets
    # crm's own matcher apply its own agreed correction instead.
    v1_content, blocking = RV0ToV1Migrator()._convert(LICENSEREF_UNLIMITED_RECIPE)
    assert blocking == []
    assert v1_content is not None
    assert "license: NOASSERTION" in v1_content


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
        (
            # No "r-" name/prefix and no "r-base" mention, but maintained by
            # the conda-forge/r team - still detected as an R feedstock.
            {
                "name": "some-cran-tool",
                "feedstock_name": "some-cran-tool",
                "raw_meta_yaml": "package:\n  name: some-cran-tool\n",
                "extra": {"recipe-maintainers": ["conda-forge/r", "someuser"]},
            },
            False,
        ),
        (
            # Has an unrelated maintainer team, but no "r-" prefix and no
            # "r-base" mention - not an R feedstock.
            {
                "name": "foo",
                "feedstock_name": "foo",
                "raw_meta_yaml": "package:\n  name: foo\n",
                "extra": {"recipe-maintainers": ["conda-forge/core"]},
            },
            True,
        ),
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


# A real pattern (from r-msqc/r-pca3d/r-cffr/r-juniperkernel): the outer
# `if` already routes osx-64 to a plain install, so the `install_name_tool`
# fix - nested under `target_platform == osx-64` inside the `else` - is only
# ever reached when target_platform != osx-64, making it dead code.
LEGACY_OSX_ARM64_WORKAROUND_BUILD_SH = textwrap.dedent(
    """\
    #!/bin/bash
    if [[ ${target_platform} == osx-64 ]] || [[ ${target_platform} =~ linux.* ]]; then
      ${R} CMD INSTALL --build .
    else
      mv ./* "${PREFIX}"/lib/R/library
      if [[ ${target_platform} == osx-64 ]]; then
        install_name_tool -change /Library/Frameworks/R.framework/Versions/3.5/Resources/lib/libR.dylib "${PREFIX}"/lib/R/lib/libR.dylib "${SHARED_LIB}" || true
      fi
    fi
    """
)


def test_build_script_review_reasons_flags_legacy_osx_arm64_workaround():
    reasons = RV0ToV1Migrator()._build_script_review_reasons(
        LEGACY_OSX_ARM64_WORKAROUND_BUILD_SH
    )
    assert len(reasons) == 1
    assert "osx-arm64" in reasons[0]


def test_build_script_review_reasons_no_false_positive_on_ordinary_script():
    reasons = RV0ToV1Migrator()._build_script_review_reasons(
        "#!/bin/bash\n${R} CMD INSTALL --build .\n"
    )
    assert reasons == []


def test_migrate_warns_about_legacy_osx_arm64_workaround(tmp_path, caplog):
    (tmp_path / "meta.yaml").write_text(MAGRITTR_RECIPE)
    (tmp_path / "build.sh").write_text(LEGACY_OSX_ARM64_WORKAROUND_BUILD_SH)

    with caplog.at_level(logging.WARNING):
        RV0ToV1Migrator().migrate(str(tmp_path), {"name": "r-magrittr"})

    # The conversion still succeeds - this is a non-blocking, informational
    # flag, not a reason to skip.
    assert (tmp_path / "recipe.yaml").exists()
    assert "manual review" in caplog.text
    assert "osx-arm64" in caplog.text
