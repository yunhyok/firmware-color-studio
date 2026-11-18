"""Keep the suite away from the stored preferences of an installed Firmware Color Studio."""

import pytest
from PySide6.QtCore import QSettings

from firmware_color_studio import app


@pytest.fixture(autouse=True)
def isolated_preferences(tmp_path_factory, monkeypatch):
    # MainWindow saves the chosen language. Without this, tests would read and overwrite the
    # user's own setting (the registry on Windows) and depend on what an earlier run left there.
    # QSettings(organization, application) is always the native store, so the class is replaced.
    store = str(tmp_path_factory.mktemp("preferences") / "preferences.ini")
    monkeypatch.setattr(app, "QSettings", lambda *args: QSettings(store, QSettings.Format.IniFormat))
