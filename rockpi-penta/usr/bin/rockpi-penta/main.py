#!/usr/bin/env python3
import queue
import threading
import time
import traceback

import fan
import misc

try:
    import oled

    top_board = True
except Exception as ex:
    traceback.print_exc()
    top_board = False

q = queue.Queue()
lock = threading.Lock()

action = {
    'none': lambda: 'nothing',
    'slider': lambda: oled.slider(lock),
    'switch': lambda: misc.fan_switch(),
    'reboot': lambda: misc.check_call('reboot'),
    'poweroff': lambda: misc.check_call('poweroff'),
}


def receive_key(q):
    # A gesture that started on a dark screen only wakes it up. Otherwise a
    # double click on a dark screen would silently switch the fan off.
    # The deadline covers the longest gesture, so a gesture the pattern
    # matcher never recognised can't make us skip a later one.
    skip_until = 0
    while True:
        key = q.get()
        try:
            if key == 'down':
                if oled.wake(lock):
                    skip_until = (time.monotonic() + misc.conf['time']['press']
                                  + misc.conf['time']['twice'] + 1)
                continue
            if oled.wake(lock) or time.monotonic() < skip_until:
                skip_until = 0
                continue
            action[misc.get_func(key)]()
        except Exception:
            # Keep the key thread alive, or the screen can never be woken.
            traceback.print_exc()


if __name__ == '__main__':

    if top_board:
        oled.welcome()
        p0 = threading.Thread(target=receive_key, args=(q,), daemon=True)
        p1 = threading.Thread(target=misc.watch_key, args=(q,), daemon=True)
        p2 = threading.Thread(target=oled.auto_slider, args=(lock,), daemon=True)
        p3 = threading.Thread(target=fan.running, daemon=True)

        p0.start()
        p1.start()
        p2.start()
        p3.start()
        try:
            p3.join()
        except KeyboardInterrupt:
            misc.conf['run'].value = 0
            print("GoodBye ~")
            oled.goodbye()

    else:
        p3 = threading.Thread(target=fan.running, daemon=False)
        p3.start()
