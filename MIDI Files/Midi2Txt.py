#!/usr/bin/python

import sys, getopt
from mido import MidiFile

f = raw_input("Enter a file (relative to this file's directory):")

mid = MidiFile(f)

for i, track in enumerate(mid.tracks):
	#track is <meta message s
	for msg in track:
		#msg is the message in form "note_on/off channel=0 note=# velocity=# time=#
		pass
