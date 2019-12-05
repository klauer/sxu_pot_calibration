#!/usr/bin/env python3
from caproto.server import pvproperty, PVGroup, ioc_arg_parser, run
from textwrap import dedent


class SimpleIOC(PVGroup):
    '''
    '''
    gap_des       = pvproperty(value=0.1, name='GapDes')
    gap_act       = pvproperty(value=0.1, name='GapAct')
    gap_go       = pvproperty(value=0.1, name='Go')
    ds_vact       = pvproperty(value=0.1, name='DS:VAct')
    ds_potvref    = pvproperty(value=0.1, name='DS:PotVref')
    ds_gapref     = pvproperty(value=0.1, name='DS:GapRef')
    ds_potslope   = pvproperty(value=0.1, name='DS:PotSlope')
    ds_potoffset  = pvproperty(value=0.1, name='DS:PotOffset')
    ds_ctrlnshift = pvproperty(value=0.1, name='DS:CtrLnShift')
    us_vact       = pvproperty(value=0.1, name='US:VAct')
    us_potvref    = pvproperty(value=0.1, name='US:PotVref')
    us_gapref     = pvproperty(value=0.1, name='US:GapRef')
    us_potslope   = pvproperty(value=0.1, name='US:PotSlope')
    us_potoffset  = pvproperty(value=0.1, name='US:PotOffset')
    us_ctrlnshift = pvproperty(value=0.1, name='US:CtrLnShift')

    @gap_go.putter
    async def gap_go(self, instance, value):
        await self.gap_act.write(self.gap_des.value)


if __name__ == '__main__':
    ioc_options, run_options = ioc_arg_parser(
        default_prefix='USEG:UNDS:4450:',
        desc=dedent(SimpleIOC.__doc__))
    ioc = SimpleIOC(**ioc_options)
    run(ioc.pvdb, **run_options)
