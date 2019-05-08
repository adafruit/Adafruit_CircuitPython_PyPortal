# The MIT License (MIT)
#
# Copyright (c) 2019 Limor Fried for Adafruit Industries
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
"""
`adafruit_pyportal`
================================================================================

CircuitPython driver for Adafruit PyPortal.


* Author(s): Limor Fried

Implementation Notes
--------------------

**Hardware:**

* `Adafruit PyPortal <https://www.adafruit.com/product/4116>`_

**Software and Dependencies:**

* Adafruit CircuitPython firmware for the supported boards:
  https://github.com/adafruit/circuitpython/releases

* Adafruit's Bus Device library: https://github.com/adafruit/Adafruit_CircuitPython_BusDevice
"""

import os
import time
import gc
import board
import busio
from digitalio import DigitalInOut
import pulseio
import adafruit_touchscreen
import neopixel

from adafruit_esp32spi import adafruit_esp32spi
import adafruit_esp32spi.adafruit_esp32spi_requests as requests
try:
    from adafruit_display_text.text_area import TextArea  # pylint: disable=unused-import
    print("*** WARNING ***\nPlease update your library bundle to the latest 'adafruit_display_text' version as we've deprecated 'text_area' in favor of 'label'")  # pylint: disable=line-too-long
except ImportError:
    from adafruit_display_text.Label import Label
from adafruit_bitmap_font import bitmap_font

import storage
import adafruit_sdcard
import displayio
import audioio
import rtc
import supervisor

try:
    from secrets import secrets
except ImportError:
    print("""WiFi settings are kept in secrets.py, please add them there!
the secrets dictionary must contain 'ssid' and 'password' at a minimum""")
    raise

__version__ = "3.0.0"
__repo__ = "https://github.com/adafruit/Adafruit_CircuitPython_PyPortal.git"

# pylint: disable=line-too-long
# you'll need to pass in an io username, width, height, format (bit depth), io key, and then url!
IMAGE_CONVERTER_SERVICE = "https://io.adafruit.com/api/v2/%s/integrations/image-formatter?x-aio-key=%s&width=%d&height=%d&output=BMP%d&url=%s"
# you'll need to pass in an io username and key
TIME_SERVICE = "https://io.adafruit.com/api/v2/%s/integrations/time/strftime?x-aio-key=%s"
# our strftime is %Y-%m-%d %H:%M:%S.%L %j %u %z %Z see http://strftime.net/ for decoding details
# See https://apidock.com/ruby/DateTime/strftime for full options
TIME_SERVICE_STRFTIME = '&fmt=%25Y-%25m-%25d+%25H%3A%25M%3A%25S.%25L+%25j+%25u+%25z+%25Z'
LOCALFILE = "local.txt"
# pylint: enable=line-too-long


class Fake_Requests:
    """For faking 'requests' using a local file instead of the network."""
    def __init__(self, filename):
        self._filename = filename
        with open(filename, "r") as file:
            self.text = file.read()

    def json(self):
        """json parsed version for local requests."""
        import json
        return json.loads(self.text)


