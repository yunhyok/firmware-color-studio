"""Convert the sRGB preview to the Windows monitor's ICC color space."""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

import numpy as np
from PySide6.QtGui import QColorSpace, QImage


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("bounds", wintypes.RECT),
        ("work_area", wintypes.RECT),
        ("flags", wintypes.DWORD),
        ("device", wintypes.WCHAR * 32),
    ]


def _monitor_device(hwnd: int) -> str | None:
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user.MonitorFromWindow.restype = wintypes.HMONITOR
    user.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo)]
    user.GetMonitorInfoW.restype = wintypes.BOOL
    monitor = user.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    info = _MonitorInfo(size=ctypes.sizeof(_MonitorInfo))
    if monitor and user.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return info.device or None
    return None


def monitor_space(hwnd: int | None = None) -> tuple[QColorSpace, str]:
    srgb = QColorSpace(QColorSpace.NamedColorSpace.SRgb)
    if sys.platform != "win32":
        return srgb, "sRGB"
    fallback = (srgb, "sRGB (monitor ICC unavailable)")
    device = _monitor_device(hwnd) if hwnd else None
    if device is None:
        return fallback
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    gdi.CreateDCW.argtypes = [wintypes.LPCWSTR] * 3 + [wintypes.LPVOID]
    gdi.CreateDCW.restype = wintypes.HDC
    gdi.GetICMProfileW.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR]
    gdi.GetICMProfileW.restype = wintypes.BOOL
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    gdi.DeleteDC.restype = wintypes.BOOL
    dc = gdi.CreateDCW(device, None, None, None)
    if not dc:
        return fallback
    try:
        size = wintypes.DWORD(32768)
        path = ctypes.create_unicode_buffer(size.value)
        if gdi.GetICMProfileW(dc, ctypes.byref(size), path):
            data = Path(path.value).read_bytes()
            space = QColorSpace.fromIccProfile(data)
            if space.isValid():
                return space, Path(path.value).name
    except (OSError, ValueError):
        pass
    finally:
        gdi.DeleteDC(dc)
    return fallback


def rgb_image(rgb: np.ndarray, target: QColorSpace | None = None) -> QImage:
    pixels = np.ascontiguousarray(np.round(np.clip(rgb, 0, 1) * 65535), dtype=np.uint16)
    rgba = np.empty((*pixels.shape[:2], 4), dtype=np.uint16)
    rgba[..., :3], rgba[..., 3] = pixels, 65535
    height, width = pixels.shape[:2]
    image = QImage(rgba.data, width, height, rgba.strides[0], QImage.Format.Format_RGBA64).copy()
    image.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    if target is not None and target.isValid() and image.colorSpace() != target:
        converted = image.convertedToColorSpace(target)
        if not converted.isNull():
            image = converted
    return image.convertToFormat(QImage.Format.Format_RGB32)
