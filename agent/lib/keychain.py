"""macOS Keychain reader for scan secrets. Stdlib only."""
import subprocess


def get_secret(service: str) -> str:
    """Return the password stored under the given Keychain service name.

    Raises KeyError with a runbook hint if missing — a setup error, not runtime.
    """
    result = subprocess.run(
        ["/usr/bin/security", "find-generic-password", "-s", service, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise KeyError(
            f"Keychain item '{service}' not found. Add it with: "
            f"security add-generic-password -a <account> -s {service} -w '<secret>' "
            f"(see docs/runbook.md)"
        )
    return result.stdout.strip()
