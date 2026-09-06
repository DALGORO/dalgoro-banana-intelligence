"""Valida provenance, calibración y co-registro de bandas DBI-MULTI-001."""

from __future__ import annotations

import re
import sys
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SERVICE_SRC = ROOT / "services" / "banana-density" / "src"
sys.path.insert(0, str(SERVICE_SRC))

from banana_analyzer.multispectral_indices import SpectralBand, SpectralIndex  # noqa: E402
from banana_analyzer.multispectral_stack import (  # noqa: E402
    MultispectralStackError,
    SpectralBandSource,
    compute_initial_indices_from_stack,
    prepare_multispectral_stack,
)

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_TRANSFORM = (0.1, 0.0, 500000.0, 0.0, -0.1, 9600000.0)


def _sources() -> dict[SpectralBand, SpectralBandSource]:
    arrays = {
        SpectralBand.GREEN: np.array(
            [[2000, 3000, 4000], [0, 2500, 3500]], dtype=np.uint16
        ),
        SpectralBand.RED: np.array(
            [[1000, 2000, 3000], [1000, 2000, 1000]], dtype=np.uint16
        ),
        SpectralBand.RED_EDGE: np.array(
            [[1500, 2500, 3500], [2000, 3000, 2000]], dtype=np.uint16
        ),
        SpectralBand.NIR: np.array(
            [[5000, 6000, 7000], [4000, 5000, 4000]], dtype=np.uint16
        ),
    }
    refs = {
        SpectralBand.GREEN: UUID("41000000-0000-4000-8000-000000000001"),
        SpectralBand.RED: UUID("41000000-0000-4000-8000-000000000002"),
        SpectralBand.RED_EDGE: UUID("41000000-0000-4000-8000-000000000003"),
        SpectralBand.NIR: UUID("41000000-0000-4000-8000-000000000004"),
    }
    sources: dict[SpectralBand, SpectralBandSource] = {}
    for band_index, band in enumerate(SpectralBand, start=1):
        sources[band] = SpectralBandSource(
            band=band,
            source_ref=refs[band],
            source_sha256=f"{band_index:064x}",
            band_index=band_index,
            crs="EPSG:32717",
            transform=_TRANSFORM,
            width=3,
            height=2,
            dtype="uint16",
            nodata=0 if band is SpectralBand.GREEN else 65535,
            scale=0.0001,
            offset=0.0,
            calibration_profile_version="reflectance_v1",
            values=arrays[band],
        )
    return sources


def _raises(callback) -> None:
    try:
        callback()
    except MultispectralStackError:
        return
    raise AssertionError("Se esperaba MultispectralStackError.")


def validate_preservation_and_calibration() -> None:
    sources = _sources()
    originals = {band: source.values.copy() for band, source in sources.items()}
    stack = prepare_multispectral_stack(sources)

    assert stack.schema_version == "dbi-multispectral-stack.v1"
    assert _SHA_RE.fullmatch(stack.fingerprint)
    assert set(stack.bands) == set(SpectralBand)

    for band, source in sources.items():
        assert np.array_equal(source.values, originals[band])
        assert source.values.dtype == np.uint16
        assert stack.bands[band].source.source_ref == source.source_ref
        assert stack.bands[band].source.source_sha256 == source.source_sha256
        assert stack.bands[band].calibrated_values.dtype == np.float64

    assert np.isclose(
        stack.bands[SpectralBand.GREEN].calibrated_values[0, 0],
        0.20,
    )
    assert stack.bands[SpectralBand.GREEN].invalid_mask[1, 0]
    assert np.isnan(stack.bands[SpectralBand.GREEN].calibrated_values[1, 0])


def validate_band_specific_masks_and_indices() -> None:
    stack = prepare_multispectral_stack(_sources())
    results = compute_initial_indices_from_stack(stack)

    assert np.isclose(
        results[SpectralIndex.NDVI].values[0, 0],
        (0.50 - 0.10) / (0.50 + 0.10),
    )

    for index in (SpectralIndex.GNDVI, SpectralIndex.CI_GREEN):
        assert not results[index].valid_mask[1, 0]
        assert np.isnan(results[index].values[1, 0])

    for index in (
        SpectralIndex.NDVI,
        SpectralIndex.NDRE,
        SpectralIndex.EVI2,
        SpectralIndex.CI_RED_EDGE,
    ):
        assert results[index].valid_mask[1, 0]
        assert np.isfinite(results[index].values[1, 0])

    for result in results.values():
        assert result.evidence_kind == "derived"


def validate_fingerprint_reproducibility() -> None:
    sources = _sources()
    first = prepare_multispectral_stack(sources)
    second = prepare_multispectral_stack(sources)
    assert first.fingerprint == second.fingerprint

    changed = dict(sources)
    changed[SpectralBand.GREEN] = replace(
        sources[SpectralBand.GREEN],
        source_sha256="f" * 64,
    )
    third = prepare_multispectral_stack(changed)
    assert third.fingerprint != first.fingerprint


def validate_contract_rejections() -> None:
    sources = _sources()

    missing = dict(sources)
    missing.pop(SpectralBand.NIR)
    _raises(lambda: prepare_multispectral_stack(missing))

    misaligned = dict(sources)
    misaligned[SpectralBand.RED] = replace(
        sources[SpectralBand.RED],
        transform=(0.1, 0.0, 500000.05, 0.0, -0.1, 9600000.0),
    )
    _raises(lambda: prepare_multispectral_stack(misaligned))

    wrong_dtype = dict(sources)
    wrong_dtype[SpectralBand.GREEN] = replace(
        sources[SpectralBand.GREEN],
        dtype="float32",
    )
    _raises(lambda: prepare_multispectral_stack(wrong_dtype))

    zero_scale = dict(sources)
    zero_scale[SpectralBand.NIR] = replace(
        sources[SpectralBand.NIR],
        scale=0.0,
    )
    _raises(lambda: prepare_multispectral_stack(zero_scale))


def main() -> None:
    validate_preservation_and_calibration()
    validate_band_specific_masks_and_indices()
    validate_fingerprint_reproducibility()
    validate_contract_rejections()
    print(
        "DBI-MULTI-001 pila científica aprobada: bandas fuente intactas, checksum, "
        "scale/offset, co-registro, nodata por banda y fingerprint reproducible."
    )


if __name__ == "__main__":
    main()
