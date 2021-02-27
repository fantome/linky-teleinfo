#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# __licence__ = "Apache License 2.0"
# 
# Based on code write by Sébastien Reuiller (https://github.com/SebastienReuiller/teleinfo-linky-with-raspberry)
# Adapted for linky new protocol

# Python 3, prerequis : pip install pySerial influxdb
#
# Exemple de trame:
# {
#  'OPTARIF': 'HC..',        # option tarifaire
#  'IMAX': '007',            # intensité max
#  'HCHC': '040177099',      # index heure creuse en Wh
#  'IINST': '005',           # Intensité instantanée en A
#  'PAPP': '01289',          # puissance Apparente, en VA
#  'MOTDETAT': '000000',     # Mot d'état du compteur
#  'HHPHC': 'A',             # Horaire Heures Pleines Heures Creuses
#  'ISOUSC': '45',           # Intensité souscrite en A
#  'ADCO': '000000000000',   # Adresse du compteur
#  'HCHP': '035972694',      # index heure pleine en Wh
#  'PTEC': 'HP..'            # Période tarifaire en cours
# }


from configparser import ConfigParser
from datetime import datetime
from influxdb import InfluxDBClient
import logging
import requests
import serial
import sys
import time


####################################################################################################
# Constants                                                                                        #
####################################################################################################

# Config file path 
CONFIG_FILE = "/etc/linky-teleinfo.conf"

# Mandatory config keys
CONFIG_KEYS = [
    ["influxdb", "host"],
    ["influxdb", "path"],
    ["influxdb", "username"],
    ["influxdb", "password"],
    ["influxdb", "db"]
]

# Error message about config
CONFIG_ERROR = """Config file '%s' must be like:
[influxdb]
host=domain.tdl
path=influxdb
username=user
password=pass
db=teleinfo

[tags]
host=home
region=linky

Section 'tags' was optional.
""" % (CONFIG_FILE)
    
# Teleinfo key types
MEASURE_KEYS = {
    'EAST': 'int',
    'EASF01': 'int',
    'EASF02': 'int',
    'EASF03': 'int',
    'EASF04': 'int',
    'EASF05': 'int',
    'EASF06': 'int',
    'EASF07': 'int',
    'EASF08': 'int',
    'EASF09': 'int',
    'EASD01': 'int',
    'EASD02': 'int',
    'EASD03': 'int',
    'EASD04': 'int',
    'IRMS1': 'int',
    'URMS1': 'int',
    'PREF': 'int',
    'PCOUP': 'int',
    'SINSTS': 'int',
    'SMAXSN': 'date-int',
    'SMAXSN-1': 'date-int',
    'CCASN': 'date-int',
    'CCASN-1': 'date-int',
    'UMOY1': 'date-int'
}

# Number of frame to ignore between two insertion
IGNORE_FRAME = 10


def check_config(config: ConfigParser) -> bool:
    missing_keys = False
    for keys in CONFIG_KEYS:
        if (not keys[0] in config) or (not keys[1] in config[ keys[0] ]):
            logging.error("Missing config key: %s/%s" % tuple(keys))
            missing_keys = True
    if missing_keys:
        print(CONFIG_ERROR,file=sys.stderr)
        return False
    return True


def connect_influxdb(config: ConfigParser) -> InfluxDBClient:
    logging.info("Connect to InfluxDB...")
    client = InfluxDBClient(
            host=config["influxdb"]["host"],
            port=443,
            path=config["influxdb"]["path"],
            ssl=True,
            verify_ssl=True,
            username=config["influxdb"]["username"],
            password=config["influxdb"]["password"])
    db = config["influxdb"]["db"]

    connected = False
    while not connected:
        try:
            logging.info("Database %s exists?" % db)
            if not {'name': db} in client.get_list_database():
                logging.info("Database %s creation.." % db)
                client.create_database(db)
                logging.info("Database %s created!" % db)
            client.switch_database(db)
            logging.info("Connected to %s!" % db)
        except requests.exceptions.ConnectionError:
            logging.warn('InfluxDB is not reachable. Waiting 5 seconds to retry.')
            time.sleep(5)
        else:
            connected = True
    return client


def insert_frame(influxdb: InfluxDBClient, frame: dict):
    points = []
    for measure, fields in frame.items():
        point = {
            "measurement": measure,
            "tags": {
                "host": "odeon",
                "region": "linky"
            },
            "time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fields": fields
        }
        points.append(point)

    influxdb.write_points(points)


def read_frame(ser: serial.Serial) -> dict:
    logging.info("Teleinfo is reading on /dev/ttyAMA0..")
    frame = dict()

    # Read until we find start of a frame
    line = ser.readline()
    while b'\x02' not in line: # Finding char start a frame
        line = ser.readline()

    # Read frame
    line = ser.readline()
    while True:
        line_str = line.decode("utf-8")

        ar = line_str.split("\t")
        try:
            key = ar[0]
            if key in MEASURE_KEYS:
                fields = {}
                if MEASURE_KEYS[ key ] == 'int':
                    fields['value'] = int(ar[1])
                elif MEASURE_KEYS[ key ] == 'text':
                    fields['value'] = ar[1]
                elif MEASURE_KEYS[ key ] == 'date-int':
                    fields['date'] = ar[1]
                    fields['value'] = int(ar[2])
                frame[key] = fields

            if b'\x03' in line:  # Ending char find, return frame info
                logging.debug(frame)
                return frame

        except Exception as e:
            logging.error("Exception : %s" % e)
        line = ser.readline()


def ignore_frame(ser: serial.Serial, limit: int):
    cnt = 0
    # Counting ignored frame base on Start char
    line = ser.readline()
    while cnt < limit:
        if b'\x02' in line:
            cnt += 1
        line = ser.readline()


def main():
    # Init logging
    logging.basicConfig(level=logging.INFO)
    logging.info("Teleinfo starting...")

    # Read config
    logging.info("Read config...")
    config = ConfigParser()
    config.read(CONFIG_FILE)
    if not check_config(config):
        print("Fix config")
        sys.exit(1)
    
    # Init tags from config
    tags = {}
    if "tags" in config:
        for k in config["tags"]:
            tags[k] = config["tags"][k]

    # Connect to InfluxDB
    influxdb = connect_influxdb(config)

    logging.info("Start collect data...")
    with serial.Serial(port='/dev/ttyAMA0', baudrate=9600, parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                       bytesize=serial.SEVENBITS, timeout=1) as ser:
        while True:
            # Read a frame and insert it in InfluxDB
            frame = read_frame(ser)
            insert_frame(influxdb, frame)

            # Ignore next N frame, we don't need a measure every second
            ignore_frame(ser, IGNORE_FRAME)


if __name__ == '__main__':
    main()
