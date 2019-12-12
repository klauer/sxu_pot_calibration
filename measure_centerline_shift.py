#!/usr/bin/env python3
# LCLS-2 SXU undulator centerline shift measurement

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


def print(*args, **kwargs):
    file = kwargs.pop('file', sys.stdout)
    _print(*args, file=file, **kwargs)
    file.flush()


class TimeoutError(Exception):
    pass


PHYSICS_DATA = os.environ.get('PHYSICS_DATA')
GAP = 40

MAX_Y = object()
NEG_MAX_Y = object()

MOVES = [
    (0.25, 0.00),
    (0.50, 0.00),
    (0.75, 0.00),
    (MAX_Y, 0.00),
    (-0.25, 0.00),
    (-0.50, 0.00),
    (-0.75, 0.00),
    (NEG_MAX_Y, 0.00),
    (0.00, 0.00),

    (0.00, 0.25),
    (0.00, 0.50),
    (0.00, 0.75),
    (0.00, MAX_Y),
    (0.00, -0.25),
    (0.00, -0.50),
    (0.00, -0.75),
    (0.00, NEG_MAX_Y),
    (0.00, 0.00),

    (0.50, 0.50),
    (MAX_Y, MAX_Y),
    (0.00, 0.00),
    (-0.50, -0.50),

    (NEG_MAX_Y, NEG_MAX_Y),
    (0.00, 0.00),
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
            time.sleep(delay)

        return readings, np.average(readings)


epics.pv.PV = PV


class Interspace(object):
    def __init__(self, cell):
        self.cell = cell
        self.prefix = 'MOVR:UNDS:{}80:'.format(cell)

        self.x_desired_pv = PV(self.prefix + 'QXDES')
        self.y_desired_pv = PV(self.prefix + 'QYDES')
        self.y_readback_pv = PV(self.prefix + 'YRDBCKCALC')
        self.roll_desired_pv = PV(self.prefix + 'QROLLDES')
        self.pitch_desired_pv = PV(self.prefix + 'QPITCHDES')
        self.yaw_desired_pv = PV(self.prefix + 'QYAWDES')

        self.go_pv = PV(self.prefix + 'TRIGGERCAL.PROC')
        self.moving_pv = PV(self.prefix + 'CAMSMOVING')

        self.all_pvs = [
            self.x_desired_pv, self.y_desired_pv, self.y_readback_pv,
            self.roll_desired_pv, self.pitch_desired_pv, self.yaw_desired_pv,
            self.go_pv, self.moving_pv,
        ]

        for pv in self.all_pvs:
            pv.wait_for_connection()

    @property
    def short_name(self):
        return 'Interspace {}'.format(self.cell)

    @property
    def connected(self):
        return all(pv.connected for pv in self.all_pvs)

    def __repr__(self):
        return ('<{class_name} prefix={prefix!r} connected={connected}>'
                ''.format(class_name=type(self).__name__,
                          prefix=self.prefix,
                          connected=self.connected)
                )

    def wait_move(self):
        delta = 1.0
        while abs(delta) > 0.005:
            y_rdbk = self.y_readback_pv.get()
            y_des = self.y_desired_pv.get()
            delta = y_des - y_rdbk

        while int(self.moving_pv.get()) != 1:
            time.sleep(0.5)


class Undulator(object):
    def __init__(self, cell):
        self.cell = cell
        self.prefix = 'USEG:UNDS:{}50:'.format(cell)

        self.us_shift_pv = PV(self.prefix + 'US:CtrLnShift')
        self.ds_shift_pv = PV(self.prefix + 'DS:CtrLnShift')

        self.all_pvs = [
            self.us_shift_pv,
            self.ds_shift_pv,
        ]

        for pv in self.all_pvs:
            pv.wait_for_connection()

    @property
    def short_name(self):
        return 'SXU{}'.format(self.cell)

    @property
    def connected(self):
        return all(pv.connected for pv in self.all_pvs)

    def get_filename(self, extension):
        fn = get_filename(self.cell, extension=extension)
        print('Writing to {}'.format(fn))
        return fn

    def __repr__(self):
        return ('<{class_name} prefix={prefix!r} connected={connected}>'
                ''.format(class_name=type(self).__name__,
                          prefix=self.prefix,
                          connected=self.connected)
                )


def query(message, allow_no=False):
    while True:
        print('{} [yn]'.format(message))
        try:
            res = raw_input()
        except KeyboardInterrupt:
            continue

        res = res.strip()
        if res in ('yes', 'y'):
            return True
        elif res in ('no', 'n') and allow_no:
            return False

        if res in ('q', 'quit'):
            sys.exit(1)

        print('y, n, or q to quit')


def read_potentiometer(pots, count=10, delay=0.2, max_fluctuation=0.007):
    while True:
        data, avg = pots.voltage_pv.get_averaged(count=count, delay=delay)
        min_max = np.max(data) - np.min(data)
        if min_max <= max_fluctuation:
            return avg
        query('Potentiometer exceeded maximum voltage fluctuation of {}. '
              'Retry?'.format(max_fluctuation))


def get_filename(cell, suffix='', extension='txt'):
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    return os.path.join(
        PHYSICS_DATA, 'undMotion', 'sxu_centerline',
        'cell_{}_{}{}.{}'.format(
            cell,
            suffix + '_' if suffix else '',
            timestamp,
            extension)
    )


def calibrate(cell, us_offset, ds_offset, max_us_y, max_ds_y):
    undulator = Undulator(cell)
    us_interspace = Interspace(cell - 1)
    ds_interspace = Interspace(cell)

    def print_connected(pv):
        print('{}\t{}' ''.format(pv.pvname, 'connected'
                                 if pv.connected
                                 else 'disconnected'),
              file=sys.stderr)

    data = {}

    all_components = [undulator, us_interspace, ds_interspace]

    def get_value(value, maximum, offset):
        if value is MAX_Y:
            value = maximum
        elif value is NEG_MAX_Y:
            value = -maximum

        value += offset
        if value > maximum:
            return maximum
        elif value < -maximum:
            return -maximum
        return value

    positions = [(get_value(us, max_us_y, us_offset),
                  get_value(ds, max_ds_y, ds_offset))
                 for us, ds in MOVES]

    if not query('Ready to move {}?'.format(undulator.short_name), allow_no=True):
        sys.exit(1)

    data = ['\t'.join(('Cell', 'US Y', 'DS Y', 'US Shift', 'DS Shift'))]
    print(data[-1], file=sys.stderr)
    for us_pos, ds_pos in positions:
        line = '{}\t{}\t{}\t'.format(undulator.short_name, us_pos, ds_pos)
        print(line, end='', file=sys.stderr)
        for interspace, pos in [(us_interspace, us_pos), (ds_interspace, ds_pos)]:
            interspace.x_desired_pv.put(0.0)
            time.sleep(0.1)
            interspace.y_desired_pv.put(pos)
            time.sleep(0.1)
            interspace.roll_desired_pv.put(0.0)
            time.sleep(0.1)
            interspace.pitch_desired_pv.put(0.0)
            time.sleep(0.1)
            interspace.yaw_desired_pv.put(0.0)
            time.sleep(0.1)
            us_interspace.go_pv.put(1)
            time.sleep(0.1)
            us_interspace.wait_move()

        _, us_shift = undulator.us_shift_pv.get_averaged()
        _, ds_shift = undulator.ds_shift_pv.get_averaged()

        shifts = '{:.4f}\t{:.4f}'.format(us_shift, ds_shift)
        print(shifts, file=sys.stderr)
        data.append(line + shifts)

    with open(undulator.get_filename('txt'), 'wt') as f:
        print('\n'.join(data), file=f)

    return data


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('cell', type=int,
                        help='SXU undulator cell')
    parser.add_argument('us_offset', type=float,
                        help='Upstream Y offset value', default=0.0)
    parser.add_argument('ds_offset', type=float,
                        help='Downstream Y offset value', default=0.0)
    parser.add_argument('max_us_y', type=float,
                        help='Maximum upstream Y value', default=1.0)
    parser.add_argument('max_ds_y', type=float,
                        help='Maximum downstream Y value', default=1.0)
    args = parser.parse_args()
    calibrate(**dict(args._get_kwargs()))
