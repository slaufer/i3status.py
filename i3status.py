import psutil
import math
import time
import json
import datetime
import sys
import traceback
import subprocess


from py3nvml import py3nvml
from pydbus import SessionBus

py3nvml.nvmlInit()
bus = SessionBus()

def rgb_to_hex(color):
    r, g, b = color
    return f"#{r:02x}{g:02x}{b:02x}"

LABEL_FG_COLOR = (0, 175, 255)
LABEL_FG_COLOR_HEX = rgb_to_hex(LABEL_FG_COLOR)

LIGHT_FG_COLOR = (170, 255, 255)
DARK_FG_COLOR = (0, 0, 0)

#BRIGHT_COLOR = (102, 255, 102)
BRIGHT_COLOR = (95, 255, 255)
BRIGHT_COLOR_HEX = rgb_to_hex(BRIGHT_COLOR)
BRIGHT_COLOR_FG_HEX = rgb_to_hex(DARK_FG_COLOR)

#MID_COLOR = (255, 255, 102)
MID_COLOR = (0, 175, 255)

#DARK_COLOR = (255, 102, 102)
DARK_COLOR = (0, 47, 95)
DARK_COLOR_HEX = rgb_to_hex(DARK_COLOR)
DARK_COLOR_FG_HEX = rgb_to_hex(LIGHT_FG_COLOR)

RX_COLOR = (102, 255, 102)
RX_COLOR_HEX = rgb_to_hex(RX_COLOR)

TX_COLOR = (255, 102, 102)
TX_COLOR_HEX = f"#{TX_COLOR[0]:02x}{TX_COLOR[1]:02x}{TX_COLOR[2]:02x}"
TX_COLOR_HEX = rgb_to_hex(TX_COLOR)

def grad_bg(
        percent,
        start_color=BRIGHT_COLOR,
        mid_color=MID_COLOR,
        end_color=DARK_COLOR,
        reverse=False,
):
    if reverse:
        percent = max(0, min(100, percent)) / 100
    else:
        percent = max(0, min(100, 100 - percent)) / 100
    if percent < 0.5:
        # Interpolate between start and mid
        ratio = percent / 0.5
        a, b = start_color, mid_color
    else:
        # Interpolate between mid and end
        ratio = (percent - 0.5) / 0.5
        a, b = mid_color, end_color

    r = int(a[0] + (b[0] - a[0]) * ratio)
    g = int(a[1] + (b[1] - a[1]) * ratio)
    b = int(a[2] + (b[2] - a[2]) * ratio)

    return r, g, b

def grad_fg(br, bg, bb):
    lum = 0.2126*br + 0.7152*bg + 0.0722*bb

    if lum > 127:
        return DARK_FG_COLOR

    return LIGHT_FG_COLOR

def grad_bg_fg(*args, **kwargs):
    br, bg, bb = grad_bg(*args, **kwargs)
    fr, fg, fb = grad_fg(br, bg, bb)

    return f'#{br:02x}{bg:02x}{bb:02x}', \
            f'#{fr:02x}{fg:02x}{fb:02x}'


def grad(*args, **kwargs):
    br, bg, bb = grad_bg(*args, **kwargs)
    return f'#{br:02x}{bg:02x}{bb:02x}'

def grad_label(text, percent, sep=True, margin=1, reverse=False):
    margin_str = ' ' * margin
    text = margin_str + text + margin_str

    if reverse:
        cutoff = (100 - percent) / 100 * len(text)
    else:
        cutoff = percent / 100 * len(text)

    last_solid = math.floor(cutoff)
    first_empty = math.ceil(cutoff)
    remainder = cutoff - last_solid

    rv = [
        {
            "full_text": text[:last_solid],
            "color": BRIGHT_COLOR_FG_HEX,
            "background": BRIGHT_COLOR_HEX,
        },
    ]

    if remainder > 0:
        bg, fg = grad_bg_fg(remainder * 100, reverse=reverse)
        rv.append({
            "full_text": text[last_solid:first_empty],
            "color": fg,
            "background": bg,
        });


    if first_empty < len(text):
        rv.append({
            "full_text": text[first_empty:],
            "color": DARK_COLOR_FG_HEX,
            "background": DARK_COLOR_HEX,
        })

    for i in range(0, len(rv) - 1):
        rv[i]['separator'] = False
        rv[i]['separator_block_width'] = 0

    if not sep:
        rv[-1]['separator'] = False

    return rv


