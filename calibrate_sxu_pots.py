#!/usr/bin/env python3
# LCLS-2 SXU undulator potentiometer interactive calibration

# NOTE: Calibration data is saved in $PHYSICS_DATA/undMotion/

from __future__ import print_function

import datetime
import json
import os
import sys
import time

import epics
import matplotlib
import matplotlib.pyplot as plt
import numpy as np

try:
    matplotlib.use('Agg')
except Exception:
    pass


_print = print


def print(*args, file=sys.stdout, **kwargs):
    _print(*args, **kwargs)
    file.flush()


PHYSICS_DATA = os.environ.get('PHYSICS_DATA')
GAP0 = 10
GAP1 = 22
BLOCK_THICKNESSES = [
    7.4, 7,
    6.5, 6,
    5.5, 5,
    4.5, 4,
    3.5, 3,
    2.5, 2,
    1.5, 1,
    0.0,
    ]


class PV(epics.PV):
    def __init__(self, pvname, auto_monitor=None, **kw):
        super(PV, self).__init__(pvname, auto_monitor=False, **kw)

    def get(self, use_monitor=False, **kw):
        value = super(PV, self).get(use_monitor=use_monitor, **kw)
        # Key difference to pyepics: raise when a timeout occurs
        if value is None:
            raise TimeoutError('Timed out while reading value')
        return value

    def get_averaged(self, count=10, delay=0.2, verbose=True, **kw):
        readings = []
        for i in range(count):
            readings.append(self.get())
            print('.', end='')
            time.sleep(delay)

        average = np.average(readings)
        print('average {:.4f} {}'.format(average, self.units or ''))

        return readings, average


epics.pv.PV = PV


class PotBase(object):
    # Awful OO for my convenience

    def __init__(self, cell, suffix):
        self.cell = cell
        self.gap_prefix = 'USEG:UNDS:{}50:'.format(cell)
        self.prefix = self.gap_prefix + suffix
        self.suffix = suffix

        self.gap_des_pv = PV(self.gap_prefix + 'GapDes')
        self.gap_act_pv = PV(self.gap_prefix + 'GapAct')
        self.gap_go_pv = PV(self.gap_prefix + 'Go')

        self.voltage_pv = PV(self.prefix + 'VAct')
        self.voltage_ref_pv = PV(self.prefix + 'PotVref')
        self.gap_ref_pv = PV(self.prefix + 'GapRef')
        self.slope_pv = PV(self.prefix + 'PotSlope')
        self.offset_pv = PV(self.prefix + 'PotOffset')
        self.center_line_shift_pv = PV(self.prefix + 'CtrLnShift')

        self.all_pvs = [
            self.gap_des_pv, self.gap_act_pv, self.gap_go_pv,
            self.voltage_pv, self.voltage_ref_pv, self.gap_ref_pv,
            self.slope_pv, self.offset_pv, self.center_line_shift_pv
        ]

        for pv in self.all_pvs:
            pv.wait_for_connection()

    @property
    def short_name(self):
        return 'Cell {} {}'.format(self.cell, self.suffix.strip(':'))

    @property
    def connected(self):
        return all(pv.connected for pv in self.all_pvs)

    def get_filename(self, extension):
        fn = get_filename(self.cell, suffix=self.suffix.strip(':'),
                          extension=extension)
        print('Writing to {}'.format(fn))
        return fn

    def __repr__(self):
        return ('<{class_name} prefix={prefix!r} connected={connected}>'
                ''.format(class_name=type(self).__name__,
                          prefix=self.prefix,
                          connected=self.connected)
                )


class DownstreamPot(PotBase):
    def __init__(self, cell):
        super(DownstreamPot, self).__init__(cell, suffix='DS:')


class UpstreamPot(PotBase):
    def __init__(self, cell):
        super(UpstreamPot, self).__init__(cell, suffix='US:')


def query(message, allow_no=False):
    while True:
        print('{} [yn]'.format(message))
        res = input()
        if res in ('yes', 'y'):
            return True
        elif res in ('no', 'n') and allow_no:
            return False

        if res in ('q', 'quit'):
            sys.exit(1)

        print('y, n, or q to quit')


def move_gap(pots, gap, tolerance=0.001):
    query('OK to move the gap to {}?'.format(gap))
    print('Moving to {}...'.format(gap))
    pots.gap_des_pv.put(gap)
    time.sleep(0.1)
    pots.gap_go_pv.put(1)
    time.sleep(0.1)

    def print_gap(msg='Gap at'):
        print('{} {} (err={})'.format(msg,
                                      pots.gap_act_pv.get(),
                                      pots.gap_act_pv.get() - gap))

    while abs(pots.gap_act_pv.get() - gap) > tolerance:
        time.sleep(0.5)
        print_gap()

    print_gap('Gap at target')
    print()


