#!/bin/bash

CELL=$1

camonitor USEG:UNDS:${CELL}50:Temp0{1,2,3,4,5,6,7,8} PHAS:UNDS:${CELL}70:Temp0{1,2}
