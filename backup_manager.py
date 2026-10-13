import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple
from config import BACKUPS_DIR, ORIGINAL_BACKUPS_DIR, HISTORY_BACKUPS_DIR

def init_backup_dirs():
    BACKUPS_DIR.mkdir(exist_ok=True)
    ORIGINAL_BACKUPS_DIR.mkdir(exist_ok=True)
    HISTORY_BACKUPS_DIR.mkdir(exist_ok=True)

def ensure_clean_backup(target_files: Dict[str, Path]) -> List[str]:
    """Saves pristine original copies of files upon first detection if not already present."""
    init_backup_dirs()
    backed_up = []
    for key, path in target_files.items():
        if key == "autoexec_cfg":
            continue
        if not path.exists():
            continue
        dest = ORIGINAL_BACKUPS_DIR / path.name
        # Only copy if original doesn't already exist to preserve factory files
        if not dest.exists():
            shutil.copy2(path, dest)
            backed_up.append(path.name)
    return backed_up

def create_versioned_backup(target_files: Dict[str, Path], tag: str = "auto") -> Path:
    """Creates a timestamped backup before modifications."""
    init_backup_dirs()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    folder_name = f"{timestamp}_{tag}"
    dest_dir = HISTORY_BACKUPS_DIR / folder_name
    dest_dir.mkdir(exist_ok=True)

    for key, path in target_files.items():
        if path.exists():
            shutil.copy2(path, dest_dir / path.name)

    return dest_dir

def restore_clean_original(target_files: Dict[str, Path]) -> Tuple[bool, List[str]]:
    """Restores files from the pristine backups/original directory."""
    init_backup_dirs()
    restored = []
    missing = []
    for key, dest_path in target_files.items():
        if key == "autoexec_cfg":
            continue
        src_path = ORIGINAL_BACKUPS_DIR / dest_path.name
        if src_path.exists():
            try:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path, dest_path)
                restored.append(dest_path.name)
            except Exception as e:
                print(f"Failed to restore {dest_path.name}: {e}")
        else:
            missing.append(dest_path.name)
    
    success = len(restored) > 0 and len(missing) == 0
    return success, restored

def list_history_backups() -> List[dict]:
    """Returns a list of previous backups with timestamp and file count."""
    init_backup_dirs()
    backups = []
    for p in sorted(HISTORY_BACKUPS_DIR.iterdir(), reverse=True):
        if p.is_dir():
            files = list(p.glob("*"))
            backups.append({
                "folder": p.name,
                "path": p,
                "time": p.name.split("_")[0] + " " + p.name.split("_")[1].replace("-", ":"),
                "count": len(files)
            })
    return backups

def restore_from_history(backup_folder_name: str, target_files: Dict[str, Path]) -> Tuple[bool, str]:
    src_dir = HISTORY_BACKUPS_DIR / backup_folder_name
    if not src_dir.exists():
        return False, f"Каталог бэкапа {backup_folder_name} не найден."
    
    restored = []
    for key, dest_path in target_files.items():
        src_file = src_dir / dest_path.name
        if src_file.exists():
            try:
                shutil.copy2(src_file, dest_path)
                restored.append(dest_path.name)
            except Exception as e:
                return False, f"Ошибка восстановления {dest_path.name}: {e}"
                
    return True, restored
