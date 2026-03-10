"""
╔══════════════════════════════════════════════════════════════════╗
║  HYDRA — Self-Healing Module Updater                             ║
║  The regenerative core of the HYDRA                              ║
║                                                                    ║
║  "Cut off one head, two more grow back."                         ║
║                                                                    ║
║  On every launch:                                                 ║
║  1. Checks the hydra-modules GitHub repo for updates             ║
║  2. Compares local module hashes against remote                  ║
║  3. Downloads and hot-swaps any changed modules                  ║
║  4. Validates new modules before activating                      ║
║  5. Keeps a rollback copy in case new module is broken           ║
║                                                                    ║
║  Self-healing strategy:                                           ║
║  - If a module fails validation after update → auto-rollback     ║
║  - If a module throws errors at runtime → disable + report       ║
║  - Periodic health checks on all active modules                  ║
║  - Error telemetry sent back to modules repo (opt-in)            ║
╚══════════════════════════════════════════════════════════════════╝
"""

import sys
import os
import json
import hashlib
import shutil
import importlib
import importlib.util
import traceback
from pathlib import Path
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError

# ─── Configuration ───
MODULES_REPO = "EmperorBadussy/hydra-modules"
MODULES_BRANCH = "main"
GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"

# Local paths (set by init())
MODULES_DIR = None
BACKUP_DIR = None
MANIFEST_PATH = None
HEALTH_LOG_PATH = None


def init(base_dir: str):
    """Initialize paths relative to the HYDRA installation."""
    global MODULES_DIR, BACKUP_DIR, MANIFEST_PATH, HEALTH_LOG_PATH

    MODULES_DIR = os.path.join(base_dir, "python", "services")
    BACKUP_DIR = os.path.join(base_dir, "python", "services", "_rollback")
    MANIFEST_PATH = os.path.join(base_dir, "python", "services", "_manifest.json")
    HEALTH_LOG_PATH = os.path.join(base_dir, "python", "services", "_health.json")

    os.makedirs(MODULES_DIR, exist_ok=True)
    os.makedirs(BACKUP_DIR, exist_ok=True)


def _github_get(endpoint: str) -> dict:
    """Make a GitHub API request."""
    url = f"{GITHUB_API}/{endpoint}"
    req = Request(url, headers={
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "HYDRA-Updater/1.0"
    })

    # Add auth token if available (for rate limiting)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        req.add_header("Authorization", f"token {token}")

    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _download_raw(path: str) -> bytes:
    """Download a raw file from the modules repo."""
    url = f"{GITHUB_RAW}/{MODULES_REPO}/{MODULES_BRANCH}/{path}"
    req = Request(url, headers={"User-Agent": "HYDRA-Updater/1.0"})
    with urlopen(req, timeout=30) as resp:
        return resp.read()


