# Only these application resources enter the frozen server. User files never do.
from pathlib import Path

root = Path(SPECPATH).parent
analysis = Analysis(
    [str(root / 'backend' / 'desktop_entry.py')],
    pathex=[str(root / 'backend')],
    binaries=[],
    datas=[(str(root / 'VERSION'), '.'), (str(root / 'frontend' / 'dist'), 'frontend/dist')],
    hiddenimports=[
        'uvicorn.logging', 'uvicorn.loops.asyncio', 'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets.websockets_impl', 'uvicorn.lifespan.on',
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['pytest', 'PyInstaller', 'tkinter'], noarchive=False,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive, analysis.scripts, [], exclude_binaries=True,
    name='baize-backend', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True,
)
COLLECT(executable, analysis.binaries, analysis.datas, strip=False, upx=False, name='baize-backend')
