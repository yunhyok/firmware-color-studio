"""Compare Gold against original K-3 III 2.20 ARM code from user-supplied firmware.

Requires numpy, unicorn and the public k3iii_tuning_emulator.py harness at
pentax-k3iii-firmware-analysis commit aa885bc. No camera is accessed.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import random
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.dont_write_bytecode = True
from firmware_color_studio.engine import Engine
from firmware_color_studio.gold import _calculate, _hardware, _interpolate, _tables, gold_camera

SLIDERS = ('saturation', 'hue', 'key', 'contrast', 'highlight', 'shadow')
# The public harness uses old labels. These offsets are physical R,G,B,Yb.
OLD_KEYS = ('rgb', 'r', 'g', 'b')


def digest(array, dtype='<u2'):
    return hashlib.sha256(np.asarray(array, dtype=dtype).tobytes()).hexdigest()


def require_equal(actual, expected, label):
    if not np.array_equal(actual, expected):
        a, b = np.asarray(actual), np.asarray(expected)
        where = np.argwhere(a != b)[0].tolist() if a.shape == b.shape else 'shape'
        raise AssertionError(f'{label}: first mismatch {where}')


def cases():
    yield 'default', {k: 0 for k in SLIDERS}
    for key in SLIDERS:
        for value in range(-4, 5):
            if value:
                yield f'{key}_{value:+d}', {k: value if k == key else 0 for k in SLIDERS}
    for values in itertools.product((-4, 4), repeat=6):
        yield 'corner_' + '_'.join(map(str, values)), dict(zip(SLIDERS, values))
    rng = random.Random(0x53136D24)
    for i in range(40):
        yield f'mixed_{i}', {k: rng.randrange(-4, 5) for k in SLIDERS}


def verify(decoded, harness):
    sys.path.insert(0, str(harness))
    import k3iii_tuning_emulator as emu
    import unicorn
    rtos = emu.load_rtos(decoded)
    engine = Engine.load()
    saved = json.loads((ROOT / 'src/firmware_color_studio/data/k3iii/gold-tables.json').read_text())
    for index, (channel, address) in enumerate(zip('rgb', (0x53c1557c, 0x53c1598c, 0x53c15d8c))):
        original = emu.read_table(rtos, address, 256, 'H')
        require_equal(_tables()[0][index], original, f'source {channel}')
        assert digest(original) == saved['provenance']['gold_rgb'][channel]['u16le_sha256']
    conversion = np.array(emu.read_table(rtos, 0x53aa021c, 16385, 'H'))
    require_equal(np.searchsorted(_tables()[1], np.arange(16385), side='right') - 1,
                  np.minimum(conversion >> 4, 1023), 'all AdobeRGB thresholds')
    assert digest(conversion) == saved['provenance']['adobergb']['u16le_sha256']
    words = emu.read_table(rtos, 0x53aac900, 241, 'Q')
    for delta, word in enumerate(words):
        expanded = np.cumsum([(word >> (4*j)) & 15 for j in range(16)])
        require_equal(expanded, delta * np.arange(16) // 16, f'delta record {delta}')
    assert digest(words, '<u8') == saved['provenance']['delta']['u64le_sha256']

    tuning = emu.StillTuning(rtos)
    e = tuning.e
    trace = {'stage': 0, 'getter': 0, 'space': 0, 'pack': 0}
    def stage(em):
        setting = em.read(em.reg('r1'), 0xa0)
        assert (setting[0x98], setting[0x99], setting[0x8d]) == (0, 1, 0)
        assert em.r8(0x547bbe44 + 0x33) == 0
        trace['stage'] += 1
    def getter(em):
        frame = em.reg('r11')
        assert tuple(em.r32(frame + o) for o in (-0x3c, -0x38, -0x34)) == (0x53c1557c, 0x53c1598c, 0x53c15d8c)
        trace['getter'] += 1
    e.watch[0x53137564] = stage
    e.watch[0x53136d24] = getter
    for address, key in ((0x53137144, 'space'), (0x53135c60, 'pack')):
        e.watch[address] = lambda em, key=key: trace.__setitem__(key, trace[key]+1)

    fixtures = []
    aggregate = hashlib.sha256()
    completed = 0
    for space in ('srgb', 'adobergb'):
        for label, settings in cases():
            result = tuning.make(31, adobe_rgb=space == 'adobergb', **settings)
            assert not result.asserts, (label, result.asserts)
            s, base, channels, (full, diff, response) = _calculate(engine, settings, space)
            require_equal(base, result.gamma_curve, label + ': base')
            require_equal(channels, np.stack([result.channel_curves[c] for c in 'rgby']), label + ': channels')
            reg = result.registers
            actual_full = np.stack([reg.gamma_full[c] for c in OLD_KEYS])
            actual_diff = np.stack([reg.gamma_diff[c] for c in OLD_KEYS])
            actual_response = np.stack([reg.gamma_table(c) for c in OLD_KEYS])
            require_equal(full, actual_full, label + ': final bases')
            require_equal(diff, actual_diff, label + ': final delta words')
            require_equal(response, actual_response, label + ': final response')
            camera = gold_camera(engine, settings, space)
            require_equal(camera.curves, actual_response[:3], label + ': camera RGB')
            require_equal(camera.cc0, reg.cc0, label + ': cc0')
            require_equal(camera.yc, reg.yc, label + ': yc')
            assert reg.cc0_decimal_point == 1 and reg.cc1_control == 0
            assert np.all(reg.tone_table == 4096) and not reg.chroma_fixed
            require_equal(camera.csp_offset, reg.csp_offset, label + ': csp offset')
            require_equal(camera.csp_gain, reg.csp_gain, label + ': csp gain')
            require_equal(camera.csp_border, reg.csp_border, label + ': csp border')
            require_equal(camera.chroma_offset, reg.ycof[1:], label + ': chroma offset')
            assert camera.csp_enable == bool(reg.csp_control[0] & 1)
            aggregate.update(actual_full.astype('<u2').tobytes())
            aggregate.update(actual_diff.astype('<u8').tobytes())
            if label == 'default' or label.endswith('_+4') or label in ('corner_-4_-4_-4_-4_-4_-4', 'corner_4_4_4_4_4_4', 'mixed_0'):
                fixtures.append({'case': label, 'space': space, 'settings': settings,
                                 'full_u16_sha256': digest(actual_full), 'diff_u64_sha256': digest(actual_diff, '<u8'),
                                 'rgb4096_u16_sha256': digest(actual_response[:3]),
                                 'cc0_i16_sha256': digest(reg.cc0, '<i2'), 'yc_i16_sha256': digest(reg.yc, '<i2')})
            completed += 1
            if completed % 40 == 0:
                print(f'whole Make: {completed} cases passed', flush=True)
    whole_trace = dict(trace)
    assert whole_trace == dict.fromkeys(trace, completed)

    # Follow the original register-application function into synthetic MMIO/SRAM.
    # Independent Milbeaut names identify AA00/AC00/AE00/B000 as R/G/B/Yb.
    register_base, aperture = 0x28418000, 0x294a0000
    e.u.mem_map(register_base, 0x10000)
    e.u.mem_map(aperture, 0x10000)
    driver, hardware, wrapper = e.alloc(0x100), e.alloc(0x100), e.alloc(0x100)
    packed = result.info[emu.REGISTER_IMAGE:]
    parameter = e.alloc(len(packed))
    e.u.mem_write(parameter, packed)
    e.w32(driver+0x14, hardware)
    e.w32(hardware+0x1c, wrapper)
    e.w32(hardware+0x18, aperture)
    e.call(0x53256a18, wrapper, register_base)
    assert e.call(0x532512cc, driver, 12, parameter) == 1
    for i, old_key in enumerate(OLD_KEYS):
        actual = np.frombuffer(e.read(aperture+0xaa00+512*i,512),dtype='<u2')
        require_equal(actual, result.registers.gamma_full[old_key], f'physical channel {i} full')
        actual = np.frombuffer(e.read(aperture+0x8800+2048*i,2048),dtype='<u8')
        require_equal(actual, result.registers.gamma_diff[old_key], f'physical channel {i} diff')

    # Complete channel preparation, including its real getter, for every u16 input.
    gamma = e.r32(tuning.obj + emu.GAMMA_OBJECT)
    setting_ptr = e.alloc(0xa0)
    e.u.mem_write(setting_ptr, result.setting)
    for first in range(0, 65536, 256):
        values = np.arange(first, first+256, dtype=np.uint16)
        e.u.mem_write(gamma, values.astype('<u2').tobytes())
        e.call(0x531368e0, gamma, setting_ptr)
        rgb = _interpolate(_tables()[0], values)
        expected = np.vstack((rgb, (77*rgb[0]+150*rgb[1]+29*rgb[2]) >> 8))
        actual = np.stack([np.frombuffer(e.read(gamma+off,512),dtype='<u2') for off in (0x2a08,0x2c08,0x2e08,0x3008)])
        require_equal(actual, expected, f'whole channel preparation {first}')
    print('whole channel preparation: all 65,536 inputs passed', flush=True)

    # Original pack helper: all legal Adobe LUT inputs, plus falling/large deltas.
    src, dest_full, dest_diff = e.alloc(512), e.alloc(512), e.alloc(2048)
    pack_cases = 0
    for space in ('srgb', 'adobergb'):
        vectors = [np.minimum(np.arange(first,first+256),16384) for first in range(0,16385,256)]
        vectors += [np.array([0,16384]*128), np.arange(16384,16128,-1)]
        for values in vectors:
            e.u.mem_write(src, values.astype('<u2').tobytes())
            e.w32(emu.STACK - 0x1000, int(space == 'adobergb'))
            e.call(0x53136f4c, gamma, src, dest_full, dest_diff)
            full, diff, _ = _hardware(values[None,:], space)
            require_equal(np.frombuffer(e.read(dest_full,512),dtype='<u2'), full[0], 'packing bases')
            require_equal(np.frombuffer(e.read(dest_diff,2048),dtype='<u8'), diff[0], 'packing deltas')
            pack_cases += 1

    state_checks = []
    values = np.array(engine._regular_curve(0,0,0,0,8192,8192),dtype='<u2')
    e.u.mem_write(gamma, values.tobytes())
    rgb = _interpolate(_tables()[0], values)
    y = (77*rgb[0]+150*rgb[1]+29*rgb[2]) >> 8
    for enabled, copy_y, override in itertools.product((0,1), repeat=3):
        e.w8(0x547bbe44+0x33, enabled)
        e.w8(0x547bbe44+0x39, copy_y)
        e.w8(setting_ptr+0x8d, override)
        e.call(0x531368e0, gamma, setting_ptr)
        actual = np.stack([np.frombuffer(e.read(gamma+off,512),dtype='<u2') for off in (0x2a08,0x2c08,0x2e08,0x3008)])
        expected_rgb = np.full((3,256),4096) if override else np.stack([y]*3) if enabled and copy_y else rgb
        require_equal(actual, np.vstack((expected_rgb,y)), 'state/copy/override branch')
        state_checks.append({'state_0x33':enabled,'state_0x39':copy_y,'setting_0x8d':override,'passed':True})
    e.w8(0x547bbe44+0x33, 0)
    e.w8(0x547bbe44+0x39, 0)
    e.w8(setting_ptr+0x8d, 0)
    # Cross has priority when both mode flags are set; it must not call Gold's getter.
    e.w8(setting_ptr+0x98, 1)
    gold_calls = trace['getter']
    cross_entry = []
    def stop_at_cross(em):
        cross_entry.append(True)
        em.u.reg_write(em._reg.UC_ARM_REG_PC, emu.STOP)
    e.watch[0x53136a64] = stop_at_cross
    e.call(0x531368e0, gamma, setting_ptr)
    assert trace['getter'] == gold_calls and cross_entry == [True]
    state_checks.append({'cross_priority_when_both_flags_set':True, 'stopped_at_cross_entry':'0x53136a64'})
    print('state branches, Cross priority and original packing passed', flush=True)

    return {'passed':True, 'firmware_rtos_sha256':emu.RTOS_SHA256, 'upstream_commit':'aa885bcdaee874d9b9bb18663dd62ed10263eda2',
            'harness_sha256':hashlib.sha256(Path(emu.__file__).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
            'unicorn':unicorn.__version__, 'whole_make_cases':completed, 'whole_make_trace':whole_trace,
            'coverage':'default; each slider -4..4; all 64 six-slider endpoint corners; 40 seeded mixed settings; both color spaces',
            'whole_make_full_diff_sha256':aggregate.hexdigest(), 'channel_preparation_u16_inputs':65536,
            'physical_table_application':{'original_function':'0x532512cc','passed':True,
                                          'full_apertures_rgb_yb':['0xaa00','0xac00','0xae00','0xb000'],
                                          'diff_apertures_rgb_yb':['0x8800','0x9000','0x9800','0xa000']},
            'original_pack_cases':pack_cases, 'adobe_conversion_inputs':16385,'delta_records':241,
            'state_branch_checks':state_checks,'fixtures':fixtures,
            'limits':['Synthetic nominal shooting state, not camera execution or ISP pixel execution.',
                      'The full 9^6 settings Cartesian product is not exhaustively executed.',
                      'Custom-curve state is exercised at channel preparation only; its downstream custom LUT selection is not exposed.',
                      'No photo fitting, rendering quality claim, sharpening, demosaicing, local tone, or noise reduction.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('decoded',type=Path)
    parser.add_argument('--harness',type=Path,default=ROOT / '.research/upstream/tools')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not __debug__:
        parser.error('Run without -O so verification assertions remain active.')
    if not (args.harness / 'k3iii_tuning_emulator.py').is_file():
        parser.error('--harness must contain k3iii_tuning_emulator.py from the documented upstream commit')
    result=verify(args.decoded,args.harness)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:value for key,value in result.items() if key not in ('fixtures','state_branch_checks')}))


if __name__=='__main__':
    main()
