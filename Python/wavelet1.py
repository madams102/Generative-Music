from pylab import *
import pywt
import scipy.io.wavfile as wavfile

# Find the highest power of two less than or equal to the input.
def lepow2(x):
    return 2 ** floor(log2(x))

# Make a scalogram given an MRA tree.
def scalogram(data):
    bottom = 0

    vmin = min(map(lambda x: min(abs(x)), data))
    vmax = max(map(lambda x: max(abs(x)), data))

    gca().set_autoscale_on(False)

    for row in range(0, len(data)):
        scale = 2.0 ** (row - len(data))

        imshow(
            array([abs(data[row])]),
            interpolation = 'nearest',
            vmin = vmin,
            vmax = vmax,
            extent = [0, 1, bottom, bottom + scale])

        bottom += scale

#////////
import pydub 
import numpy as np

def read(f, normalized=False):
    """MP3 to numpy array"""
    a = pydub.AudioSegment.from_mp3(f)
    y = np.array(a.get_array_of_samples())
    if a.channels == 2:
        y = y.reshape((-1, 2))
    if normalized:
        return a.frame_rate, np.float32(y) / 2**15
    else:
        return a.frame_rate, y

def write(f, sr, x, normalized=False):
    """numpy array to MP3"""
    channels = 2 if (x.ndim == 2 and x.shape[1] == 2) else 1
    if normalized:  # normalized array - each item should be a float in [-1, 1)
        y = np.int16(x * 2 ** 15)
    else:
        y = np.int16(x)
    song = pydub.AudioSegment(y.tobytes(), frame_rate=sr, sample_width=2, channels=channels)
    song.export(f, format="mp3", bitrate="320k")

sr, x = read('songtest.mp3')
arr = []
for i in range(0, np.size(x)/2):
    arr.append(x[i])

import pywt
import pywt.data
#import matplotlib.pyplot as plt
cA, cD = pywt.dwt(arr, 'db1')
#///////

# Load the signal, take the first channel, limit length to a power of 2 for simplicity.
rate, signal = wavfile.read('beethoven5th.wav')
#print(int(lepow2(len(signal))))
signal = signal[0:int(lepow2(len(signal))),0]
arr = x[0:int(lepow2(len(x))),0]
tree = pywt.wavedec(signal, 'coif17')

# Plotting.
gray()
scalogram(tree)
show()
