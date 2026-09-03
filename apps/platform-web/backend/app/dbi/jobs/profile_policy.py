"""Política provisional de perfil DBI controlada exclusivamente por servidor."""

from __future__ import annotations

import os
from collections.abc import Mapping

from app.dbi.jobs.service_contracts import (
    AnalysisProfileResolutionContext,
    ApprovedAnalysisProfile,
)

DBI_ANALYSIS_MODEL_VERSION_ENV = "DBI_ANALYSIS_MODEL_VERSION_REF"
DBI_ANALYSIS_PIPELINE_CONFIG_ENV = "DBI_ANALYSIS_PIPELINE_CONFIG_VERSION"
DBI_ANALYSIS_POLICY_REF_ENV = "DBI_ANALYSIS_PROFILE_POLICY_REF"


class DBIConfiguredAnalysisProfilePolicy:
    """Perfil global explícitamente aprobado por configuración del servidor."""

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


def load_configured_analysis_profile_policy(
    environ: Mapping[str, str] | None = None,
) -> DBIConfiguredAnalysisProfilePolicy | None:
    """Carga un perfil sólo si los tres valores server-side son completos.

    Cero variables significa que aún no hay perfil aprobado y el llamador debe
    fallar cerrado. Una configuración parcial se considera error operativo.
    """

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