class PyPortal:
    """Class representing the Adafruit PyPortal.

    :param url: The URL of your data source. Defaults to ``None``.
    :param headers: The headers for authentication, typically used by Azure API's.
    :param json_path: The list of json traversal to get data out of. Can be list of lists for
                      multiple data points. Defaults to ``None`` to not use json.
    :param regexp_path: The list of regexp strings to get data out (use a single regexp group). Can
                        be list of regexps for multiple data points. Defaults to ``None`` to not
                        use regexp.
    :param default_bg: The path to your default background image file or a hex color.
                       Defaults to 0x000000.
    :param status_neopixel: The pin for the status NeoPixel. Use ``board.NEOPIXEL`` for the on-board
                            NeoPixel. Defaults to ``None``, no status LED
    :param str text_font: The path to your font file for your data text display.
    :param text_position: The position of your extracted text on the display in an (x, y) tuple.
                          Can be a list of tuples for when there's a list of json_paths, for example
    :param text_color: The color of the text, in 0xRRGGBB format. Can be a list of colors for when
                       there's multiple texts. Defaults to ``None``.
    :param text_wrap: Whether or not to wrap text (for long text data chunks). Defaults to
                      ``False``, no wrapping.
    :param text_maxlen: The max length of the text for text wrapping. Defaults to 0.
    :param text_transform: A function that will be called on the text before display
    :param image_json_path: The JSON traversal path for a background image to display. Defaults to
                            ``None``.
    :param image_resize: What size to resize the image we got from the json_path, make this a tuple
                         of the width and height you want. Defaults to ``None``.
    :param image_position: The position of the image on the display as an (x, y) tuple. Defaults to
                           ``None``.
    :param success_callback: A function we'll call if you like, when we fetch data successfully.
                             Defaults to ``None``.
    :param str caption_text: The text of your caption, a fixed text not changed by the data we get.
                             Defaults to ``None``.
    :param str caption_font: The path to the font file for your caption. Defaults to ``None``.
    :param caption_position: The position of your caption on the display as an (x, y) tuple.
                             Defaults to ``None``.
    :param caption_color: The color of your caption. Must be a hex value, e.g. ``0x808000``.
    :param image_url_path: The HTTP traversal path for a background image to display.
                             Defaults to ``None``.
    :param debug: Turn on debug print outs. Defaults to False.

    """
    # pylint: disable=too-many-instance-attributes, too-many-locals, too-many-branches, too-many-statements
    def __init__(self, *, url=None, headers=None, json_path=None, regexp_path=None,
                 default_bg=0x000000, status_neopixel=None,
                 text_font=None, text_position=None, text_color=0x808080,
                 text_wrap=False, text_maxlen=0, text_transform=None,
                 image_json_path=None, image_resize=None, image_position=None,
                 caption_text=None, caption_font=None, caption_position=None,
                 caption_color=0x808080, image_url_path=None,
                 success_callback=None,  esp=None, passed_spi=None, debug=False ):

        self._debug = debug

        try:
            self._backlight = pulseio.PWMOut(board.TFT_BACKLIGHT)  # pylint: disable=no-member
        except ValueError:
            self._backlight = None
        self.set_backlight(1.0)  # turn on backlight

        self._url = url
        self._headers = headers
        if json_path:
            if isinstance(json_path[0], (list, tuple)):
                self._json_path = json_path
            else:
                self._json_path = (json_path,)
        else:
            self._json_path = None

        self._regexp_path = regexp_path
        self._success_callback = success_callback

        if status_neopixel:
            self.neopix = neopixel.NeoPixel(status_neopixel, 1, brightness=0.2)
        else:
            self.neopix = None
        self.neo_status(0)

        try:
            os.stat(LOCALFILE)
            self._uselocal = True
        except OSError:
            self._uselocal = False

        if self._debug:
            print("Init display")
        self.splash = displayio.Group(max_size=15)

        if self._debug:
            print("Init background")
        self._bg_group = displayio.Group(max_size=1)
        self._bg_file = None
        self._default_bg = default_bg
        self.splash.append(self._bg_group)

        # show thank you and bootup file if available
        for bootscreen in ("/thankyou.bmp", "/pyportal_startup.bmp"):
            try:
                os.stat(bootscreen)
                board.DISPLAY.show(self.splash)
                for i in range(100, -1, -1):  # dim down
                    self.set_backlight(i/100)
                    time.sleep(0.005)
                self.set_background(bootscreen)
                board.DISPLAY.wait_for_frame()
                for i in range(100):  # dim up
                    self.set_backlight(i/100)
                    time.sleep(0.005)
                time.sleep(2)
            except OSError:
                pass # they removed it, skip!

        self._speaker_enable = DigitalInOut(board.SPEAKER_ENABLE)
        self._speaker_enable.switch_to_output(False)
        self.audio = audioio.AudioOut(board.AUDIO_OUT)
        try:
            self.play_file("pyportal_startup.wav")
        except OSError:
            pass # they deleted the file, no biggie!

        # If there was a passed ESP Object
        if esp:
            if self._debug:
                print("ESP32 Passed to PyPortal")
            self._esp = esp
            if passed_spi: #If SPI Object Passed
                spi = passed_spi
            else:
                spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
        # Else: Make ESP32 connection
        else:
            if self._debug:
                print("Init ESP32")
            esp32_ready = DigitalInOut(board.ESP_BUSY)
            esp32_gpio0 = DigitalInOut(board.ESP_GPIO0)
            esp32_reset = DigitalInOut(board.ESP_RESET)
            esp32_cs = DigitalInOut(board.ESP_CS)
            spi = busio.SPI(board.SCK, board.MOSI, board.MISO)

            self._esp = adafruit_esp32spi.ESP_SPIcontrol(spi, esp32_cs, esp32_ready,
                                                     esp32_reset, esp32_gpio0)
        #self._esp._debug = 1
        for _ in range(3): # retries
            try:
                print("ESP firmware:", self._esp.firmware_version)
                break
            except RuntimeError:
                print("Retrying ESP32 connection")
                time.sleep(1)
                self._esp.reset()
        else:
            raise RuntimeError("Was not able to find ESP32")
        requests.set_interface(self._esp)

        if url and not self._uselocal:
            self._connect_esp()

        # set the default background
        self.set_background(self._default_bg)
        board.DISPLAY.show(self.splash)

        if self._debug:
            print("Init SD Card")
        sd_cs = DigitalInOut(board.SD_CS)
        self._sdcard = None
        try:
            self._sdcard = adafruit_sdcard.SDCard(spi, sd_cs)
            vfs = storage.VfsFat(self._sdcard)
            storage.mount(vfs, "/sd")
        except OSError as error:
            print("No SD card found:", error)

        self._qr_group = None

        if self._debug:
            print("Init caption")
        self._caption = None
        if caption_font:
            self._caption_font = bitmap_font.load_font(caption_font)
        self.set_caption(caption_text, caption_position, caption_color)

        if text_font:
            if isinstance(text_position[0], (list, tuple)):
                num = len(text_position)
                if not text_wrap:
                    text_wrap = [0] * num
                if not text_maxlen:
                    text_maxlen = [0] * num
                if not text_transform:
                    text_transform = [None] * num
            else:
                num = 1
                text_position = (text_position,)
                text_color = (text_color,)
                text_wrap = (text_wrap,)
                text_maxlen = (text_maxlen,)
                text_transform = (text_transform,)
            self._text = [None] * num
            self._text_color = [None] * num
            self._text_position = [None] * num
            self._text_wrap = [None] * num
            self._text_maxlen = [None] * num
            self._text_transform = [None] * num
            self._text_font = bitmap_font.load_font(text_font)
            if self._debug:
                print("Loading font glyphs")
            # self._text_font.load_glyphs(b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
            #                             b'0123456789:/-_,. ')
            gc.collect()

            for i in range(num):
                if self._debug:
                    print("Init text area", i)
                self._text[i] = None
                self._text_color[i] = text_color[i]
                self._text_position[i] = text_position[i]
                self._text_wrap[i] = text_wrap[i]
                self._text_maxlen[i] = text_maxlen[i]
                self._text_transform[i] = text_transform[i]
        else:
            self._text_font = None
            self._text = None

        self._image_json_path = image_json_path
        self._image_url_path = image_url_path
        self._image_resize = image_resize
        self._image_position = image_position
        if image_json_path or image_url_path:
            if self._debug:
                print("Init image path")
            if not self._image_position:
                self._image_position = (0, 0)  # default to top corner
            if not self._image_resize:
                self._image_resize = (320, 240)  # default to full screen

        if self._debug:
            print("Init touchscreen")
        # pylint: disable=no-member
        self.touchscreen = adafruit_touchscreen.Touchscreen(board.TOUCH_XL, board.TOUCH_XR,
                                                            board.TOUCH_YD, board.TOUCH_YU,
                                                            calibration=((5200, 59000),
                                                                         (5800, 57000)),
                                                            size=(320, 240))
        # pylint: enable=no-member

        self.set_backlight(1.0)  # turn on backlight

        gc.collect()

    def set_background(self, file_or_color, position=None):
        """The background image to a bitmap file.

        :param file_or_color: The filename of the chosen background image, or a hex color.

        """
        print("Set background to ", file_or_color)
        while self._bg_group:
            self._bg_group.pop()

        if not position:
            position = (0, 0)  # default in top corner

        if not file_or_color:
            return  # we're done, no background desired
        if self._bg_file:
            self._bg_file.close()
        if isinstance(file_or_color, str): # its a filenme:
            self._bg_file = open(file_or_color, "rb")
            background = displayio.OnDiskBitmap(self._bg_file)
            try:
                self._bg_sprite = displayio.TileGrid(background,
                                                     pixel_shader=displayio.ColorConverter(),
                                                     position=position)
            except TypeError:
                self._bg_sprite = displayio.TileGrid(background,
                                                     pixel_shader=displayio.ColorConverter(),
                                                     x=position[0], y=position[1])
        elif isinstance(file_or_color, int):
            # Make a background color fill
            color_bitmap = displayio.Bitmap(320, 240, 1)
            color_palette = displayio.Palette(1)
            color_palette[0] = file_or_color
            try:
                self._bg_sprite = displayio.TileGrid(color_bitmap,
                                                     pixel_shader=color_palette,
                                                     position=(0, 0))
            except TypeError:
                self._bg_sprite = displayio.TileGrid(color_bitmap,
                                                     pixel_shader=color_palette,
                                                     x=position[0], y=position[1])
        else:
            raise RuntimeError("Unknown type of background")
        self._bg_group.append(self._bg_sprite)
        board.DISPLAY.refresh_soon()
        gc.collect()
        board.DISPLAY.wait_for_frame()

    def set_backlight(self, val):
        """Adjust the TFT backlight.

        :param val: The backlight brightness. Use a value between ``0`` and ``1``, where ``0`` is
                    off, and ``1`` is 100% brightness.

        """
        val = max(0, min(1.0, val))
        if self._backlight:
            self._backlight.duty_cycle = int(val * 65535)
        else:
            board.DISPLAY.auto_brightness = False
            board.DISPLAY.brightness = val

    def preload_font(self, glyphs=None):
        # pylint: disable=line-too-long
        """Preload font.

        :param glyphs: The font glyphs to load. Defaults to ``None``, uses alphanumeric glyphs if
                       None.

        """
        # pylint: enable=line-too-long
        if not glyphs:
            glyphs = b'0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-!,. "\'?!'
        print("Preloading font glyphs:", glyphs)
        if self._text_font:
            self._text_font.load_glyphs(glyphs)

    def set_caption(self, caption_text, caption_position, caption_color):
        # pylint: disable=line-too-long
        """A caption. Requires setting ``caption_font`` in init!

        :param caption_text: The text of the caption.
        :param caption_position: The position of the caption text.
        :param caption_color: The color of your caption text. Must be a hex value, e.g.
                              ``0x808000``.

        """
        # pylint: enable=line-too-long
        if self._debug:
            print("Setting caption to", caption_text)

        if (not caption_text) or (not self._caption_font) or (not caption_position):
            return  # nothing to do!

        if self._caption:
            self._caption._update_text(str(caption_text))  # pylint: disable=protected-access
            board.DISPLAY.refresh_soon()
            board.DISPLAY.wait_for_frame()
            return

        self._caption = Label(self._caption_font, text=str(caption_text))
        self._caption.x = caption_position[0]
        self._caption.y = caption_position[1]
        self._caption.color = caption_color
        self.splash.append(self._caption)

    def set_text(self, val, index=0):
        """Display text, with indexing into our list of text boxes.

        :param str val: The text to be displayed
        :param index: Defaults to 0.

        """
        if self._text_font:
            string = str(val)
            if self._text_maxlen[index]:
                string = string[:self._text_maxlen[index]]
            if self._text[index]:
                # print("Replacing text area with :", string)
                # self._text[index].text = string
                # return
                items = []
                while len(self.splash):  # pylint: disable=len-as-condition
                    item = self.splash.pop()
                    if item == self._text[index]:
                        break
                    items.append(item)
                self._text[index] = Label(self._text_font, text=string)
                self._text[index].color = self._text_color[index]
                self._text[index].x = self._text_position[index][0]
                self._text[index].y = self._text_position[index][1]
                self.splash.append(self._text[index])
                for g in items:
                    self.splash.append(g)
                return

            if self._text_position[index]:  # if we want it placed somewhere...
                print("Making text area with string:", string)
                self._text[index] = Label(self._text_font, text=string)
                self._text[index].color = self._text_color[index]
                self._text[index].x = self._text_position[index][0]
                self._text[index].y = self._text_position[index][1]
                self.splash.append(self._text[index])

    def neo_status(self, value):
        """The status NeoPixel.

        :param value: The color to change the NeoPixel.

        """
        if self.neopix:
            self.neopix.fill(value)

    def play_file(self, file_name, wait_to_finish=True):
        """Play a wav file.

        :param str file_name: The name of the wav file to play on the speaker.

        """
        board.DISPLAY.wait_for_frame()
        wavfile = open(file_name, "rb")
        wavedata = audioio.WaveFile(wavfile)
        self._speaker_enable.value = True
        self.audio.play(wavedata)
        if not wait_to_finish:
            return
        while self.audio.playing:
            pass
        wavfile.close()
        self._speaker_enable.value = False

    @staticmethod
    def _json_traverse(json, path):
        value = json
        for x in path:
            value = value[x]
            gc.collect()
        return value

    def get_local_time(self, location=None):
        # pylint: disable=line-too-long
        """Fetch and "set" the local time of this microcontroller to the local time at the location, using an internet time API.

        :param str location: Your city and country, e.g. ``"New York, US"``.

        """
        # pylint: enable=line-too-long
        self._connect_esp()
        api_url = None
        try:
            aio_username = secrets['aio_username']
            aio_key = secrets['aio_key']
        except KeyError:
            raise KeyError("\n\nOur time service requires a login/password to rate-limit. Please register for a free adafruit.io account and place the user/key in your secrets file under 'aio_username' and 'aio_key'")# pylint: disable=line-too-long

        location = secrets.get('timezone', location)
        if location:
            print("Getting time for timezone", location)
            api_url = (TIME_SERVICE + "&tz=%s") % (aio_username, aio_key, location)
        else: # we'll try to figure it out from the IP address
            print("Getting time from IP address")
            api_url = TIME_SERVICE % (aio_username, aio_key)
        api_url += TIME_SERVICE_STRFTIME
        try:
            response = requests.get(api_url)
            if self._debug:
                print("Time request: ", api_url)
                print("Time reply: ", response.text)
            times = response.text.split(' ')
            the_date = times[0]
            the_time = times[1]
            year_day = int(times[2])
            week_day = int(times[3])
            is_dst = None  # no way to know yet
        except KeyError:
            raise KeyError("Was unable to lookup the time, try setting secrets['timezone'] according to http://worldtimeapi.org/timezones")  # pylint: disable=line-too-long
        year, month, mday = [int(x) for x in the_date.split('-')]
        the_time = the_time.split('.')[0]
        hours, minutes, seconds = [int(x) for x in the_time.split(':')]
        now = time.struct_time((year, month, mday, hours, minutes, seconds, week_day, year_day,
                                is_dst))
        print(now)
        rtc.RTC().datetime = now

        # now clean up
        response.close()
        response = None
        gc.collect()

    def wget(self, url, filename, *, chunk_size=12000):
        """Download a url and save to filename location, like the command wget.

        :param url: The URL from which to obtain the data.
        :param filename: The name of the file to save the data to.
        :param chunk_size: how much data to read/write at a time.

        """
        print("Fetching stream from", url)

        self.neo_status((100, 100, 0))
        r = requests.get(url, stream=True)

        if self._debug:
            print(r.headers)
        content_length = int(r.headers['content-length'])
        remaining = content_length
        print("Saving data to ", filename)
        stamp = time.monotonic()
        file = open(filename, "wb")
        for i in r.iter_content(min(remaining, chunk_size)):  # huge chunks!
            self.neo_status((0, 100, 100))
            remaining -= len(i)
            file.write(i)
            if self._debug:
                print("Read %d bytes, %d remaining" % (content_length-remaining, remaining))
            else:
                print(".", end='')
            if not remaining:
                break
            self.neo_status((100, 100, 0))
        file.close()

        r.close()
        stamp = time.monotonic() - stamp
        print("Created file of %d bytes in %0.1f seconds" % (os.stat(filename)[6], stamp))
        self.neo_status((0, 0, 0))
        if not content_length == os.stat(filename)[6]:
            raise RuntimeError

    def _connect_esp(self):
        self.neo_status((0, 0, 100))
        while not self._esp.is_connected:
            # secrets dictionary must contain 'ssid' and 'password' at a minimum
            print("Connecting to AP", secrets['ssid'])
            if secrets['ssid'] == 'CHANGE ME' or secrets['ssid'] == 'CHANGE ME':
                change_me = "\n"+"*"*45
                change_me += "\nPlease update the 'secrets.py' file on your\n"
                change_me += "CIRCUITPY drive to include your local WiFi\n"
                change_me += "access point SSID name in 'ssid' and SSID\n"
                change_me += "password in 'password'. Then save to reload!\n"
                change_me += "*"*45
                raise OSError(change_me)
            self.neo_status((100, 0, 0)) # red = not connected
            try:
                self._esp.connect(secrets)
            except RuntimeError as error:
                print("Could not connect to internet", error)
                print("Retrying in 3 seconds...")
                time.sleep(3)

    @staticmethod
    def image_converter_url(image_url, width, height, color_depth=16):
        """Generate a converted image url from the url passed in,
           with the given width and height. aio_username and aio_key must be
           set in secrets."""
        try:
            aio_username = secrets['aio_username']
            aio_key = secrets['aio_key']
        except KeyError:
            raise KeyError("\n\nOur image converter service require a login/password to rate-limit. Please register for a free adafruit.io account and place the user/key in your secrets file under 'aio_username' and 'aio_key'")# pylint: disable=line-too-long

        return IMAGE_CONVERTER_SERVICE % (aio_username, aio_key,
                                          width, height,
                                          color_depth, image_url)

    def fetch(self, refresh_url=None):
        """Fetch data from the url we initialized with, perfom any parsing,
        and display text or graphics. This function does pretty much everything
        Optionally update the URL
        """
        if refresh_url:
            self._url = refresh_url
        json_out = None
        image_url = None
        values = []

        gc.collect()
        if self._debug:
            print("Free mem: ", gc.mem_free())  # pylint: disable=no-member

        r = None
        if self._uselocal:
            print("*** USING LOCALFILE FOR DATA - NOT INTERNET!!! ***")
            r = Fake_Requests(LOCALFILE)

        if not r:
            self._connect_esp()
            # great, lets get the data
            print("Retrieving data...", end='')
            self.neo_status((100, 100, 0))   # yellow = fetching data
            gc.collect()
            r = requests.get(self._url, headers=self._headers)
            gc.collect()
            self.neo_status((0, 0, 100))   # green = got data
            print("Reply is OK!")

        if self._debug:
            print(r.text)

        if self._image_json_path or self._json_path:
            try:
                gc.collect()
                json_out = r.json()
                gc.collect()
            except ValueError:            # failed to parse?
                print("Couldn't parse json: ", r.text)
                raise
            except MemoryError:
                supervisor.reload()

        if self._regexp_path:
            import re

        if self._image_url_path:
            image_url = self._image_url_path

        # extract desired text/values from json
        if self._json_path:
            for path in self._json_path:
                try:
                    values.append(PyPortal._json_traverse(json_out, path))
                except KeyError:
                    print(json_out)
                    raise
        elif self._regexp_path:
            for regexp in self._regexp_path:
                values.append(re.search(regexp, r.text).group(1))
        else:
            values = r.text

        if self._image_json_path:
            try:
                image_url = PyPortal._json_traverse(json_out, self._image_json_path)
            except KeyError as error:
                print("Error finding image data. '" + error.args[0] + "' not found.")
                self.set_background(self._default_bg)

        # we're done with the requests object, lets delete it so we can do more!
        json_out = None
        r = None
        gc.collect()

        if image_url:
            try:
                print("original URL:", image_url)
                image_url = self.image_converter_url(image_url,
                                                     self._image_resize[0],
                                                     self._image_resize[1])
                print("convert URL:", image_url)
                # convert image to bitmap and cache
                #print("**not actually wgetting**")
                filename = "/cache.bmp"
                chunk_size = 12000      # default chunk size is 12K (for QSPI)
                if self._sdcard:
                    filename = "/sd" + filename
                    chunk_size = 512  # current bug in big SD writes -> stick to 1 block
                try:
                    self.wget(image_url, filename, chunk_size=chunk_size)
                except OSError as error:
                    print(error)
                    raise OSError("""\n\nNo writable filesystem found for saving datastream. Insert an SD card or set internal filesystem to be unsafe by setting 'disable_concurrent_write_protection' in the mount options in boot.py""") # pylint: disable=line-too-long
                except RuntimeError as error:
                    print(error)
                    raise RuntimeError("wget didn't write a complete file")
                self.set_background(filename, self._image_position)
            except ValueError as error:
                print("Error displaying cached image. " + error.args[0])
                self.set_background(self._default_bg)
            finally:
                image_url = None
                gc.collect()

        # if we have a callback registered, call it now
        if self._success_callback:
            self._success_callback(values)

        # fill out all the text blocks
        if self._text:
            for i in range(len(self._text)):
                string = None
                if self._text_transform[i]:
                    func = self._text_transform[i]
                    string = func(values[i])
                else:
                    try:
                        string = "{:,d}".format(int(values[i]))
                    except (TypeError, ValueError):
                        string = values[i] # ok its a string
                if self._debug:
                    print("Drawing text", string)
                if self._text_wrap[i]:
                    if self._debug:
                        print("Wrapping text")
                    lines = PyPortal.wrap_nicely(string, self._text_wrap[i])
                    string = '\n'.join(lines)
                self.set_text(string, index=i)
        if len(values) == 1:
            return values[0]
        return values

    def show_QR(self, qr_data, qr_size=1, x=0, y=0):  # pylint: disable=invalid-name
        """Display a QR code on the TFT

        :param qr_data: The data for the QR code.
        :param int qr_size: The scale of the QR code.
        :param x: The x position of upper left corner of the QR code on the display.
        :param y: The y position of upper left corner of the QR code on the display.

        """
        import adafruit_miniqr
        # generate the QR code
        qrcode = adafruit_miniqr.QRCode()
        qrcode.add_data(qr_data)
        qrcode.make()

        # monochrome (2 color) palette
        palette = displayio.Palette(2)
        palette[0] = 0xFFFFFF
        palette[1] = 0x000000

        # pylint: disable=invalid-name
        # bitmap the size of the matrix, plus border, monochrome (2 colors)
        qr_bitmap = displayio.Bitmap(qrcode.matrix.width + 2, qrcode.matrix.height + 2, 2)
        for i in range(qr_bitmap.width * qr_bitmap.height):
            qr_bitmap[i] = 0

        # transcribe QR code into bitmap
        for xx in range(qrcode.matrix.width):
            for yy in range(qrcode.matrix.height):
                qr_bitmap[xx+1, yy+1] = 1 if qrcode.matrix[xx, yy] else 0

        # display the QR code
        qr_sprite = displayio.TileGrid(qr_bitmap, pixel_shader=palette)
        if self._qr_group:
            try:
                self._qr_group.pop()
            except IndexError: # later test if empty
                pass
        else:
            self._qr_group = displayio.Group()
            self.splash.append(self._qr_group)
        self._qr_group.scale = qr_size
        self._qr_group.x = x
        self._qr_group.y = y
        self._qr_group.append(qr_sprite)
        board.DISPLAY.show(self._qr_group)

    # return a list of lines with wordwrapping
    @staticmethod
    def wrap_nicely(string, max_chars):
        """A helper that will return a list of lines with word-break wrapping.

        :param str string: The text to be wrapped.
        :param int max_chars: The maximum number of characters on a line before wrapping.

        """
        string = string.replace('\n', '').replace('\r', '') # strip confusing newlines
        words = string.split(' ')
        the_lines = []
        the_line = ""
        for w in words:
            if len(the_line+' '+w) <= max_chars:
                the_line += ' '+w
            else:
                the_lines.append(the_line)
                the_line = ''+w
        if the_line:      # last line remaining
            the_lines.append(the_line)
        # remove first space from first line:
        the_lines[0] = the_lines[0][1:]
        return the_lines
