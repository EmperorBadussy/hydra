"""
╔══════════════════════════════════════════════════════════════════╗
║  HYDRA — Python Bridge                                           ║
║  JSON stdin/stdout IPC with Electron main process                ║
║                                                                    ║
║  "Cut off one head, two more grow back."                         ║
║                                                                    ║
║  Commands: search, download, get_metadata, list_modules,         ║
║            update_modules, health_check, module_status,          ║
║            authenticate, install_deps                             ║
╚══════════════════════════════════════════════════════════════════╝
"""

import sys
import os
import json
import traceback

# Ensure unbuffered output
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import module_updater

# ─── Global state ───
_modules = {}  # module_name → { instance, info, status }
_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def initialize():
    """Initialize the HYDRA bridge."""
    global _modules

    # Init module updater with base dir
    module_updater.init(_base_dir)

    # Auto-update modules on startup
    sys.stderr.write("[HYDRA] Checking for module updates...\n")
    try:
        update_result = module_updater.check_for_updates(
            progress_callback=lambda msg: sys.stderr.write(f"  {msg}\n")
        )
        if update_result["updated"]:
            sys.stderr.write(f"[HYDRA] Updated modules: {', '.join(update_result['updated'])}\n")
        if update_result["errors"]:
            for err in update_result["errors"]:
                sys.stderr.write(f"[HYDRA] Update error: {err}\n")
    except Exception as e:
        sys.stderr.write(f"[HYDRA] Update check failed: {e}\n")

    # Discover and load all modules
    _modules = module_updater.discover_modules()
    sys.stderr.write(f"[HYDRA] Loaded {len([m for m in _modules.values() if m['status'] == 'loaded'])} service modules\n")

    # Run health checks
    health = module_updater.health_check(_modules)
    for name, status in health.items():
        if not status["healthy"]:
            sys.stderr.write(f"[HYDRA] Module {name} unhealthy: {status['message']}\n")
            if status.get("missing_deps"):
                sys.stderr.write(f"[HYDRA] Auto-healing: installing deps for {name}\n")
                module_updater.auto_install_deps(name, status["missing_deps"])


def _find_service_for_url(url: str):
    """Auto-detect which service module handles a URL."""
    for name, mod_data in _modules.items():
        instance = mod_data.get("instance")
        if not instance or mod_data.get("status") != "loaded":
            continue
        try:
            patterns = instance.get_url_patterns()
            for pattern in patterns:
                if pattern in url:
                    return name, instance
        except Exception:
            continue
    return None, None


# ════════════════════════════════════════════════════════════════
# COMMAND HANDLERS
# ════════════════════════════════════════════════════════════════

def handle_list_modules(params):
    """List all available service modules."""
    modules_list = []
    for name, mod_data in _modules.items():
        info = mod_data.get("info")
        entry = {
            "name": name,
            "status": mod_data.get("status", "unknown"),
            "error": mod_data.get("error")
        }
        if info:
            entry.update({
                "display_name": info.name,
                "version": info.version,
                "description": info.description,
                "icon": info.icon,
                "requires_auth": mod_data["instance"].requires_auth() if mod_data.get("instance") else False,
                "authenticated": mod_data["instance"].is_authenticated() if mod_data.get("instance") else False,
            })
        modules_list.append(entry)

    return {"status": "ok", "data": {"modules": modules_list}}


def handle_update_modules(params):
    """Force update check for all modules."""
    global _modules

    def progress(msg):
        # Send progress event to Electron
        progress_msg = json.dumps({
            "status": "progress",
            "request_id": params.get("_request_id", ""),
            "data": {"message": msg}
        })
        sys.stdout.write(progress_msg + "\n")
        sys.stdout.flush()

    result = module_updater.check_for_updates(progress_callback=progress)

    # Reload modules if any were updated
    if result["updated"] or result["new_modules"]:
        _modules = module_updater.discover_modules()

    return {"status": "ok", "data": result}


def handle_health_check(params):
    """Run health checks on all modules."""
    results = module_updater.health_check(_modules)
    return {"status": "ok", "data": results}


def handle_module_status(params):
    """Get detailed status of a specific module."""
    name = params.get("module")
    if not name or name not in _modules:
        return {"status": "error", "error": f"Module not found: {name}"}

    mod_data = _modules[name]
    info = mod_data.get("info")
    instance = mod_data.get("instance")

    status = {
        "name": name,
        "status": mod_data.get("status"),
        "error": mod_data.get("error"),
    }

    if info:
        status.update({
            "display_name": info.name,
            "version": info.version,
            "description": info.description,
            "author": info.author,
            "icon": info.icon,
            "requires": info.requires,
            "min_hydra_version": info.min_hydra_version,
        })

    if instance:
        try:
            validation = instance.validate()
            status["validation"] = validation
            status["authenticated"] = instance.is_authenticated()
            status["qualities"] = instance.get_available_qualities()
        except Exception as e:
            status["validation"] = {"valid": False, "message": str(e)}

    return {"status": "ok", "data": status}


def handle_search(params):
    """Search across one or all service modules."""
    query = params.get("query", "")
    service = params.get("service")  # Optional: specific service
    media_type = params.get("media_type", "all")
    limit = params.get("limit", 20)

    if not query:
        return {"status": "error", "error": "No search query provided"}

    all_results = []

    if service:
        # Search specific service
        mod_data = _modules.get(service)
        if not mod_data or not mod_data.get("instance"):
            return {"status": "error", "error": f"Service not available: {service}"}
        try:
            results = mod_data["instance"].search(query, media_type, limit)
            all_results = [{"service": service, **r} for r in results]
        except Exception as e:
            return {"status": "error", "error": str(e)}
    else:
        # Search all services
        for name, mod_data in _modules.items():
            instance = mod_data.get("instance")
            if not instance or mod_data.get("status") != "loaded":
                continue
            try:
                results = instance.search(query, media_type, limit)
                for r in results:
                    all_results.append({"service": name, **r})
            except Exception as e:
                sys.stderr.write(f"[HYDRA] Search error in {name}: {e}\n")

    return {"status": "ok", "data": {"results": all_results, "query": query}}


