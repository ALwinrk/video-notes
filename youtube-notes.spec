# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
from PyInstaller.building.datastruct import Tree

datas = []
binaries = []
hiddenimports = [
    'yt_dlp', 'openai', 'anthropic', 'PIL',
    'pipeline', 'gui', 'ffmpeg_locator', 'transcriber',
    'tkinter', 'tkinter.ttk', 'tkinter.filedialog', 'tkinter.messagebox',
    'queue', 'threading', 'logging',
    'faster_whisper', 'ctranslate2', 'huggingface_hub',
    'tokenizers', 'onnxruntime', 'av',
]
tmp_ret = collect_all('yt_dlp')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

ft_ret = collect_all('faster_whisper')
datas += ft_ret[0]; binaries += ft_ret[1]; hiddenimports += ft_ret[2]

ct_ret = collect_all('ctranslate2')
datas += ct_ret[0]; binaries += ct_ret[1]; hiddenimports += ct_ret[2]

hf_ret = collect_all('huggingface_hub')
datas += hf_ret[0]; binaries += hf_ret[1]; hiddenimports += hf_ret[2]

# Bundle ffmpeg + ffprobe
_FFMPEG_DIR = r'C:\dpreasonix\ffmpeg_bundle\ffmpeg-8.1.1-essentials_build\bin'
binaries += [
    (_FFMPEG_DIR + '\\ffmpeg.exe', '.'),
    (_FFMPEG_DIR + '\\ffprobe.exe', '.'),
]

# Whisper small model tree (added after Analysis below)

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

# Bundle pre-downloaded Whisper small model (~464 MB)
_whisper_tree = Tree(
    r'C:\dpreasonix\whisper_model_cache',
    prefix='whisper_model_cache',
    excludes=['.git', '__pycache__'],
)
a.datas += _whisper_tree

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='video-notes',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir='%LOCALAPPDATA%\\video-notes-v2',
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
