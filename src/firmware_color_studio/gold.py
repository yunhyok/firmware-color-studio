"""K-3 III Gold: integer LUT composition and final hardware gamma tables.

Only numerical parameters are included. See docs/gold.md for original-code
verification, hardware channel mapping, and the fixed nominal runtime state.
"""
from functools import lru_cache
import json
from pathlib import Path

import numpy as np


@lru_cache(maxsize=1)
def _tables():
    data = json.loads((Path(__file__).parent / 'data/k3iii/gold-tables.json').read_text(encoding='utf-8'))
    return (np.array([data['gold_rgb'][c] for c in 'rgb'], dtype=np.int64),
            np.array(data['adobergb_thresholds'], dtype=np.int64))


def runtime_spec():
    """No safely established user runtime controls; nominal state is fixed."""
    return {}


def _interpolate(tables, values):
    """Firmware 0x53136d24/0x53136e54; signed division truncates toward zero."""
    values = np.asarray(values, dtype=np.int64)
    index = np.minimum(values >> 6, 255)
    left = tables[:, index]
    product = (tables[:, np.minimum(index + 1, 255)] - left) * (values & 63)
    return (left + np.sign(product) * (np.abs(product) // 64)) & 0xffff


def _hardware(channels, color_space):
    """Return exact 256-point bases, packed deltas, and 4096-point response."""
    if color_space not in ('srgb', 'adobergb'):
        raise ValueError('color_space must be srgb or adobergb')
    if color_space == 'adobergb':
        full = np.searchsorted(_tables()[1], channels, side='right') - 1
    else:
        full = np.minimum(channels >> 4, 1023)
    delta = np.clip(np.diff(full, axis=1, append=full[:, -1:]), 0, 240)
    fractional = delta[..., None] * np.arange(16) // 16
    increments = np.diff(fractional, axis=-1, prepend=np.zeros((*delta.shape, 1), dtype=np.int64))
    words = np.sum(increments.astype(np.uint64) << (np.arange(16, dtype=np.uint64) * 4), axis=-1, dtype=np.uint64)
    response = (full[..., None] + fractional).reshape(len(full), 4096)
    return full, words, response


def _calculate(engine, settings, color_space):
    if not isinstance(settings, dict):
        raise ValueError('settings must be a dictionary')
    if any(type(v) is not int or not -4 <= v <= 4 for v in settings.values()):
        raise ValueError('Gold settings must be integers within -4..4')
    s = engine.settings('gold', **settings)
    base = np.array(engine._regular_curve(s['key'], s['contrast'], s['highlight'], -s['shadow'], 8192, 8192), dtype=np.int64)
    rgb = _interpolate(_tables()[0], base)
    y = (77 * rgb[0] + 150 * rgb[1] + 29 * rgb[2]) >> 8
    channels = np.vstack((rgb, y))
    return s, base, channels, _hardware(channels, color_space)


def gold_camera(engine, settings, color_space='srgb', runtime=None):
    """Build Gold with the exact final RGB gamma response at nominal state.

    runtime is empty: custom-curve state, scene/exposure-dependent tuning and
    setting override paths are not inferred from photographs or guessed.
    """
    if runtime is not None and (not isinstance(runtime, dict) or runtime):
        raise ValueError('Gold has no supported runtime overrides; use an empty dictionary')
    s, base, _, (_, _, response) = _calculate(engine, settings, color_space)
    camera = engine.camera('gold', color_space=color_space, curve=base, **s)
    camera.curves = response[:3].astype(np.float64)
    camera.curve_max = 1023.0
    camera.notes.update({'gold_model': 'firmware-2.20-integer-hardware',
                         'gamma_channel_order': 'R,G,B (register offsets 0x4768,0x4968,0x4b68)',
                         'exposure_gain': 8192, 'project_row': 0, 'runtime': {},
                         'custom_gamma_state_enabled': False, 'setting_override': False})
    return camera
