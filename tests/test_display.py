import ctypes
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtGui import QColorSpace

from firmware_color_studio import display


def test_monitor_profile_uses_window_device_name(tmp_path, monkeypatch):
    profile = tmp_path / "second-monitor.icc"
    space = QColorSpace(QColorSpace.NamedColorSpace.DisplayP3)
    profile.write_bytes(bytes(space.iccProfile()))

    def monitor_info(_, pointer):
        info = ctypes.cast(pointer, ctypes.POINTER(display._MonitorInfo)).contents
        assert info.size == ctypes.sizeof(display._MonitorInfo)
        info.device = r"\\.\DISPLAY2"
        return True

    def get_profile(_, size, buffer):
        buffer.value = str(profile)
        return True

    user = SimpleNamespace(MonitorFromWindow=Mock(return_value=21), GetMonitorInfoW=Mock(side_effect=monitor_info))
    gdi = SimpleNamespace(CreateDCW=Mock(return_value=43), GetICMProfileW=Mock(side_effect=get_profile), DeleteDC=Mock())
    library = Mock(side_effect={"user32": user, "gdi32": gdi}.__getitem__)
    monkeypatch.setattr(display, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(display.ctypes, "WinDLL", lambda name, **_: library(name), raising=False)

    actual, description = display.monitor_space(17)
    assert actual == QColorSpace.fromIccProfile(space.iccProfile())
    assert description == profile.name
    user.MonitorFromWindow.assert_called_once_with(17, 2)
    gdi.CreateDCW.assert_called_once_with(r"\\.\DISPLAY2", None, None, None)
    gdi.DeleteDC.assert_called_once_with(43)


def test_missing_native_monitor_falls_back_without_creating_a_desktop_dc(monkeypatch):
    monkeypatch.setattr(display, "sys", SimpleNamespace(platform="win32"))
    library = Mock(return_value=SimpleNamespace(MonitorFromWindow=Mock(return_value=0), GetMonitorInfoW=Mock()))
    monkeypatch.setattr(display.ctypes, "WinDLL", library, raising=False)

    assert display.monitor_space()[0] == QColorSpace(QColorSpace.NamedColorSpace.SRgb)
    library.assert_not_called()
    assert display.monitor_space(17)[0] == QColorSpace(QColorSpace.NamedColorSpace.SRgb)
    library.assert_called_once_with("user32", use_last_error=True)
