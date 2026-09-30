# SpaceFree

A Windows desktop app that scans your whole disk, shows **why it is full**, and helps you clean it safely.
Everything runs offline on your PC - no file names or data are sent anywhere.

## Run

```
pip install -r requirements.txt
python main.py
```

## What it does

- Scans all fixed drives (removable ones optional) with a multi-threaded walker.
- Labels what it finds:
  - **Bad** - safe to delete (temp files, caches, crash dumps, old installers, duplicate copies, stale `node_modules`).
  - **Review** - probably removable but check first (virtual disks, big unused files, large old downloads).
  - **Important** - Windows, Program Files, ProgramData, and your personal folders. Never deletable here.
  - **Good** - everything else that looks normal.
- Every finding includes a plain-English reason.
- **Live results:** everything updates while the scan runs - findings, biggest folders, space by file type, media, folder tree and size map. No waiting for the end.
- **Space by file type** for *all* files (video, images, audio, documents, archives, disk images, code, apps, other), not just system junk.
- **Open folder** buttons (and double-click / right-click) jump straight to the file or folder in Explorer for review.
- Tabs: Summary, Cleanup (tick and remove), **Media** (every image, video and audio file with a real preview and playback), Folders (size tree), Size map (treemap).
- Export the findings to CSV.
- **Advisor** (System One style): a small offline model asks five narrow questions about every finding and media file
  (is it educational? recreatable? irreplaceable? how stale? what kind?), each answered as a typed probability with a
  confidence, never free text. Plain code then turns the answers into one verdict:
  **Delete** (safe, recreatable), **Review** (not sure), **Keep** (good, no need to delete), **Educational** (course/lecture/book
  material, protected from bulk delete). The Advisor tab shows it in four groups with a one-click "move everything marked Delete".
  Nothing leaves your PC.

## Safety

- Deleting only **moves items to the Recycle Bin**, after a confirmation dialog, and re-checks the protection rules first.
- System folders, drive roots, core user folders and system files (`pagefile.sys`, `hiberfil.sys`) cannot be deleted.
- Personal files (Documents, Pictures, Desktop, Videos, Music, OneDrive) are never auto-labelled Bad.
- Cloud-only OneDrive files are ignored (they use no disk space).
- Caveat: Windows may delete items permanently if they are larger than the Recycle Bin's size limit.

## Layout

```
main.py                 app entry
spacefree/scanner.py    parallel disk walk + folder size tree
spacefree/rules.py      Bad / Review / Good / Important rules
spacefree/duplicates.py size -> partial hash -> full hash
spacefree/safety.py     protected paths
spacefree/advisor/      the Advisor: questions, features, model, decide
spacefree/cleaner.py    Recycle Bin moves
spacefree/ui/           PyQt6 interface
tests/                  pytest suite
```

## Tests

```
python -m pytest
```

## Build an .exe (optional)

```
pip install pyinstaller
pyinstaller --noconsole --onefile --name SpaceFree main.py
```
