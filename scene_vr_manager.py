import shutil
from pathlib import Path
from typing import Dict, Tuple
from config import ORIGINAL_BACKUPS_DIR

MODE_ORIGINAL = "original"
MODE_SKY = "sky"
MODE_BLACK = "black"

# 1. Factory original DCS SceneVR.lua with hangar, Su-27, and lights
ORIGINAL_LUA_CONTENT = '''package.path = package.path ..';./Scripts/DemoScenes/?.lua;'
local sceneEnvironment = require("demosceneEnvironment")

scene = {}

function loadScene(scenePtr)
\tsceneAPI = sceneEnvironment.getInterface(scenePtr)
\tsceneAPI:setUpdateFunc('sceneVRUpdate')
\tsceneAPI:setEnvironmentMap("Bazar/Graphics/VRMainScene.dds",0.9);
\tsceneAPI:setSun(math.rad(-90), math.rad(0))

\tscene.m\t\t\t= sceneAPI:addModel("su-27", 0, 2.4, 0);
\tscene.m:setArgument(0, 1);
\tscene.m:setArgument(3, 1);
\tscene.m:setArgument(5, 1);
\tscene.m:setArgument(4, 0.25);
\tscene.m:setArgument(6, 0.25);
\tscene.m:setArgument(115, 1);
\tscene.m:setArgument(116, 1);
\tscene.m:setArgument(117, 1);

\tlocal cam_level = 1.8

\tscene.cam\t\t= sceneAPI:addCamera(3, cam_level , 3)
\tscene.cam:setFarClip(1000.0)
\tscene.cam:setFov(90)
\tscene.cam.transform:lookAtPoint(-10.0, cam_level, 0);

\tscene.flr\t\t= sceneAPI:addModel("shelter_floor", 0,0,0);
\tscene.flr:drawToEnvironment(true);
\tscene.flr.transform:scale(2,1.5,1.5);

\tscene.sh\t\t= sceneAPI:addModel("ukrytie", 0,0,0); 
\tscene.sh:drawToEnvironment(true);
\tscene.sh.transform:scale(2,2,2);

\tscene.L1\t\t\t= sceneAPI:addLightOmni(0, 25, 0,\t1,0.8,0.5);
\tscene.L1:setRadius(200);
\tscene.L1:setAmount(1);

\tscene.cam:setActive()

\tpreloadList = 
\t{
\t\t{"su-27", \t\t  {}, {}},
\t\t{"shelter_floor", {}, {}},
\t\t{"ukrytie", \t  {}, {}},
\t}
\tsceneAPI:waitForModels(preloadList)\t
end

--[0;1]
local function pingpong(length, t)
\tlocal tt = (t%length)*2/length
\tif tt>1 then tt = 2-tt end
\treturn tt
end

function sceneVRUpdate(t, dt)

end
'''

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

def ensure_scene_vr_backup(target_files: Dict[str, Path]) -> bool:
    """Ensures pristine original backup of SceneVR.lua exists in backups/original/."""
    ORIGINAL_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    backup_file = ORIGINAL_BACKUPS_DIR / "SceneVR.lua"
    if backup_file.exists():
        return True

    file_path = get_scene_vr_file(target_files)
    if file_path and file_path.exists():
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            # Only backup if current file is indeed the original
            if "su-27" in content or "ukrytie" in content:
                shutil.copy2(file_path, backup_file)
                return True
        except Exception:
            pass

    # If file was already modded or missing, write our known pristine original content
    try:
        backup_file.write_text(ORIGINAL_LUA_CONTENT, encoding="utf-8")
        return True
    except Exception:
        return False

def apply_scene_vr_mode(target_files: Dict[str, Path], mode: str) -> Tuple[bool, str]:
    """Applies the selected VR scene mode to SceneVR.lua with automatic backup."""
    file_path = get_scene_vr_file(target_files)
    if not file_path:
        return False, "Target file path not configured"

    if not file_path.parent.exists():
        return False, f"Directory does not exist: {file_path.parent}"

    # Always ensure clean backup exists before applying any changes
    ensure_scene_vr_backup(target_files)

    content_map = {
        MODE_ORIGINAL: ORIGINAL_LUA_CONTENT,
        MODE_SKY: SKY_LUA_CONTENT,
        MODE_BLACK: BLACK_LUA_CONTENT,
    }

    content = content_map.get(mode)
    if not content:
        return False, f"Unknown mode: {mode}"

    try:
        file_path.write_text(content, encoding="utf-8")
        return True, ""
    except Exception as e:
        return False, str(e)
