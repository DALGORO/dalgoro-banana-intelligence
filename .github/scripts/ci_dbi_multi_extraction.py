"""Valida extracción espacial pura y fusión referencial MULTI ↔ INSPECT."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SERVICE_SRC = ROOT / "services" / "banana-density" / "src"
sys.path.insert(0, str(SERVICE_SRC))

from banana_analyzer.multispectral_extraction import (  # noqa: E402
    MultispectralExtractionError,
    SpatialSupport,
    SpatialSupportMode,
    SpectralFieldLink,
    extract_spectral_evidence,
)
from banana_analyzer.multispectral_indices import SpectralBand  # noqa: E402
from banana_analyzer.multispectral_stack import (  # noqa: E402
    SpectralBandSource,
    prepare_multispectral_stack,
)

_TRANSFORM = (0.1, 0.0, 500000.0, 0.0, -0.1, 9600000.0)


def _sources() -> dict[SpectralBand, SpectralBandSource]:
    raw = {
        SpectralBand.GREEN: np.array([[2000, 3000, 4000], [0, 2500, 3500]], dtype=np.uint16),
        SpectralBand.RED: np.array([[1000, 2000, 3000], [1000, 2000, 1000]], dtype=np.uint16),
        SpectralBand.RED_EDGE: np.array([[1500, 2500, 3500], [2000, 3000, 2000]], dtype=np.uint16),
        SpectralBand.NIR: np.array([[5000, 6000, 7000], [4000, 5000, 4000]], dtype=np.uint16),
    }
    result: dict[SpectralBand, SpectralBandSource] = {}
    for index, band in enumerate(SpectralBand, start=1):
        result[band] = SpectralBandSource(
            band=band,
            source_ref=UUID(f"42000000-0000-4000-8000-{index:012d}"),
            source_sha256=f"{index:064x}",
            band_index=index,
            crs="EPSG:32717",
            transform=_TRANSFORM,
            width=3,
            height=2,
            dtype="uint16",
            nodata=0 if band is SpectralBand.GREEN else 65535,
            scale=0.0001,
            offset=0.0,
            calibration_profile_version="reflectance_v1",
            values=raw[band],
        )
    return result


def _link(*, sampling: bool = True, up: bool = False) -> SpectralFieldLink:
    return SpectralFieldLink(
        tenant_ref="tenant-demo",
        organization_ref="organization-demo",
        farm_id=UUID("10000000-0000-4000-8000-000000000001"),
        plot_id=UUID("20000000-0000-4000-8000-000000000001"),
        observation_version_id=UUID("dc5660c1-a2b7-464a-804a-44abe87ce2c5"),
        sampling_point_id=(
            UUID("91000000-0000-4000-8000-000000000001") if sampling else None
        ),
        up_id=UUID("92000000-0000-4000-8000-000000000001") if up else None,
    )


def _window() -> SpatialSupport:
    return SpatialSupport(
        mode=SpatialSupportMode.WINDOW,
        profile_version="window_5m_v1",
        limitation="Ventana sustituta usada porque COPA_UP aún no está disponible.",
    )


def _mask() -> np.ndarray:
    return np.array([[True, True, False], [True, False, False]], dtype=bool)


def _raises(callback) -> None:
    try:
        callback()
    except MultispectralExtractionError:
        return
    raise AssertionError("Se esperaba MultispectralExtractionError.")


def _summary(extraction, variable_ref: str):
    matches = [item for item in extraction.summaries if item.variable_ref == variable_ref]
    assert len(matches) == 1
    return matches[0]


def validate_window_extraction() -> None:
    sources = _sources()
    originals = {band: source.values.copy() for band, source in sources.items()}
    stack = prepare_multispectral_stack(sources)
    extraction = extract_spectral_evidence(
        stack,
        link=_link(sampling=True, up=False),
        support=_window(),
        selection_mask=_mask(),
    )

    assert extraction.schema_version == "dbi-multispectral-extraction.v1"
    assert extraction.evidence_kind == "derived"
    assert extraction.support_mode is SpatialSupportMode.WINDOW
    assert extraction.support_limitation
    assert extraction.selected_count == 3
    assert extraction.sampling_point_id is not None
    assert extraction.up_id is None
    assert extraction.observation_version_id == UUID(
        "dc5660c1-a2b7-464a-804a-44abe87ce2c5"
    )
    assert extraction.stack_fingerprint == stack.fingerprint

    green = _summary(extraction, "green")
    assert green.variable_kind == "band"
    assert green.evidence_kind == "derived"
    assert green.selected_count == 3
    assert green.valid_count == 2
    assert np.isclose(green.valid_fraction, 2 / 3)
    assert np.isclose(green.mean, 0.25)
    assert green.source_ref == sources[SpectralBand.GREEN].source_ref
    assert green.source_sha256 == sources[SpectralBand.GREEN].source_sha256

    ndvi = _summary(extraction, "ndvi")
    assert ndvi.variable_kind == "index"
    assert ndvi.valid_count == 3
    assert ndvi.formula_version == "ndvi_v1"
    assert ndvi.formula == "(nir-red)/(nir+red)"
    assert ndvi.source_ref is None
    assert ndvi.source_sha256 is None

    for band, source in sources.items():
        assert np.array_equal(source.values, originals[band])


def validate_copa_up_and_pending_association() -> None:
    stack = prepare_multispectral_stack(_sources())
    copa = extract_spectral_evidence(
        stack,
        link=_link(sampling=False, up=True),
        support=SpatialSupport(
            mode=SpatialSupportMode.COPA_UP,
            profile_version="copa_up_mask_v1",
        ),
        selection_mask=_mask(),
    )
    assert copa.support_mode is SpatialSupportMode.COPA_UP
    assert copa.up_id is not None
    assert copa.sampling_point_id is None
    assert copa.support_limitation is None

    pending = extract_spectral_evidence(
        stack,
        link=_link(sampling=False, up=False),
        support=_window(),
        selection_mask=_mask(),
    )
    assert pending.up_id is None
    assert pending.sampling_point_id is None
    assert pending.observation_version_id is not None


def validate_rejections() -> None:
    stack = prepare_multispectral_stack(_sources())
    _raises(
        lambda: extract_spectral_evidence(
            stack,
            link=_link(),
            support=SpatialSupport(
                mode=SpatialSupportMode.WINDOW,
                profile_version="window_5m_v1",
            ),
            selection_mask=_mask(),
        )
    )
    _raises(
        lambda: extract_spectral_evidence(
            stack,
            link=_link(up=False),
            support=SpatialSupport(
                mode=SpatialSupportMode.COPA_UP,
                profile_version="copa_up_mask_v1",
            ),
            selection_mask=_mask(),
        )
    )
    _raises(
        lambda: extract_spectral_evidence(
            stack,
            link=_link(),
            support=_window(),
            selection_mask=np.zeros((2, 3), dtype=bool),
        )
    )
    _raises(
        lambda: extract_spectral_evidence(
            stack,
            link=_link(),
            support=_window(),
            selection_mask=np.ones((1, 1), dtype=bool),
        )
    )
    _raises(
        lambda: extract_spectral_evidence(
            stack,
            link=_link(),
            support=_window(),
            selection_mask=np.ones((2, 3), dtype=np.uint8),
        )
    )


def validate_reproducibility() -> None:
    stack = prepare_multispectral_stack(_sources())
    first = extract_spectral_evidence(
        stack,
        link=_link(),
        support=_window(),
        selection_mask=_mask(),
    )
    second = extract_spectral_evidence(
        stack,
        link=_link(),
        support=_window(),
        selection_mask=_mask(),
    )
    assert first == second
    assert len(first.summaries) == len(SpectralBand) + 6


def main() -> None:
    validate_window_extraction()
    validate_copa_up_and_pending_association()
    validate_rejections()
    validate_reproducibility()
    print(
        "DBI-MULTI-001 extracción aprobada: ventana/COPA_UP, vínculo versionado "
        "INSPECT, nodata excluido, estadísticos reproducibles y evidencia derived."
    )


if __name__ == "__main__":
    main()
