"""Update check for copies installed from a zip file.

Every copy, however it was installed, looks at the release index on GitHub
shortly after Blender starts, tells the user when a newer version exists, and
installs it on request. A copy installed from the TARTEEB update link is
updated through that link; a copy installed from a zip downloads the new zip. Nothing is sent anywhere; it only
downloads the public index and the add-on zip, and only when Blender's
"Allow Online Access" is on.
"""

import hashlib
import json
import os
import tempfile
import threading
import tomllib
import urllib.request

import bpy

INDEX_URL = "https://mtarteeb.github.io/technical-drawings/index.json"
PKG_ID = "technical_drawings"
TIMEOUT = 12

state = {
    'status': 'IDLE',        # IDLE | CHECKING | CURRENT | AVAILABLE | ERROR | INSTALLING | INSTALLED
    'latest': None,          # version string on the server
    'archive': None,         # absolute URL of the newest zip
    'hash': None,            # "sha256:..." of that zip
    'message': "",
}


def current_version():
    path = os.path.join(os.path.dirname(__file__), "blender_manifest.toml")
    try:
        with open(path, 'rb') as fh:
            return tomllib.load(fh).get("version", "0.0.0")
    except (OSError, tomllib.TOMLDecodeError):
        return "0.0.0"


# The version whose code is running. If the files on disk are replaced while
# Blender is open, the two differ until Blender is restarted.
LOADED_VERSION = current_version()


def restart_needed():
    return current_version() != LOADED_VERSION


def _as_tuple(version):
    parts = []
    for piece in version.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def repo_module():
    """Name of the Blender repository this copy is installed in, or None."""
    parts = (__package__ or "").split(".")
    return parts[1] if len(parts) >= 3 and parts[0] == "bl_ext" else None


def managed_by_blender():
    """True when this copy came from a remote repository, which Blender updates."""
    module = repo_module()
    for repo in bpy.context.preferences.extensions.repos:
        if repo.module == module:
            return bool(repo.use_remote_url and repo.remote_url)
    return False


def online_allowed():
    return bool(getattr(bpy.app, "online_access", True))


def _fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "technical-drawings-updater"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def check():
    """Look up the newest released version. Blocking; safe to call from a thread."""
    state.update(status='CHECKING', message="")
    try:
        index = json.loads(_fetch(INDEX_URL).decode("utf-8"))
        entry = next(e for e in index.get("data", []) if e.get("id") == PKG_ID)
        latest = entry["version"]
        archive = entry["archive_url"]
        if not archive.startswith("http"):
            archive = INDEX_URL.rsplit("/", 1)[0] + "/" + archive.lstrip("./")
        state.update(latest=latest, archive=archive, hash=entry.get("archive_hash"))
        if _as_tuple(latest) > _as_tuple(current_version()):
            state.update(status='AVAILABLE', message="Version %s is available" % latest)
        else:
            state.update(status='CURRENT', message="You have the latest version")
    except StopIteration:
        state.update(status='ERROR', message="The add-on was not found in the release list")
    except Exception as err:                       # network errors, bad JSON
        state.update(status='ERROR', message="Could not check for updates: %s" % err)
    return state['status']


def _redraw():
    wm = bpy.context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            area.tag_redraw()


def check_in_background():
    """Start a check without freezing Blender; the panels refresh when it ends."""
    if state['status'] in {'CHECKING', 'INSTALLING'}:
        return
    state.update(status='CHECKING', message="")
    thread = threading.Thread(target=check, daemon=True)
    thread.start()

    def poll():
        if thread.is_alive():
            return 0.5
        _redraw()
        return None

    # persistent: opening a .blend file must not cancel the check.
    bpy.app.timers.register(poll, first_interval=0.5, persistent=True)


def ensure_checked():
    """Start the update check if it has not run yet in this Blender session.

    Called whenever the panel is drawn, so the check happens however Blender
    was started (from the icon, or by opening a .blend file) and does not
    depend on a start-up timer surviving.
    """
    if state['status'] == 'IDLE' and not bpy.app.background and online_allowed():
        state['status'] = 'CHECKING'

        def start():
            state['status'] = 'IDLE'
            check_in_background()
            return None

        bpy.app.timers.register(start, first_interval=0.1, persistent=True)


def install():
    """Download the newest zip, verify it, and install it over this copy."""
    module = repo_module()
    if module is None:
        state.update(status='ERROR', message="This copy was not installed as an extension")
        return False
    if not state.get('archive'):
        if check() != 'AVAILABLE':
            return False
    state.update(status='INSTALLING', message="Downloading version %s..." % state['latest'])
    if managed_by_blender():
        # Installed from the update link: let Blender fetch it from that link.
        latest = state['latest']
        try:
            repos = bpy.context.preferences.extensions.repos
            index = next(i for i, r in enumerate(repos) if r.module == module)
            bpy.ops.extensions.repo_sync(repo_index=index)
            result = bpy.ops.extensions.package_install(repo_index=index, pkg_id=PKG_ID,
                                                        enable_on_install=True)
        except Exception as err:
            state.update(status='ERROR', message="Could not install the update: %s" % err)
            return False
        if 'FINISHED' not in result:
            state.update(status='ERROR', message="Blender did not install the update")
            return False
        state.update(status='INSTALLED', message="Updated to version %s" % latest)
        return True
    try:
        data = _fetch(state['archive'])
        expected = state.get('hash') or ""
        if expected.startswith("sha256:"):
            if hashlib.sha256(data).hexdigest() != expected.split(":", 1)[1]:
                raise ValueError("the downloaded file did not match its checksum")
        folder = tempfile.mkdtemp(prefix="technical_drawings_update_")
        path = os.path.join(folder, "%s-%s.zip" % (PKG_ID, state['latest']))
        with open(path, 'wb') as fh:
            fh.write(data)
    except Exception as err:
        state.update(status='ERROR', message="Could not download the update: %s" % err)
        return False
    latest = state['latest']
    try:
        result = bpy.ops.extensions.package_install_files(
            filepath=path, repo=module, enable_on_install=True, overwrite=True)
    except Exception as err:
        state.update(status='ERROR', message="Could not install the update: %s" % err)
        return False
    finally:
        try:
            os.remove(path)
            os.rmdir(folder)
        except OSError:
            pass
    if 'FINISHED' not in result:
        state.update(status='ERROR', message="Blender did not install the update")
        return False
    state.update(status='INSTALLED', message="Updated to version %s" % latest)
    return True


def startup_check():
    """Called once shortly after Blender starts."""
    if bpy.app.background or not online_allowed():
        return None
    check_in_background()
    return None
