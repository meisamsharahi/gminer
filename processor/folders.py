"""Directory-only browser for the local dashboard."""
from pathlib import Path


def list_folders(path=None):
    current = Path(path).expanduser() if path else Path.home()
    if not current.is_absolute():
        raise ValueError("Enter an absolute folder path.")
    current = current.resolve(strict=True)
    if not current.is_dir():
        raise ValueError("Choose a folder, rather than a file.")
    children = []
    for child in current.iterdir():
        try:
            if not child.name.startswith(".") and child.is_dir():
                children.append({"name": child.name, "path": str(child)})
        except OSError:
            continue
    children.sort(key=lambda child: (child["name"].casefold(), child["name"]))
    home = Path.home()
    candidates = [("Home", home), ("Downloads", home / "Downloads"),
                  ("Documents", home / "Documents"), ("Desktop", home / "Desktop"),
                  ("Project", Path(__file__).resolve().parent.parent), ("Volumes", Path("/Volumes"))]
    shortcuts = [{"name": name, "path": str(folder.resolve())} for name, folder in candidates if folder.is_dir()]
    breadcrumbs = [{"name": current.anchor, "path": current.anchor}]
    for parent in reversed([current, *current.parents][:-1]):
        breadcrumbs.append({"name": parent.name, "path": str(parent)})
    return {"path": str(current), "parent": str(current.parent) if current.parent != current else None,
            "folders": children[:1000], "truncated": len(children) > 1000,
            "shortcuts": shortcuts, "breadcrumbs": breadcrumbs}


def create_folder(parent, name):
    name = name.strip()
    if not name or name in {".", ".."} or any(c in name for c in ('/', '\\', '\x00')):
        raise ValueError("Enter a folder name without slashes.")
    root = Path(parent).expanduser()
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("Choose an existing parent folder.")
    target = root.resolve() / name
    if target.exists():
        raise ValueError("A file or folder with that name already exists.")
    target.mkdir()
    return {"path": str(target)}