def read_potentiometer(pots, count=10, delay=0.2, max_fluctuation=0.007):
    while True:
        data, avg = pots.voltage_pv.get_averaged(count=count, delay=delay)
        min_max = np.max(data) - np.min(data)
        if min_max <= max_fluctuation:
            return avg
        query('Potentiometer exceeded maximum voltage fluctuation of {}. '
              'Retry?'.format(max_fluctuation))


def get_calibration_data(pots):
    ''
    if not pots.connected:
        raise TimeoutError('Not all PVs connected')

    data = {'blocks': {},
            'gaps': {},
            }

    for gap in (GAP0, GAP1):
        move_gap(pots, gap)
        time.sleep(0.5)
        data['gaps'][gap] = read_potentiometer(pots)

    for block in BLOCK_THICKNESSES:
        query('\n{}: insert the ceramic block of thickness: {:.1f} mm'
              ''.format(pots.short_name, block))
        data['blocks'][block] = read_potentiometer(pots)

    move_gap(pots, 10)

    _, data['center_line_shift'] = pots.center_line_shift_pv.get_averaged()

    slope, _ = calculate_slope_offset(data)
    data['slope'] = slope
    data['offset'] = data['center_line_shift']

    plot(pots, data)
    return data


def calculate_slope_offset(data, gap0=GAP0, gap1=GAP1):
    equiv_block = abs(gap1 - gap0) / 2
    equiv_voltage = data['blocks'][equiv_block]
    blocks = list(sorted(data['blocks']))
    voltages = [data['blocks'][block]
                for block in blocks]
    delta_extension = [equiv_block - block
                       for block in blocks]
    delta_voltage = [equiv_voltage - voltage
                     for voltage in voltages]

    slope, _ = np.polyfit(voltages, delta_extension, 1)
    _, offset = np.polyfit(delta_voltage, delta_extension, 1)
    return slope, offset


def plot(pots, data):
    '''According to appropriate linear potentiometer, fit cam rotary pot'''
    fig, ax = plt.subplots(1, 1, figsize=(9, 6))
    plt.title('SXU {} Potentiometer Calibration'.format(pots.short_name))
    plt.xlabel('Block [mm]')
    plt.ylabel('Linear potentiometer [V]')

    blocks = list(sorted(data['blocks']))
    voltages = [data['blocks'][block]
                for block in blocks]

    ax.plot(blocks, voltages, 'o-')

    text_info = '''
Slope     : {:.4f}
Offset    : {:.4f}
{}mm ref  : {:.4f}
{}mm ref  : {:.4f}
'''.format(data['slope'],
           data['offset'],
           GAP0, data['gaps'][GAP0],
           GAP1, data['gaps'][GAP1],
           )

    plt.annotate(text_info, xy=(0.01, 0.015),
                 xycoords='axes fraction',
                 family='monospace',
                 va="bottom",
                 fontsize=12,
                 )

    plt.savefig(pots.get_filename('png'))
    return fig, ax


def get_filename(cell, suffix='', extension='txt'):
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    return os.path.join(
        PHYSICS_DATA, 'undMotion', 'sxu_pots',
        'cell_{}_{}{}.{}'.format(
            cell,
            suffix + '_' if suffix else '',
            timestamp,
            extension)
    )


def calibrate(cell):
    ds = DownstreamPot(cell)
    us = UpstreamPot(cell)

    def print_connected(pv):
        print('{}\t{}' ''.format(pv.pvname, 'connected'
                                 if pv.connected
                                 else 'disconnected'),
              file=sys.stderr)

    data = {}

    for part in [ds, us]:
        print('-- {} --'.format(part.short_name), file=sys.stderr)
        for pv in part.all_pvs:
            print_connected(pv)
        print(file=sys.stderr)
        print(file=sys.stderr)

        print('Running calibration on {}...'.format(part.short_name))
        data[part] = get_calibration_data(part)

        to_write = [
            (part.voltage_ref_pv, data[part]['gaps'][GAP0]),
            (part.gap_ref_pv, GAP0),
            (part.slope_pv, data[part]['slope']),
            (part.offset_pv, data[part]['offset']),
        ]

        caputs = ['caput {} {}'.format(pv.pvname, value)
                  for pv, value in to_write
                  ]

        print('To write:')
        print('\t' + '\n\t'.join(caputs))

        if query('Write to PVs?', allow_no=True):
            for pv, value in to_write:
                pv.put(value)

        with open(part.get_filename('json'), 'wt') as f:
            json.dump(data[part], f)

    return data


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('cell', type=int,
                        help='SXU undulator cell')
    args = parser.parse_args()
    calibrate(**dict(args._get_kwargs()))
