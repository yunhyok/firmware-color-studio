from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs
from pathlib import Path

root = Path(SPECPATH).parent
data = collect_data_files('firmware_color_studio')
data += collect_data_files('cv2', includes=['LICENSE*.txt'])
data += [(str(root / 'LICENSE'), '.'), (str(root / 'THIRD_PARTY_NOTICES.md'), '.')]
a = Analysis(
    [str(root / 'packaging' / 'entry.py')], pathex=[str(root / 'src')],
    binaries=collect_dynamic_libs('rawpy'), datas=data,
    hiddenimports=['firmware_color_studio.cli'],
    excludes=['unicorn', 'pypdf', 'pytest', 'tkinter', 'PySide6.QtWebEngineCore',
              'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtMultimedia'],
    noarchive=False,
)
pyz = PYZ(a.pure)
# The wheel ships a separate video codec plugin. Chart recognition consumes RGB pixels from Qt.
a.binaries = [entry for entry in a.binaries if not Path(entry[0]).name.startswith('opencv_videoio_ffmpeg')]
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='FirmwareColorStudio',
          console=False, debug=False, strip=False, upx=False,
          icon=str(root / 'src' / 'firmware_color_studio' / 'resources' / 'app.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='FirmwareColorStudio')
