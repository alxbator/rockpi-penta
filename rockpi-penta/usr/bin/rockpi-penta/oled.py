#!/usr/bin/python3
import atexit
import os
import time
import traceback

import adafruit_ssd1306
import board
import digitalio
import busio
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
import multiprocessing as mp

import misc

font = {
    '10': ImageFont.truetype('fonts/DejaVuSansMono-Bold.ttf', 10),
    '11': ImageFont.truetype('fonts/DejaVuSansMono-Bold.ttf', 11),
    '12': ImageFont.truetype('fonts/DejaVuSansMono-Bold.ttf', 12),
    '14': ImageFont.truetype('fonts/DejaVuSansMono-Bold.ttf', 14),
}


def disp_init():
    RESET = getattr(board.pin, os.environ['OLED_RESET'])
    i2c = busio.I2C(getattr(board.pin, os.environ['SCL']), getattr(board.pin, os.environ['SDA']))
    disp = adafruit_ssd1306.SSD1306_I2C(128, 32, i2c, reset=digitalio.DigitalInOut(RESET))
    disp.fill(0)
    disp.show()
    return disp


disp = disp_init()

image = Image.new('1', (disp.width, disp.height))
draw = ImageDraw.Draw(image)


def off_deadline():
    """When to switch the screen off if no key is pressed from now on."""
    minutes = misc.conf['oled']['timeout']
    return time.monotonic() + minutes * 60 if minutes > 0 else float('inf')


# Screen state, guarded by the lock that main.py passes around.
#   on         - the panel is lit
#   off_at     - time.monotonic() at which to switch it off
#   next_slide - time.monotonic() at which auto_slider shows the next page
screen = {'on': True, 'off_at': off_deadline(), 'next_slide': 0.0}

# Don't leave a static picture lit when the service stops or crashes.
atexit.register(disp.poweroff)


def disp_show():
    im = image.rotate(180) if misc.conf['oled']['rotate'] else image
    disp.image(im)
    disp.write_framebuf()
    draw.rectangle((0, 0, disp.width, disp.height), outline=0, fill=0)


def welcome():
    draw.text((0, 0), 'ROCKPi SATA HAT', font=font['14'], fill=255)
    draw.text((32, 16), 'Loading...', font=font['12'], fill=255)
    disp_show()


def goodbye():
    draw.text((32, 8), 'Good Bye ~', font=font['14'], fill=255)
    disp_show()
    time.sleep(2)
    disp_show()  # clear


def put_disk_info():
    k, v = misc.get_disk_info()
    text1 = 'Disk: {} {}'.format(k[0], v[0])

    if len(k) == 5:
        text2 = '{} {}  {} {}'.format(k[1], v[1], k[2], v[2])
        text3 = '{} {}  {} {}'.format(k[3], v[3], k[4], v[4])
        page = [
            {'xy': (0, -2), 'text': text1, 'fill': 255, 'font': font['11']},
            {'xy': (0, 10), 'text': text2, 'fill': 255, 'font': font['11']},
            {'xy': (0, 21), 'text': text3, 'fill': 255, 'font': font['11']},
        ]
    elif len(k) == 3:
        text2 = '{} {}  {} {}'.format(k[1], v[1], k[2], v[2])
        page = [
            {'xy': (0, 2), 'text': text1, 'fill': 255, 'font': font['12']},
            {'xy': (0, 18), 'text': text2, 'fill': 255, 'font': font['12']},
        ]
    else:
        page = [{'xy': (0, 2), 'text': text1, 'fill': 255, 'font': font['14']}]

    return page


def gen_pages():
    pages = {
        0: [
            {'xy': (0, -2), 'text': misc.get_info('up'), 'fill': 255, 'font': font['11']},
            {'xy': (0, 10), 'text': misc.get_cpu_temp(), 'fill': 255, 'font': font['11']},
            {'xy': (0, 21), 'text': misc.get_info('ip'), 'fill': 255, 'font': font['11']},
        ],
        1: [
            {'xy': (0, 2), 'text': misc.get_info('cpu'), 'fill': 255, 'font': font['12']},
            {'xy': (0, 18), 'text': misc.get_info('men'), 'fill': 255, 'font': font['12']},
        ],
        2: put_disk_info()
    }

    return pages


def show_page(page):
    """Draw a page and schedule the next automatic slide. Caller holds the lock."""
    for item in page:
        draw.text(**item)
    disp_show()
    if misc.conf['slider']['auto']:
        screen['next_slide'] = time.monotonic() + misc.conf['slider']['time']
    else:
        screen['next_slide'] = float('inf')


def slider(lock):
    with lock:
        if screen['on']:
            show_page(misc.slider_next(gen_pages()))


def wake(lock):
    """Push the switch-off time back and light the screen if it is dark.

    Returns True if the screen was dark: the key press that woke it
    must not do anything else.
    """
    with lock:
        screen['off_at'] = off_deadline()
        if screen['on']:
            return False
        misc.conf['idx'].value = -1  # wake up on the first page
        page = misc.slider_next(gen_pages())
        # Not disp.poweron(): it pulses the reset pin, and the controller
        # comes back unconfigured, i.e. still dark. init_display() sends
        # the whole setup sequence and ends with "display on".
        disp.init_display()
        screen['on'] = True
        show_page(page)
        return True


def auto_slider(lock):
    """Show the next page every [slider] time seconds while the screen is lit,
    and switch the screen off [oled] timeout minutes after the last key press.
    """
    while True:
        try:
            with lock:
                now = time.monotonic()
                if screen['on'] and now >= screen['off_at']:
                    disp.poweroff()
                    screen['on'] = False
                due = screen['on'] and now >= screen['next_slide']
            if due:
                slider(lock)
        except Exception:
            # Keep the loop alive: if it dies, the screen is never switched off.
            traceback.print_exc()
        time.sleep(1)


if __name__ == '__main__':
    # for test
    lock = mp.Lock()
    auto_slider(lock)
