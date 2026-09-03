"""Selección server-side de la única autoridad de perfiles de análisis DBI."""

from __future__ import annotations

import os
from collections.abc import Mapping

from app.dbi.jobs.service_contracts import (
    AnalysisProfileResolutionContext,
    ApprovedAnalysisProfile,
)

DBI_ANALYSIS_PROFILE_SOURCE_ENV = "DBI_ANALYSIS_PROFILE_SOURCE"
DBI_ANALYSIS_PROFILE_SOURCE_REGISTRY = "registry"
DBI_ANALYSIS_PROFILE_SOURCE_ENVIRONMENT = "environment"
DBI_ANALYSIS_MODEL_VERSION_ENV = "DBI_ANALYSIS_MODEL_VERSION_REF"
DBI_ANALYSIS_PIPELINE_CONFIG_ENV = "DBI_ANALYSIS_PIPELINE_CONFIG_VERSION"
DBI_ANALYSIS_POLICY_REF_ENV = "DBI_ANALYSIS_PROFILE_POLICY_REF"
_LEGACY_PROFILE_ENV_VARS = (
    DBI_ANALYSIS_MODEL_VERSION_ENV,
    DBI_ANALYSIS_PIPELINE_CONFIG_ENV,
    DBI_ANALYSIS_POLICY_REF_ENV,
)


class DBIConfiguredAnalysisProfilePolicy:
    """Compatibilidad explícita con un perfil global controlado por servidor."""

    def __init__(self, profile: ApprovedAnalysisProfile) -> None:
        if not isinstance(profile, ApprovedAnalysisProfile):
            raise TypeError("profile debe ser ApprovedAnalysisProfile.")
        self._profile = profile

    def resolve(
        self,
        *,
        context: AnalysisProfileResolutionContext,
    ) -> ApprovedAnalysisProfile:
        if not isinstance(context, AnalysisProfileResolutionContext):
            raise TypeError("context debe ser AnalysisProfileResolutionContext.")
        return self._profile


def load_analysis_profile_source(
    environ: Mapping[str, str] | None = None,
) -> str:
    """Selecciona una sola autoridad; el registro persistente es el default."""

    source = os.environ if environ is None else environ
    authority = source.get(
        DBI_ANALYSIS_PROFILE_SOURCE_ENV,
        DBI_ANALYSIS_PROFILE_SOURCE_REGISTRY,
    ).strip().lower()
    if authority not in {
        DBI_ANALYSIS_PROFILE_SOURCE_REGISTRY,
        DBI_ANALYSIS_PROFILE_SOURCE_ENVIRONMENT,
    }:
        raise ValueError("DBI_ANALYSIS_PROFILE_SOURCE no es válido.")

    legacy_present = any(source.get(name) is not None for name in _LEGACY_PROFILE_ENV_VARS)
    if authority == DBI_ANALYSIS_PROFILE_SOURCE_REGISTRY and legacy_present:
        raise ValueError(
            "No se permiten variables de perfil legacy cuando la autoridad es registry."
        )
    return authority


def load_configured_analysis_profile_policy(
    environ: Mapping[str, str] | None = None,
) -> DBIConfiguredAnalysisProfilePolicy | None:
    """Carga el fallback environment sólo si sus tres valores son completos."""

    source = os.environ if environ is None else environ
    raw = {
        "model_version_id": source.get(DBI_ANALYSIS_MODEL_VERSION_ENV),
        "pipeline_config_version": source.get(DBI_ANALYSIS_PIPELINE_CONFIG_ENV),
        "policy_ref": source.get(DBI_ANALYSIS_POLICY_REF_ENV),
    }
    configured = {name: value for name, value in raw.items() if value is not None}
    if not configured:
        return None
    if len(configured) != len(raw):
        raise ValueError("La configuración del perfil DBI está incompleta.")

    profile = ApprovedAnalysisProfile(**raw)
    return DBIConfiguredAnalysisProfilePolicy(profile)
