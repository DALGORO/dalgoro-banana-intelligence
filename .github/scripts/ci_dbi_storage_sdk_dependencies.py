"""Valida el SDK S3 fijado sin red, cuenta cloud o credenciales reales."""

from __future__ import annotations

import os
from importlib import metadata
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
BACKEND_REQUIREMENTS = (
    ROOT / "apps" / "platform-web" / "backend" / "requirements.txt"
)

EXPECTED_VERSIONS = {
    "boto3": "1.43.62",
    "botocore": "1.43.62",
    "jmespath": "1.1.0",
    "python-dateutil": "2.9.0.post0",
    "s3transfer": "0.19.2",
}

EXPECTED_LICENSES = {
    "boto3": frozenset({"Apache-2.0", "Apache License 2.0"}),
    "botocore": frozenset({"Apache-2.0", "Apache License 2.0"}),
    "jmespath": frozenset({"MIT", "MIT License"}),
    "python-dateutil": frozenset({"Dual License"}),
    "s3transfer": frozenset({"Apache-2.0", "Apache License 2.0"}),
}

FORBIDDEN_LICENSE_MARKERS = (
    "agpl",
    "gnu affero",
    "gpl-",
    "gnu general public license",
)


def _normalized_name(value: str) -> str:
    return value.casefold().replace("_", "-")


def validate_requirement_pins() -> None:
    lines = BACKEND_REQUIREMENTS.read_text(encoding="utf-8-sig").splitlines()
    pins: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        assert "==" in line, f"Dependencia no fijada exactamente: {line}"
        name, version = line.split("==", maxsplit=1)
        normalized = _normalized_name(name)
        assert normalized not in pins, f"Dependencia duplicada: {name}"
        pins[normalized] = version

    for package_name, expected_version in EXPECTED_VERSIONS.items():
        assert pins.get(package_name) == expected_version
        assert metadata.version(package_name) == expected_version


def validate_license_surface() -> None:
    """Bloquea licencias copyleft fuertes no aprobadas en el SDK agregado."""

    for package_name, accepted_licenses in EXPECTED_LICENSES.items():
        package_metadata = metadata.metadata(package_name)
        license_value = (package_metadata.get("License") or "").strip()
        assert license_value in accepted_licenses, (
            f"Licencia no aprobada para {package_name}: {license_value!r}"
        )

        searchable_metadata = "\n".join(
            (
                license_value,
                *(package_metadata.get_all("Classifier") or ()),
            )
        ).casefold()
        assert not any(
            marker in searchable_metadata
            for marker in FORBIDDEN_LICENSE_MARKERS
        ), f"Se detectó copyleft fuerte no aprobado en {package_name}."


def validate_dependency_surface() -> None:
    try:
        metadata.version("awscrt")
    except metadata.PackageNotFoundError:
        pass
    else:
        raise AssertionError("El extra CRT no está autorizado para DBI-STORAGE-001.")

    for package_name in ("boto3", "botocore"):
        requires_python = metadata.metadata(package_name)["Requires-Python"]
        assert requires_python is not None
        assert requires_python.replace(" ", "") == ">=3.10"


def validate_offline_client_construction() -> None:
    os.environ["AWS_EC2_METADATA_DISABLED"] = "true"

    import boto3
    from botocore.config import Config

    session = boto3.Session(
        aws_access_key_id="dbi-ci-synthetic-access",
        aws_secret_access_key="dbi-ci-synthetic-secret",
        region_name="us-east-1",
    )
    client = session.client(
        "s3",
        endpoint_url="http://127.0.0.1:9",
        use_ssl=False,
        verify=False,
        config=Config(
            signature_version="s3v4",
            connect_timeout=1,
            read_timeout=1,
            retries={"total_max_attempts": 1, "mode": "standard"},
            s3={"addressing_style": "path"},
        ),
    )

    url = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": "dbi-ci-synthetic",
            "Key": "tenants/synthetic/analysis-inputs/object",
            "ContentType": "application/octet-stream",
        },
        ExpiresIn=300,
        HttpMethod="PUT",
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "http"
    assert parsed.hostname == "127.0.0.1"
    assert parsed.port == 9
    assert parsed.path == (
        "/dbi-ci-synthetic/tenants/synthetic/analysis-inputs/object"
    )
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert query["X-Amz-Expires"] == ["300"]
    assert "dbi-ci-synthetic-access" in query["X-Amz-Credential"][0]
    assert "dbi-ci-synthetic-secret" not in url
    assert boto3.DEFAULT_SESSION is None


def main() -> None:
    validate_requirement_pins()
    validate_license_surface()
    validate_dependency_surface()
    validate_offline_client_construction()
    print("Almacenamiento DBI: SDK S3, versiones y licencias aprobados offline.")


if __name__ == "__main__":
    main()
