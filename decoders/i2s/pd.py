##
## This file is part of the libsigrokdecode project.
##
## Copyright (C) 2012 Joel Holdsworth <joel@airwebreathe.org.uk>
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
##

import sigrokdecode as srd

'''
OUTPUT_PYTHON format:

Packet:
[<ptype>, <pdata>]

<ptype>, <pdata>:
 - 'DATA', [<channel>, <value>]

<channel>: 'L' or 'R'
<value>: integer
'''

class Decoder(srd.Decoder):
    api_version = 1
    id = 'i2s'
    name = 'I²S'
    longname = 'Integrated Interchip Sound'
    desc = 'Serial bus for connecting digital audio devices.'
    license = 'gplv2+'
    inputs = ['logic']
    outputs = ['i2s']
    probes = (
        {'id': 'sck', 'name': 'SCK', 'desc': 'Bit clock line'},
        {'id': 'ws', 'name': 'WS', 'desc': 'Word select line'},
        {'id': 'sd', 'name': 'SD', 'desc': 'Serial data line'},
    )
    options = (
	{
         'id' : 'ws_polarity', 'desc' : 'Word Select Polarity', 
	 'default' : 'normal', 'values' : ('normal', 'inverted')
    	},
    )
    annotations = (
        ('left', 'Left channel'),
        ('right', 'Right channel'),
        ('warnings', 'Warnings'),
    )
    binary = (
        ('wav', 'WAV file'),
    )

    def __init__(self, **kwargs):
        self.samplerate = None
        self.oldsck = 1
        self.oldws = 1
        self.bitcount = 0
        self.data = 0
        self.samplesreceived = 0
        self.first_sample = None
        self.start_sample = None
        self.wordlength = -1
        self.wrote_wav_header = False

    def start(self):
        self.out_python = self.register(srd.OUTPUT_PYTHON)
        self.out_bin = self.register(srd.OUTPUT_BINARY)
        self.out_ann = self.register(srd.OUTPUT_ANN)

    def metadata(self, key, value):
        if key == srd.SRD_CONF_SAMPLERATE:
            self.samplerate = value

    def putpb(self, data):
        self.put(self.start_sample, self.samplenum, self.out_python, data)

    def putbin(self, data):
        self.put(self.start_sample, self.samplenum, self.out_bin, data)

    def putb(self, data):
        self.put(self.start_sample, self.samplenum, self.out_ann, data)

    def report(self):

        # Calculate the sample rate.
        samplerate = '?'
        if self.start_sample != None and \
            self.first_sample != None and \
            self.start_sample > self.first_sample:
            samplerate = '%d' % (self.samplesreceived *
                self.samplerate / (self.start_sample -
                self.first_sample))

        return 'I²S: %d %d-bit samples received at %sHz' % \
            (self.samplesreceived, self.wordlength, samplerate)

    def wav_header(self):
        # Chunk descriptor
        h  = b'RIFF'
        h += b'\x24\x80\x00\x00' # Chunk size (2084)
        h += b'WAVE'
        # Fmt subchunk
        h += b'fmt '
        h += b'\x10\x00\x00\x00' # Subchunk size (16 bytes)
        h += b'\x01\x00'         # Audio format (0x0001 == PCM)
        h += b'\x02\x00'         # Number of channels (2)
        h += b'\x80\x3e\x00\x00' # Samplerate (16000)
        h += b'\x00\x7d\x00\x00' # Byterate (32000)
        h += b'\x04\x00'         # Blockalign (4)
        h += b'\x10\x00'         # Bits per sample (16)
        # Data subchunk
        h += b'data'
        h += b'\xff\xff\x00\x00' # Subchunk size (65535 bytes) TODO
        return h

    def wav_sample(self, sample):
        # TODO: This currently assumes U32 samples, and converts to S16.
        s = sample >> 16
        if s >= 0x8000:
            s -= 0x10000
        lo, hi = s & 0xff, (s >> 8) & 0xff
        return bytes([lo, hi])

    def decode(self, ss, es, data):
        if self.samplerate is None:
            raise Exception("Cannot decode without samplerate.")
        for self.samplenum, (sck, ws, sd) in data:

            # Ignore sample if the bit clock hasn't changed.
            if sck == self.oldsck:
                continue

            self.oldsck = sck
            if sck == 0:   # Ignore the falling clock edge.
                continue

            self.data = (self.data << 1) | sd
            self.bitcount += 1

            # This was not the LSB unless WS has flipped.
            if ws == self.oldws:
                continue

            # Only submit the sample, if we received the beginning of it.
            if self.start_sample != None:

                if not self.wrote_wav_header:
                    self.put(0, 0, self.out_bin, (0, self.wav_header()))
                    self.wrote_wav_header = True

                self.samplesreceived += 1

                idx = 0 if self.oldws else 1
                if self.options['ws_polarity'] == 'normal':
                    c1 = 'Right channel' if self.oldws else 'Left channel'
                    c2 = 'Right' if self.oldws else 'Left'
                    c3 = 'R' if self.oldws else 'L'
                else:
                    c1 = 'Left channel' if self.oldws else 'Right channel'
                    c2 = 'Left' if self.oldws else 'Right'
                    c3 = 'L' if self.oldws else 'R'
                
                v = '%08x' % self.data
                self.putpb(['DATA', [c3, self.data]])
                self.putb([idx, ['%s: %s' % (c1, v), '%s: %s' % (c2, v),
                                 '%s: %s' % (c3, v), c3]])
                self.putbin((0, self.wav_sample(self.data)))

                # Check that the data word was the correct length.
                if self.wordlength != -1 and self.wordlength != self.bitcount:
                    self.putb([2, ['Received %d-bit word, expected %d-bit '
                                   'word' % (self.bitcount, self.wordlength)]])

                self.wordlength = self.bitcount

            # Reset decoder state.
            self.data = 0
            self.bitcount = 0
            self.start_sample = self.samplenum

            # Save the first sample position.
            if self.first_sample == None:
                self.first_sample = self.samplenum

            self.oldws = ws

