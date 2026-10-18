import shutil
from pathlib import Path
from typing import Dict, Optional, Tuple
from config import ORIGINAL_BACKUPS_DIR

MODE_ORIGINAL = "original"
MODE_SKY = "sky"
MODE_BLACK = "black"

# 2. Recommended lightweight procedural sky dome (no 3D models, zero VRAM overhead)
SKY_LUA_CONTENT = '''package.path = package.path ..';./Scripts/DemoScenes/?.lua;'
local sceneEnvironment = require("demosceneEnvironment")

scene = {}

function loadScene(scenePtr)
    sceneAPI = sceneEnvironment.getInterface(scenePtr)
    sceneAPI:setUpdateFunc('sceneVRUpdate')

    -- Процедурное небо DCS: легкий купол атмосферы без 3D-моделей
    sceneAPI:setSky(true)
    sceneAPI:setSun(math.rad(35), math.rad(45))

    local cam_level = 1.8

    scene.cam        = sceneAPI:addCamera(0, cam_level, 0)
    scene.cam:setFarClip(10000.0)
    scene.cam:setFov(90)
    scene.cam.transform:lookAtPoint(0, cam_level, 10.0)
    scene.cam:setActive()
end

--[0;1]
local function pingpong(length, t)
    local tt = (t%length)*2/length
    if tt>1 then tt = 2-tt end
    return tt
end

function sceneVRUpdate(t, dt)

end
'''

# 3. Minimalist empty camera forum mod (pure black background, zero rendering)
BLACK_LUA_CONTENT = '''package.path = package.path ..';./Scripts/DemoScenes/?.lua;'
local sceneEnvironment = require("demosceneEnvironment")

scene = {}

function loadScene(scenePtr)
    sceneAPI = sceneEnvironment.getInterface(scenePtr)
    sceneAPI:setUpdateFunc('sceneVRUpdate')
    sceneAPI:setSun(math.rad(-90), math.rad(0))

    local cam_level = 1.8

    scene.cam        = sceneAPI:addCamera(3, cam_level, 3)
    scene.cam:setFarClip(1000.0)
    scene.cam:setFov(90)
    scene.cam.transform:lookAtPoint(-10.0, cam_level, 0)
    scene.cam:setActive()
end

--[0;1]
local function pingpong(length, t)
    local tt = (t%length)*2/length
    if tt>1 then tt = 2-tt end
    return tt
end

function sceneVRUpdate(t, dt)

end
'''

def get_scene_vr_file(target_files: Dict[str, Path]) -> Path:
    return target_files.get("SceneVR_lua")


def get_original_scene_vr_file(target_files: Dict[str, Path]) -> Optional[Path]:
    scene_file = get_scene_vr_file(target_files)
    if not scene_file:
        return None
    return ORIGINAL_BACKUPS_DIR / scene_file.name


def _looks_like_original_scene(content: bytes) -> bool:
    return (
        b"setSky(true)" not in content
        and any(marker in content for marker in (b"su-27", b"ukrytie", b"waitForModels"))
    )


def has_valid_original_scene_vr_backup(target_files: Dict[str, Path]) -> bool:
    backup_path = get_original_scene_vr_file(target_files)
    if not backup_path or not backup_path.is_file():
        return False
    try:
        content = backup_path.read_bytes()
    except OSError:
        return False
    return _looks_like_original_scene(content)


def detect_scene_vr_mode(target_files: Dict[str, Path]) -> str:
    """Returns 'original', 'sky', 'black', or 'unknown' based on the file contents."""
    file_path = get_scene_vr_file(target_files)
    if not file_path or not file_path.exists():
        return "unknown"

    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        if "setSky(true)" in content:
            return MODE_SKY
        if "su-27" in content or "ukrytie" in content or "waitForModels" in content:
            return MODE_ORIGINAL
        if "sceneAPI:addCamera" in content:
            return MODE_BLACK
    except Exception:
        pass

    return "unknown"


def restore_scene_vr_original(target_files: Dict[str, Path]) -> Tuple[bool, str]:
    """Restore the complete SceneVR.lua from the preserved original backup."""
    file_path = get_scene_vr_file(target_files)
    backup_path = get_original_scene_vr_file(target_files)
    if not file_path or not backup_path:
        return False, "Target file path not configured"
    if not backup_path.is_file():
        return False, f"Original backup not found: {backup_path}"
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_path, file_path)
        return True, ""
    except OSError as error:
        return False, str(error)


def ensure_scene_vr_backup(target_files: Dict[str, Path]) -> bool:
    """Preserve the active factory scene and repair an invalid backup from it."""
    backup_file = get_original_scene_vr_file(target_files)
    if not backup_file:
        return False
    if has_valid_original_scene_vr_backup(target_files):
        return True

    file_path = get_scene_vr_file(target_files)
    if not file_path or not file_path.is_file():
        return False
    try:
        content = file_path.read_bytes()
        if not _looks_like_original_scene(content):
            return False
        ORIGINAL_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        backup_file.write_bytes(content)
        return has_valid_original_scene_vr_backup(target_files)
    except OSError:
        return False

def apply_scene_vr_mode(target_files: Dict[str, Path], mode: str) -> Tuple[bool, str]:
    """Applies the selected VR scene mode to SceneVR.lua with automatic backup."""
    file_path = get_scene_vr_file(target_files)
    if not file_path:
        return False, "Target file path not configured"

    if mode == MODE_ORIGINAL:
        return restore_scene_vr_original(target_files)

    if not file_path.parent.exists():
        return False, f"Directory does not exist: {file_path.parent}"

    # Always ensure clean backup exists before applying any changes
    if not ensure_scene_vr_backup(target_files):
        return False, "Could not preserve the original SceneVR.lua before modification"

    content_map = {
        MODE_SKY: SKY_LUA_CONTENT,
        MODE_BLACK: BLACK_LUA_CONTENT,
    }

    content = content_map.get(mode)
    if not content:
        return False, f"Unknown mode: {mode}"

    try:
        file_path.write_text(content, encoding="utf-8")
        return True, ""
    except OSError as e:
        return False, str(e)
