"""Valida el núcleo científico inicial de DBI-MULTI-001 sin red ni base."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SERVICE_SRC = ROOT / "services" / "banana-density" / "src"
sys.path.insert(0, str(SERVICE_SRC))

from banana_analyzer.multispectral_indices import (  # noqa: E402
    MultispectralIndexError,
    SpectralBand,
    SpectralIndex,
    compute_index,
    compute_initial_indices,
    index_definition,
)


def _bands() -> dict[str, np.ndarray]:
    return {
        "green": np.array([[0.20, 0.30, 0.40], [0.00, 0.25, np.nan]], dtype=float),
        "red": np.array([[0.10, 0.20, 0.30], [0.00, 0.20, 0.10]], dtype=float),
        "red_edge": np.array([[0.15, 0.25, 0.35], [0.00, 0.30, 0.20]], dtype=float),
        "nir": np.array([[0.50, 0.60, 0.70], [0.00, 0.50, 0.40]], dtype=float),
    }


def _raises(callback) -> None:
    try:
        callback()
    except MultispectralIndexError:
        return
    raise AssertionError("Se esperaba MultispectralIndexError.")


def validate_formulas() -> None:
    bands = _bands()
    results = compute_initial_indices(bands)
    assert set(results) == set(SpectralIndex)

    ndvi = results[SpectralIndex.NDVI]
    ndre = results[SpectralIndex.NDRE]
    gndvi = results[SpectralIndex.GNDVI]
    evi2 = results[SpectralIndex.EVI2]
    ci_re = results[SpectralIndex.CI_RED_EDGE]
    ci_green = results[SpectralIndex.CI_GREEN]

    assert np.isclose(ndvi.values[0, 0], (0.50 - 0.10) / (0.50 + 0.10))
    assert np.isclose(ndre.values[0, 0], (0.50 - 0.15) / (0.50 + 0.15))
    assert np.isclose(gndvi.values[0, 0], (0.50 - 0.20) / (0.50 + 0.20))
    assert np.isclose(
        evi2.values[0, 0],
        2.5 * (0.50 - 0.10) / (0.50 + 2.4 * 0.10 + 1.0),
    )
    assert np.isclose(ci_re.values[0, 0], (0.50 / 0.15) - 1.0)
    assert np.isclose(ci_green.values[0, 0], (0.50 / 0.20) - 1.0)

    for result in results.values():
        assert result.schema_version == "dbi-multispectral-index.v1"
        assert result.evidence_kind == "derived"
        assert result.values.dtype == np.float32
        assert result.valid_mask.dtype == bool
        assert result.values.shape == (2, 3)
        assert result.valid_mask.shape == (2, 3)


def validate_nodata_and_unstable_division() -> None:
    bands = _bands()
    explicit_invalid = np.zeros((2, 3), dtype=bool)
    explicit_invalid[0, 1] = True
    results = compute_initial_indices(bands, invalid_mask=explicit_invalid)

    for result in results.values():
        assert not result.valid_mask[0, 1]
        assert np.isnan(result.values[0, 1])
        assert not result.valid_mask[1, 0]
        assert np.isnan(result.values[1, 0])

    for index in (SpectralIndex.GNDVI, SpectralIndex.CI_GREEN):
        result = results[index]
        assert not result.valid_mask[1, 2]
        assert np.isnan(result.values[1, 2])

    ndvi = results[SpectralIndex.NDVI]
    assert ndvi.valid_mask[1, 2]
    assert np.isfinite(ndvi.values[1, 2])


def validate_contract_boundaries() -> None:
    for index in SpectralIndex:
        definition = index_definition(index)
        assert definition.index is index
        assert definition.formula_version.endswith("_v1")
        assert SpectralBand.NIR in definition.required_bands
        assert definition.formula

    bands = _bands()
    _raises(
        lambda: compute_index(
            SpectralIndex.NDVI,
            {"nir": bands["nir"]},
        )
    )
    _raises(
        lambda: compute_index(
            SpectralIndex.NDVI,
            {"nir": bands["nir"], "red": np.ones((1, 1))},
        )
    )
    _raises(
        lambda: compute_index(
            SpectralIndex.NDVI,
            bands,
            invalid_mask=np.zeros((1, 1), dtype=bool),
        )
    )
    _raises(lambda: compute_index(SpectralIndex.NDVI, bands, epsilon=0.0))


def validate_reproducibility() -> None:
    bands = _bands()
    first = compute_initial_indices(bands)
    second = compute_initial_indices(bands)
    for index in SpectralIndex:
        assert np.array_equal(first[index].valid_mask, second[index].valid_mask)
        assert np.array_equal(
            np.nan_to_num(first[index].values, nan=-9999.0),
            np.nan_to_num(second[index].values, nan=-9999.0),
        )


def main() -> None:
    validate_formulas()
    validate_nodata_and_unstable_division()
    validate_contract_boundaries()
    validate_reproducibility()
    print(
        "DBI-MULTI-001 índices aprobados: fórmulas, nodata, división estable, "
        "provenance mínimo y reproducibilidad."
    )


if __name__ == "__main__":
    main()