def _file_hash(filepath: str) -> str:
    """SHA-256 hash of a local file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _content_hash(data: bytes) -> str:
    """SHA-256 hash of bytes."""
    return hashlib.sha256(data).hexdigest()


def load_manifest() -> dict:
    """Load the local module manifest (tracks versions + hashes)."""
    if MANIFEST_PATH and os.path.exists(MANIFEST_PATH):
        try:
            with open(MANIFEST_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"modules": {}, "last_update": None, "hydra_version": "0.1.0"}


def save_manifest(manifest: dict):
    """Save the local module manifest."""
    manifest["last_update"] = datetime.now().isoformat()
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)


def load_health_log() -> dict:
    """Load the health check log."""
    if HEALTH_LOG_PATH and os.path.exists(HEALTH_LOG_PATH):
        try:
            with open(HEALTH_LOG_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"modules": {}, "last_check": None}


def save_health_log(log: dict):
    """Save the health check log."""
    log["last_check"] = datetime.now().isoformat()
    with open(HEALTH_LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)


# ════════════════════════════════════════════════════════════════
# UPDATE CYCLE
# ════════════════════════════════════════════════════════════════

def check_for_updates(progress_callback=None) -> dict:
    """
    Main update cycle. Checks remote repo for module changes.

    Returns:
        dict with: checked, updated, failed, errors, modules
    """
    result = {
        "checked": 0,
        "updated": [],
        "failed": [],
        "errors": [],
        "new_modules": [],
        "modules": {}
    }

    if not MODULES_DIR:
        result["errors"].append("Module updater not initialized")
        return result

    def report(msg):
        if progress_callback:
            progress_callback(msg)
        sys.stderr.write(f"[HYDRA-UPDATE] {msg}\n")

    try:
        # 1. Fetch remote manifest
        report("Checking for module updates...")
        try:
            remote_manifest_data = _download_raw("manifest.json")
            remote_manifest = json.loads(remote_manifest_data)
        except Exception as e:
            result["errors"].append(f"Could not reach module repository: {e}")
            report(f"Update check failed: {e}")
            return result

        local_manifest = load_manifest()

        # 2. Compare each module
        remote_modules = remote_manifest.get("modules", {})
        result["checked"] = len(remote_modules)

        for module_name, remote_info in remote_modules.items():
            try:
                remote_version = remote_info.get("version", "0.0.0")
                remote_hash = remote_info.get("hash", "")
                remote_file = remote_info.get("file", f"services/{module_name}.py")
                min_hydra = remote_info.get("min_hydra_version", "0.1.0")

                local_info = local_manifest.get("modules", {}).get(module_name, {})
                local_hash = local_info.get("hash", "")

                # Check if module needs updating
                local_path = os.path.join(MODULES_DIR, f"{module_name}.py")
                needs_update = False

                if not os.path.exists(local_path):
                    report(f"New module available: {module_name} v{remote_version}")
                    needs_update = True
                elif remote_hash and remote_hash != local_hash:
                    report(f"Update available: {module_name} v{remote_version}")
                    needs_update = True
                elif remote_version != local_info.get("version", ""):
                    report(f"Version bump: {module_name} v{remote_version}")
                    needs_update = True

                if needs_update:
                    _update_module(module_name, remote_file, remote_info, local_path, report)
                    if not os.path.exists(local_path):
                        result["new_modules"].append(module_name)
                    result["updated"].append(module_name)
                else:
                    report(f"Module {module_name} is up to date")

                result["modules"][module_name] = {
                    "version": remote_version,
                    "status": "updated" if needs_update else "current"
                }

            except Exception as e:
                result["failed"].append(module_name)
                result["errors"].append(f"{module_name}: {e}")
                report(f"Failed to update {module_name}: {e}")

        # 3. Save updated manifest
        save_manifest(local_manifest)
        report(f"Update check complete. {len(result['updated'])} modules updated.")

    except Exception as e:
        result["errors"].append(str(e))
        report(f"Update cycle failed: {e}")
        traceback.print_exc(file=sys.stderr)

    return result


def _update_module(module_name: str, remote_file: str, remote_info: dict,
                   local_path: str, report):
    """Download and install a single module with rollback safety."""
    # 1. Backup existing module
    if os.path.exists(local_path):
        backup_path = os.path.join(BACKUP_DIR, f"{module_name}.py.bak")
        shutil.copy2(local_path, backup_path)
        report(f"Backed up {module_name} for rollback")

    # 2. Download new module
    report(f"Downloading {module_name}...")
    new_content = _download_raw(remote_file)
    new_hash = _content_hash(new_content)

    # 3. Write to temp file first
    temp_path = local_path + ".tmp"
    with open(temp_path, "wb") as f:
        f.write(new_content)

    # 4. Validate the new module
    report(f"Validating {module_name}...")
    valid = _validate_module(temp_path, module_name)

    if valid:
        # 5a. Activate — replace old with new
        os.replace(temp_path, local_path)

        # Update manifest
        manifest = load_manifest()
        manifest.setdefault("modules", {})[module_name] = {
            "version": remote_info.get("version", "0.0.0"),
            "hash": new_hash,
            "updated_at": datetime.now().isoformat(),
            "file": remote_file
        }
        save_manifest(manifest)
        report(f"✓ {module_name} updated successfully")
    else:
        # 5b. Rollback — restore backup
        report(f"✗ {module_name} failed validation, rolling back")
        os.remove(temp_path)
        backup_path = os.path.join(BACKUP_DIR, f"{module_name}.py.bak")
        if os.path.exists(backup_path):
            shutil.copy2(backup_path, local_path)
            report(f"Rolled back {module_name} to previous version")

        # Log the failure
        health = load_health_log()
        health.setdefault("modules", {})[module_name] = {
            "status": "rollback",
            "reason": "validation_failed",
            "timestamp": datetime.now().isoformat()
        }
        save_health_log(health)


def _validate_module(filepath: str, module_name: str) -> bool:
    """
    Validate a module file by attempting to import it and checking
    that it implements the required interface.
    """
    try:
        spec = importlib.util.spec_from_file_location(
            f"hydra_validate_{module_name}", filepath
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Check for required class
        service_class = None
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if (isinstance(attr, type) and
                hasattr(attr, 'get_info') and
                hasattr(attr, 'download') and
                attr_name != 'BaseService'):
                service_class = attr
                break

        if service_class is None:
            sys.stderr.write(f"[VALIDATE] {module_name}: No service class found\n")
            return False

        # Try instantiation
        instance = service_class()
        info = instance.get_info()
        if not info or not info.name:
            sys.stderr.write(f"[VALIDATE] {module_name}: Invalid module info\n")
            return False

        sys.stderr.write(f"[VALIDATE] {module_name}: OK ({info.name} v{info.version})\n")
        return True

    except Exception as e:
        sys.stderr.write(f"[VALIDATE] {module_name}: Failed — {e}\n")
        return False


# ════════════════════════════════════════════════════════════════
# MODULE LOADING
# ════════════════════════════════════════════════════════════════

def discover_modules() -> dict:
    """
    Discover and load all available service modules.
    Returns dict of module_name → service instance.
    """
    if not MODULES_DIR:
        return {}

    modules = {}

    for filename in os.listdir(MODULES_DIR):
        if not filename.endswith(".py"):
            continue
        if filename.startswith("_") or filename == "base_service.py":
            continue

        module_name = filename[:-3]
        try:
            filepath = os.path.join(MODULES_DIR, filename)
            spec = importlib.util.spec_from_file_location(
                f"hydra_service_{module_name}", filepath
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            # Find the service class
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if (isinstance(attr, type) and
                    hasattr(attr, 'get_info') and
                    hasattr(attr, 'download') and
                    attr_name != 'BaseService'):
                    instance = attr()
                    info = instance.get_info()
                    modules[module_name] = {
                        "instance": instance,
                        "info": info,
                        "status": "loaded"
                    }
                    sys.stderr.write(f"[HYDRA] Loaded module: {info.name} v{info.version}\n")
                    break

        except Exception as e:
            sys.stderr.write(f"[HYDRA] Failed to load {module_name}: {e}\n")
            modules[module_name] = {
                "instance": None,
                "info": None,
                "status": "error",
                "error": str(e)
            }

    return modules


def health_check(modules: dict) -> dict:
    """
    Run health checks on all loaded modules.
    Disables modules that fail validation.
    """
    results = {}
    health = load_health_log()

    for name, mod_data in modules.items():
        instance = mod_data.get("instance")
        if not instance:
            results[name] = {"healthy": False, "message": "Not loaded"}
            continue

        try:
            validation = instance.validate()
            healthy = validation.get("valid", False)
            results[name] = {
                "healthy": healthy,
                "message": validation.get("message", ""),
                "missing_deps": validation.get("missing_deps", [])
            }

            health.setdefault("modules", {})[name] = {
                "status": "healthy" if healthy else "unhealthy",
                "message": validation.get("message", ""),
                "timestamp": datetime.now().isoformat(),
                "consecutive_failures": 0 if healthy else
                    health.get("modules", {}).get(name, {}).get("consecutive_failures", 0) + 1
            }

            # Auto-disable after 3 consecutive failures
            if health["modules"][name].get("consecutive_failures", 0) >= 3:
                mod_data["status"] = "disabled"
                results[name]["message"] += " (auto-disabled after 3 failures)"
                sys.stderr.write(f"[HYDRA] Auto-disabled {name} after 3 consecutive failures\n")

        except Exception as e:
            results[name] = {"healthy": False, "message": str(e)}

    save_health_log(health)
    return results


def auto_install_deps(module_name: str, deps: list) -> dict:
    """
    Attempt to auto-install missing dependencies for a module.
    Part of the self-healing system.
    """
    import subprocess

    results = {"installed": [], "failed": []}

    for dep in deps:
        try:
            sys.stderr.write(f"[HYDRA] Auto-installing dependency: {dep}\n")
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", dep, "--quiet"],
                timeout=120
            )
            results["installed"].append(dep)
        except Exception as e:
            results["failed"].append({"package": dep, "error": str(e)})
            sys.stderr.write(f"[HYDRA] Failed to install {dep}: {e}\n")

    return results
