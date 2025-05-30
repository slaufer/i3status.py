import psutil
import math
import time
import json
import datetime

from py3nvml import py3nvml
py3nvml.nvmlInit()

GOOD_COLOR = (102, 255, 102)
GOOD_COLOR_HEX = f"#{GOOD_COLOR[0]:02x}{GOOD_COLOR[1]:02x}{GOOD_COLOR[2]:02x}"
BAD_COLOR = (255, 102, 102)
BAD_COLOR_HEX = f"#{BAD_COLOR[0]:02x}{BAD_COLOR[1]:02x}{BAD_COLOR[2]:02x}"

def grad(percent, start_color=GOOD_COLOR, end_color=BAD_COLOR):
    percent = max(0, min(100, percent)) / 100  # Normalize
    r = int(start_color[0] + (end_color[0] - start_color[0]) * percent)
    g = int(start_color[1] + (end_color[1] - start_color[1]) * percent)
    b = int(start_color[2] + (end_color[2] - start_color[2]) * percent)
    return f'#{r:02x}{g:02x}{b:02x}'

def grad_label(text, percent, sep=True, margin=1):
    margin_str = ' ' * margin
    text = margin_str + text + margin_str

    cutoff = (100 - percent) / 100 * len(text)

    last_solid = math.floor(cutoff)
    first_empty = math.ceil(cutoff)
    remainder = cutoff - last_solid

    rv = [
        {
            "full_text": text[:last_solid],
            "color": "#000000",
            "background": GOOD_COLOR_HEX,
        },
    ]

    if remainder > 0:
        rv.append({
            "full_text": text[last_solid:first_empty],
            "color": "#000000",
            "background": grad(remainder * 100),
        });


    if first_empty < len(text):
        rv.append({
            "full_text": text[first_empty:],
            "color": "#000000",
            "background": BAD_COLOR_HEX,
        })

    for i in range(0, len(rv) - 1):
        rv[i]['separator'] = False
        rv[i]['separator_block_width'] = 0

    if not sep:
        rv[-1]['separator'] = False
        rv[-1]['separator_block_width'] = 0

    return rv


def numformat(n, width=7):
    units = [" ", " Ki", " Mi", " Gi", " Ti", " Pi", " Ei"]
    tier = max(int(math.log2(abs(n)) // 10) if n != 0 else 0, 0)
    scaled = n / (2 ** (tier * 10))
    digits = max(int(math.log10(abs(scaled))) if scaled != 0 else 0, 0)
    decimals = width - (2 if scaled >= 0 else 3) - digits - len(units[tier])
    return f"{scaled:.{max(decimals, 0)}f}{units[tier]}".rjust(width)

def clock_module():
    return [{
        "full_text": datetime.datetime.now().strftime("%a %Y-%m-%d %I:%M:%S %p"),
    }];

def mem_module():
    vmem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    return [
        { "full_text": "ram", "separator": False },
        *grad_label(f"{numformat(vmem.available, 8)}B", vmem.percent),
        { "full_text": "swap", "separator": False },
        *grad_label(f"{numformat(swap.free, 8)}B", swap.percent),
    ]

def cpu_module():
    load = psutil.cpu_percent(percpu=True)

    rv = [{ "full_text": "cpu", "separator": False }]

    for i in range(0, len(load), 2):
        rv.append({
            "background": grad(load[i]),
            "color": grad(load[i+1]) if i+1 < len(load) else '#000000',
            "full_text": "\u2584",
            "separator": False,
            "separator_block_width": 0,
        })

    rv[-1]['separator'] = True
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
            { "full_text": f'gpu{gpuIndex}', "separator": False },
            *grad_label('          ', load.gpu),
            { "full_text": f'vram{gpuIndex}', "separator": False },
            *grad_label(f'{numformat(mem_avail, width=8)}B', mem_perc),
        ]

    return rv

def disk_module(label, path):
    usage = psutil.disk_usage(path)

    return [
        { "full_text": label, "separator": False },
        *grad_label(f'{numformat(usage.free, 8)}B', usage.free / usage.total * 100)
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
        })

        recv_rate = (counter.bytes_recv - last_counter.get('bytes_recv')) / interval
        sent_rate = (counter.bytes_sent - last_counter.get('bytes_sent')) / interval
        recv_rate_ewa = time_adjusted_EWA(recv_rate, interval, last_counter.get('recv_rate_ewa'), 2)
        sent_rate_ewa = time_adjusted_EWA(sent_rate, interval, last_counter.get('sent_rate_ewa'), 2)

        rv += [
            { "full_text": nic, "separator": False },
            {
                "full_text": f"\U0001f873",
                "separator": False,
                "color": GOOD_COLOR_HEX if recv_rate > 0 else None,
            },
            {
                "full_text": f"{numformat(recv_rate_ewa, 7)}B/s",
                "separator": False,
                "color": GOOD_COLOR_HEX if recv_rate_ewa > 0 else None,
            },
            {
                "full_text": f"\U0001f871",
                "separator": False,
                "color": BAD_COLOR_HEX if sent_rate > 0 else None,
            },
            {
                "full_text": f"{numformat(sent_rate_ewa, 7)}B/s",
                "color": BAD_COLOR_HEX if sent_rate_ewa > 0 else None,
            },
        ]

        net_counters[nic] = {
            "bytes_sent": counter.bytes_sent,
            "bytes_recv": counter.bytes_recv,
            "sent_rate_ewa": sent_rate_ewa,
            "recv_rate_ewa": recv_rate_ewa,
        }

    net_last = now
    return rv


def main():
    interval = 0.25
    print('{"version":1}\n[')

    while True:
        status = [] \
            + net_module(["wlp14s0"]) \
            + disk_module("root", "/") \
            + gpu_module() \
            + cpu_module() \
            + mem_module() \
            + clock_module()
        print(json.dumps(status), ",")
        time.sleep(interval)

if __name__ == '__main__':
    main()
