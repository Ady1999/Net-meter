"""Example NetMeter plugin: shows the time and date.

Copy this file into NetMeter's plugins folder (Options > Plugins > Open plugins
folder), restart NetMeter, then tick "Time" / "Date" under Items to show.
"""
import time

NAME = "Clock"
ITEMS = [
    {"id": "time", "name": "Time", "label": "", "sample": "88:88:88"},
    {"id": "date", "name": "Date", "label": "", "sample": "Wed 88 Sep"},
]


def get_value(item_id):
    if item_id == "time":
        return time.strftime("%H:%M:%S")
    return time.strftime("%a %d %b")


def get_tooltip():
    return "Clock plugin: " + time.strftime("%A %d %B %Y")
