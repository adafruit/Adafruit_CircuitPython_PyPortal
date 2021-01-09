# SPDX-FileCopyrightText: 2017 Scott Shawcroft, written for Adafruit Industries
# SPDX-FileCopyrightText: Copyright (c) 2020 Melissa LeBlanc-Williams for Adafruit Industries
#
# SPDX-License-Identifier: MIT
"""
`adafruit_pyportal.peripherals`
================================================================================

CircuitPython driver for Adafruit PyPortal.

* Author(s): Limor Fried, Kevin J. Walters, Melissa LeBlanc-Williams

Implementation Notes
--------------------

**Hardware:**

* `Adafruit PyPortal <https://www.adafruit.com/product/4116>`_

**Software and Dependencies:**

* Adafruit CircuitPython firmware for the supported boards:
  https://github.com/adafruit/circuitpython/releases

"""

import board
from digitalio import DigitalInOut
import audioio
import audiocore
import storage

try:
    import sdcardio

    NATIVE_SD = True
except ImportError:
    import adafruit_sdcard as sdcardio

    NATIVE_SD = False

__version__ = "0.0.0-auto.0"
__repo__ = "https://github.com/adafruit/Adafruit_CircuitPython_PyPortal.git"


class Peripherals:
    """Peripherals Helper Class for the PyPortal Library"""

    # pylint: disable=too-many-instance-attributes, too-many-locals, too-many-branches, too-many-statements
    def __init__(self, spi, debug=False):
        # Speaker Enable
        self._speaker_enable = DigitalInOut(board.SPEAKER_ENABLE)
        self._speaker_enable.switch_to_output(False)

        if hasattr(board, "AUDIO_OUT"):
            self.audio = audioio.AudioOut(board.AUDIO_OUT)
        elif hasattr(board, "SPEAKER"):
            self.audio = audioio.AudioOut(board.SPEAKER)
        else:
            raise AttributeError("Board does not have a builtin speaker!")

        if debug:
            print("Init SD Card")
        sd_cs = board.SD_CS
        if not NATIVE_SD:
            sd_cs = DigitalInOut(sd_cs)
        self._sdcard = None

        try:
            self._sdcard = sdcardio.SDCard(spi, sd_cs)
            vfs = storage.VfsFat(self._sdcard)
            storage.mount(vfs, "/sd")
        except OSError as error:
            print("No SD card found:", error)

    def play_file(self, file_name, wait_to_finish=True):
        """Play a wav file.

        :param str file_name: The name of the wav file to play on the speaker.

        """
        wavfile = open(file_name, "rb")
        wavedata = audiocore.WaveFile(wavfile)
        self._speaker_enable.value = True
        self.audio.play(wavedata)
        if not wait_to_finish:
            return
        while self.audio.playing:
            pass
        wavfile.close()
        self._speaker_enable.value = False

    def sd_check(self):
        """Returns True if there is an SD card preset and False
        if there is no SD card. The _sdcard value is set in _init
        """
        if self._sdcard:
            return True
        return False

    @property
    def speaker_disable(self):
        """
        Enable or disable the speaker for power savings
        """
        return not self._speaker_enable.value

    @speaker_disable.setter
    def speaker_disable(self, value):
        self._speaker_enable.value = not value
