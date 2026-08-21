import json
import os

from services.forensics import _guess_mime


def inspect_c2pa(file_path: str) -> dict:
    """Read Content Credentials when present. Never invent a provenance score."""
    if not os.path.isfile(file_path):
        return {
            "status": "File not found for C2PA inspection",
            "method": "c2pa-python",
            "credentials_found": False,
        }

    try:
        from c2pa import Reader
    except Exception as e:
        return {
            "status": f"C2PA library not available: {e}",
            "method": "Unavailable",
            "credentials_found": False,
            "note": "Install c2pa-python to inspect Content Credentials.",
        }

    try:
        reader = None
        try:
            reader = Reader.try_create(file_path)
        except TypeError:
            mime = _guess_mime(file_path)
            with open(file_path, "rb") as handle:
                reader = Reader.try_create(mime, handle)

        if reader is None:
            return {
                "status": "No Content Credentials found",
                "method": "c2pa-python Reader.try_create",
                "model_name": "c2pa-python",
                "credentials_found": False,
                "note": "The file was inspected; no C2PA manifest was attached.",
            }

        with reader:
            raw = reader.json()
        manifest = json.loads(raw) if isinstance(raw, str) else raw
        active = manifest.get("active_manifest")
        manifests = manifest.get("manifests") or {}
        active_manifest = manifests.get(active) if isinstance(manifests, dict) else None
        claim_generator = None
        assertions = []
        if isinstance(active_manifest, dict):
            claim_generator = active_manifest.get("claim_generator") or active_manifest.get("claim_generator_info")
            assertions = [
                item.get("label")
                for item in (active_manifest.get("assertions") or [])
                if isinstance(item, dict)
            ][:12]

        return {
            "status": "Content Credentials present",
            "method": "c2pa-python Reader",
            "model_name": "c2pa-python",
            "model_status": "Library available",
            "credentials_found": True,
            "active_manifest": active,
            "claim_generator": claim_generator,
            "assertions": assertions,
            "note": "Provenance is complementary to detection; credentials do not prove or disprove impersonation.",
        }
    except Exception as e:
        return {
            "status": f"C2PA inspection failed: {e}",
            "method": "c2pa-python",
            "credentials_found": False,
            "note": "The library ran; this file could not be parsed as having valid credentials.",
        }
