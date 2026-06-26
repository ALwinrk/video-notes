# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import os as _os

datas = []
binaries = []
hiddenimports = ['yt_dlp', 'openai', 'anthropic', 'PIL', 'youtube_transcript_api']
tmp_ret = collect_all('yt_dlp')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Bundle ffmpeg + ffprobe (required for frame extraction + audio processing)
_ffmpeg_dir = 'ffmpeg_bundle/ffmpeg-8.1.1-essentials_build/bin'
if _os.path.isdir(_ffmpeg_dir):
    for _f in _os.listdir(_ffmpeg_dir):
        _src = _os.path.join(_ffmpeg_dir, _f)
        if _os.path.isfile(_src):
            binaries.append((_src, '.'))

# Bundle whisper.cpp binary + model (if available)
_wcpp_exe = 'whisper.cpp.exe'
if _os.path.isfile(_wcpp_exe):
    binaries.append((_wcpp_exe, '.'))

_wcpp_model = 'ggml-tiny.bin'
if _os.path.isfile(_wcpp_model):
    datas.append((_wcpp_model, '.'))


a = Analysis(
    ['youtube_notes\\main.py'],
    pathex=['youtube_notes'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='youtube-notes',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
