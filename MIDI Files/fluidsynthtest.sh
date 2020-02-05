#!/bin/bash
echo MIDI File Directory:

read dir

sudo fluidsynth -a alsa -r 2048 ~/Documents/Song\ Generator/GeneralUser\ GS\ 1.471/GeneralUser\ GS\ v1.471.sf2 $dir