def numformat(n, width=7):
    units = [" B", " K", " M", " G", " T", " P", " E"]
    tier = max(int(math.log2(abs(n)) // 10) if n != 0 else 0, 0)
    scaled = n / (2 ** (tier * 10))
    digits = max(int(math.log10(abs(scaled))) if scaled != 0 else 0, 0)
    decimals = width - (2 if scaled >= 0 else 3) - digits - len(units[tier])
    return f"{scaled:.{max(decimals, 0)}f}{units[tier]}".rjust(width)

def clock_module():
    return [{
        "full_text": datetime.datetime.now().strftime("%a %Y-%m-%d %I:%M:%S %p"),
        "color": LABEL_FG_COLOR_HEX
    }];

def mem_module():
    vmem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    return [
        { "full_text": "ram", "separator": False, "color": LABEL_FG_COLOR_HEX },
        *grad_label(f"{numformat(vmem.available, 7)}", vmem.percent, sep=False),
        { "full_text": "swap", "separator": False, "color": LABEL_FG_COLOR_HEX },
        *grad_label(f"{numformat(swap.free, 7)}", swap.percent, sep=False),
    ]

def cpu_module():
    load = psutil.cpu_percent(percpu=True)

    rv = [{ "full_text": "cpu", "separator": False, "color": LABEL_FG_COLOR_HEX }]

    for i in range(0, len(load), 2):
        rv.append({
            "background": grad(load[i]),
            "color": grad(load[i+1]) if i+1 < len(load) else '#000000',
            "full_text": "\u2584",
            "separator": False,
            "separator_block_width": 0,
        })

    del rv[-1]['separator_block_width']

    return rv


gpu_handles = {}

def gpu_module(gpus=[0]):
    rv = []

    for gpuIndex in gpus:
        handle = gpu_handles.get(gpuIndex)

        if handle is None:
            handle = py3nvml.nvmlDeviceGetHandleByIndex(gpuIndex)
            gpu_handles[gpuIndex] = handle

        label = py3nvml.nvmlDeviceGetName(handle)
        load = py3nvml.nvmlDeviceGetUtilizationRates(handle)
        mem = py3nvml.nvmlDeviceGetMemoryInfo(handle)
        mem_perc = mem.used / mem.total * 100
        mem_avail = mem.total - mem.used

        rv += [
            { "full_text": f'gpu{gpuIndex}', "separator": False, "color": LABEL_FG_COLOR_HEX },
            *grad_label('         ', load.gpu, sep=False),
            { "full_text": f'vram{gpuIndex}', "separator": False, "color": LABEL_FG_COLOR_HEX },
            *grad_label(f'{numformat(mem_avail, width=7)}', mem_perc, sep=False),
        ]

    return rv

def disk_module(label, path):
    usage = psutil.disk_usage(path)

    return [
        { "full_text": label, "separator": False, "color": LABEL_FG_COLOR_HEX },
        *grad_label(f'{numformat(usage.free, width=7)}', usage.free / usage.total * 100, sep=False)
    ]

net_counters = {}
net_counters_beta = 0.9
net_last = time.time()

def time_adjusted_EWA(v, dt, pv, tau):
    sf = math.e**(-dt/tau)
    return  sf * pv + (1 - sf) * v


def net_module(nics):
    global net_last # yeah i used a global fight me
    counters = psutil.net_io_counters(pernic=True)
    now = time.time()
    interval = now - net_last
    rv = []

    for nic in nics:
        counter = counters.get(nic)

        if counter is None:
            continue

        last_counter = net_counters.get(nic, {
            "bytes_sent": counter.bytes_sent,
            "bytes_recv": counter.bytes_recv,
            "sent_rate_ewa": 0,
            "recv_rate_ewa": 0,
            "sent_hwm": 1,
            "recv_hwm": 1,
        })

        recv_rate = (counter.bytes_recv - last_counter.get('bytes_recv')) / interval
        sent_rate = (counter.bytes_sent - last_counter.get('bytes_sent')) / interval
        recv_rate_ewa = time_adjusted_EWA(recv_rate, interval, last_counter.get('recv_rate_ewa'), 1)
        sent_rate_ewa = time_adjusted_EWA(sent_rate, interval, last_counter.get('sent_rate_ewa'), 1)
        sent_hwm = max(last_counter['sent_hwm'], sent_rate)
        recv_hwm = max(last_counter['recv_hwm'], recv_rate)

        rv += [
            { "full_text": nic, "separator": False, "color": LABEL_FG_COLOR_HEX },
            {
                "full_text": "\U0001f873",
                "separator": False,
                "color": RX_COLOR_HEX if recv_rate > 0 else "#606060",
            },
            *grad_label(f"{numformat(recv_rate_ewa, 6)}", recv_rate_ewa / recv_hwm * 100, sep=False),
            {
                "full_text": "\U0001f871",
                "separator": False,
                "color": TX_COLOR_HEX if sent_rate > 0 else "#606060",
            },
            *grad_label(f"{numformat(sent_rate_ewa, 6)}", sent_rate_ewa / sent_hwm * 100, sep=False),
        ]

        net_counters[nic] = {
            "bytes_sent": counter.bytes_sent,
            "bytes_recv": counter.bytes_recv,
            "sent_rate_ewa": sent_rate_ewa,
            "recv_rate_ewa": recv_rate_ewa,
            "sent_hwm": sent_hwm,
            "recv_hwm": recv_hwm,
        }

    net_last = now
    return rv

def marquee(text, width, rate=0.25, separator=' | '):
    if len(text) <= width:
        return text + (width - len(text)) * " "

    text += separator

    begin = math.floor(time.time() / rate) % len(text)
    end = begin + width
    rv = text[begin:end]

    if end > len(text):
        rv += text[:end - len(text)]

    return rv

def media_module(width):
    name = next((name for name in bus.get(".DBus").ListNames() if name.startswith("org.mpris.MediaPlayer2")), None)
    if name is None:
        return []

    try:
        player = bus.get(name, "/org/mpris/MediaPlayer2")
        metadata = player.Metadata
    except:
        return []

    media_name = ' - '.join([x for x in [
        ', '.join(metadata.get("xesam:artist", [])),
        metadata.get("xesam:album"),
        metadata.get("xesam:title"),
    ] if x is not None and x != ''])

    if media_name == '' or media_name is None:
        return []

    # marqee text according to width and i
    #text += " \u23f5 "

    return [
        { "full_text": "\u25b6", "color": LABEL_FG_COLOR_HEX, "separator": False },
        { "full_text": " " + marquee(media_name, width) + " ", "separator": False, "color": BRIGHT_COLOR_HEX, "background": DARK_COLOR_HEX },
    ]

mullvad_cache = None
mullvad_last_check = 0

def mullvad_module():
    global mullvad_cache, mullvad_last_check

    now = time.time()

    # Return cached value if within throttle period
    if mullvad_cache is not None and (now - mullvad_last_check) < 2:
        return mullvad_cache

    # Execute and update cache
    try:
        result = subprocess.run(['mullvad', 'status'],
                              capture_output=True,
                              text=True)
        status = result.stdout.strip()

        if status.startswith('Connected'):
            icon = "\U0001f512"  # 🔒 locked
            color = BRIGHT_COLOR_HEX

            # Extract relay name from output
            relay = None
            for line in status.split('\n'):
                if 'Relay:' in line:
                    relay = line.split('Relay:')[1].strip()
                    break

            rv = [{
                "full_text": icon,
                "color": color,
                "separator": False,
            }]

            if relay:
                rv.append({
                    "full_text": f"{relay}",
                    "color": LABEL_FG_COLOR_HEX,
                    "separator": False,
                })

            mullvad_cache = rv
        else:
            icon = "\U0000274C"  # ❌ unlocked
            color = TX_COLOR_HEX

            mullvad_cache = [{
                "full_text": icon,
                "color": color,
                "separator": False,
            }]

        mullvad_last_check = now
        return mullvad_cache
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as ex:
        # If mullvad command fails or times out, return empty
        print(ex)
        mullvad_cache = []
        mullvad_last_check = now
        return []

def eq_module():
    # ▂▃▄▅▆▇█
    chars = [ ' ', '\u2581', '\u2582', '\u2583', '\u2584', '\u2585', '\u2586', '\u2587', '\u2588' ]

    return [{ "full_text": ''.join(chars)}]

def main():
    interval = 0.25
    print('{"version":1}\n[')

    i = 0

    while True:
        status = [] \
            + media_module(50) \
            + mullvad_module() \
            + net_module(["enp6s0"]) \
            + disk_module("root", "/") \
            + gpu_module() \
            + cpu_module() \
            + mem_module() \
            + clock_module()
        print(json.dumps(status), ",")
        i += 1
        time.sleep(interval)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        with open("i3status_errors.txt", "w") as f:
            f.write(traceback.format_exc())