def handle_get_metadata(params):
    """Get metadata for a URL."""
    url = params.get("url", "")
    service = params.get("service")

    if not url:
        return {"status": "error", "error": "No URL provided"}

    # Auto-detect service from URL if not specified
    if not service:
        service, instance = _find_service_for_url(url)
        if not service:
            return {"status": "error", "error": "Could not detect service for this URL"}
    else:
        mod_data = _modules.get(service)
        if not mod_data or not mod_data.get("instance"):
            return {"status": "error", "error": f"Service not available: {service}"}
        instance = mod_data["instance"]

    try:
        metadata = instance.get_metadata(url)
        return {"status": "ok", "data": {"service": service, **metadata}}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def handle_download(params, request_id):
    """Download content from a service."""
    url = params.get("url", "")
    service = params.get("service")
    quality = params.get("quality", "best")
    output_dir = params.get("output_dir", "")
    item_id = params.get("item_id", "")

    if not url:
        return {"status": "error", "error": "No URL provided"}

    if not output_dir:
        output_dir = os.path.join(os.path.expanduser("~"), "Videos", "HYDRA")
    os.makedirs(output_dir, exist_ok=True)

    # Auto-detect service
    if not service:
        service, instance = _find_service_for_url(url)
        if not service:
            return {"status": "error", "error": "Could not detect service for this URL"}
    else:
        mod_data = _modules.get(service)
        if not mod_data or not mod_data.get("instance"):
            return {"status": "error", "error": f"Service not available: {service}"}
        instance = mod_data["instance"]

    # Progress callback → sends events to Electron
    def on_progress(progress):
        msg = json.dumps({
            "status": "progress",
            "request_id": request_id,
            "item_id": item_id,
            "progress": progress.percent,
            "speed": progress.speed,
            "eta": progress.eta,
            "message": progress.message,
            "downloaded_bytes": progress.downloaded_bytes,
            "total_bytes": progress.total_bytes,
        })
        sys.stdout.write(msg + "\n")
        sys.stdout.flush()

    try:
        result = instance.download(url, output_dir, quality, progress_callback=on_progress)
        return {"status": "ok", "data": result}
    except Exception as e:
        # Self-healing: log the error for the module
        health = module_updater.load_health_log()
        health.setdefault("modules", {}).setdefault(service, {})
        errors = health["modules"][service].setdefault("runtime_errors", [])
        errors.append({
            "error": str(e),
            "url": url,
            "timestamp": __import__("datetime").datetime.now().isoformat()
        })
        # Cap at 50 errors
        health["modules"][service]["runtime_errors"] = errors[-50:]
        module_updater.save_health_log(health)

        return {"status": "error", "error": str(e), "service": service}


def handle_authenticate(params):
    """Authenticate with a service."""
    service = params.get("service")
    credentials = params.get("credentials", {})

    if not service:
        return {"status": "error", "error": "No service specified"}

    mod_data = _modules.get(service)
    if not mod_data or not mod_data.get("instance"):
        return {"status": "error", "error": f"Service not available: {service}"}

    try:
        result = mod_data["instance"].authenticate(credentials)
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def handle_install_deps(params):
    """Install missing dependencies for a module."""
    service = params.get("service")
    deps = params.get("deps", [])

    if not service or not deps:
        return {"status": "error", "error": "No service or deps specified"}

    result = module_updater.auto_install_deps(service, deps)
    return {"status": "ok", "data": result}


# ════════════════════════════════════════════════════════════════
# COMMAND ROUTER
# ════════════════════════════════════════════════════════════════

HANDLERS = {
    "list_modules": handle_list_modules,
    "update_modules": handle_update_modules,
    "health_check": handle_health_check,
    "module_status": handle_module_status,
    "search": handle_search,
    "get_metadata": handle_get_metadata,
    "authenticate": handle_authenticate,
    "install_deps": handle_install_deps,
}


def process_command(line):
    """Parse and execute a JSON command from stdin."""
    try:
        cmd = json.loads(line)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"JSON parse error: {e}\n")
        return

    action = cmd.get("action", "")
    params = cmd.get("params", {})
    request_id = cmd.get("request_id", "")

    if action == "download":
        result = handle_download(params, request_id)
    elif action == "update_modules":
        params["_request_id"] = request_id
        result = handle_update_modules(params)
    elif action in HANDLERS:
        result = HANDLERS[action](params)
    else:
        result = {"status": "error", "error": f"Unknown action: {action}"}

    result["request_id"] = request_id
    sys.stdout.write(json.dumps(result) + "\n")
    sys.stdout.flush()


# ════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════

def main():
    sys.stderr.write("HYDRA bridge started. Initializing...\n")
    initialize()
    sys.stderr.write("HYDRA bridge ready. Listening for commands...\n")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            process_command(line)
        except Exception as e:
            sys.stderr.write(f"Unhandled error: {traceback.format_exc()}\n")
            try:
                cmd = json.loads(line)
                request_id = cmd.get("request_id", "")
                error_resp = json.dumps({
                    "status": "error",
                    "error": str(e),
                    "request_id": request_id
                })
                sys.stdout.write(error_resp + "\n")
                sys.stdout.flush()
            except Exception:
                pass


if __name__ == "__main__":
    main()
