# -*- coding: utf-8 -*-
import ConfigParser
import argparse
from xml.dom import minidom
import sqlite3
from datetime import datetime
import time
import requests
import json
import sys


ADD_URL = 'https://getpocket.com/v3/add'
HEADERS = {'X-Accept': 'application/json', 'Content-Type': 'application/json'}
CREATE_DB_QUERY = '''CREATE TABLE IF NOT EXISTS subscriber
                     (scan_start_time TIMESTAMP NOT NULL,
                     scan_end_time TIMESTAMP NOT NULL,
                     new_count INT NOT NULL,
                     feeds_count INT NOT NULL,
                     status_string VARCHAR(32) NOT NULL,
                     status_extras MEDIUMTEXT NOT NULL)'''

LAST_CHECK_QUERY = '''SELECT scan_start_time
                      FROM subscriber
                      ORDER BY scan_start_time
                      DESC LIMIT 1'''

INSERT_QUERY = '''INSERT INTO subscriber (scan_start_time,
                  scan_end_time, new_count, feeds_count,
                  status_string, status_extras)
                  VALUES(?, ?, ?, ?, ?, ?)'''


def is_outline(node):
    if node.nodeType == node.ELEMENT_NODE and node.nodeName == 'outline':
        return True
    else:
        return False


def getText(nodelist):
    rc = []
    for node in nodelist:
        if node.nodeType == node.TEXT_NODE:
            rc.append(node.data)
    return ''.join(rc)


def date_created_oml(doc):
    head = doc.getElementsByTagName('head')[0]
    date = head.getElementsByTagName('dateCreated')[0]
    date = getText(date.childNodes)
    date = datetime.strptime(' '.join(date.split()[:-1]),
                             '%a, %d %b %Y %H:%M:%S')
    return date


def process_outline(element):
    error = {}
    outline = {}
    try:
        outline['title'] = element.attributes['title'].value
    except Exception as er:
        error[repr(element)] = str(er)
    else:
        try:
            _type = element.attributes['type'].value
            assert _type == 'rss', 'not rss'
        except Exception as er:
            error[outline['title']] = str(er)
        else:
            try:
                outline['url'] = element.attributes['xmlUrl'].value
            except Exception as er:
                error[outline['title']] = str(er)
    finally:
        return outline, error


class Subscriber():
    def __init__(self, _file):
        config = ConfigParser.ConfigParser()
        config.readfp(_file)
        self.sqlite_path = config.get('subscriber', 'sqlite_path')
        self.opml_path = config.get('subscriber', 'opml_path')
        self.key = config.get('subscriber', 'pocket_consumer_key')
        self.token = config.get('subscriber', 'pocket_access_token')

    def bd_last_check(self):
        db = sqlite3.connect(self.sqlite_path)
        cursor = db.cursor()
        cursor.execute(CREATE_DB_QUERY)
        cursor.execute(LAST_CHECK_QUERY)
        last_check = cursor.fetchone()
        return last_check

    def pocket(self, outlines):
        _len = len(outlines)
        self.new_count = 0
        sys.stdout.write('Sending to pocket:')
        sys.stdout.flush()
        for i in range(_len):
            data = {"url": outlines[i]['url'], "title": outlines[i]['title'],
                    "consumer_key": self.key,
                    "access_token": self.token}
            try:
                r = requests.post(ADD_URL, headers=HEADERS,
                                  data=json.dumps(data), timeout=5)
                if r.status_code != 200:
                    print 'Error: {}'.format(r.headers.get('x-error'))
                    if r.headers.get('x-limit-user-remaining') == '0':
                        sleep = int(r.headers.get('x-limit-user-reset'))
                        if sleep:
                            print 'Wait {}sec'.format(sleep)
                            time.sleep(sleep)
                # print req.headers
            except Exception as error:
                print error
            else:
                self.new_count += 1
            percents = '{}%'.format(int((i + 1) / (_len/100.0)))
            sys.stdout.write(percents)
            sys.stdout.flush()
            sys.stdout.write('\b' * len(percents))
        sys.stdout.write('\b' * 18)

    def get_outlines(self, doc):
        self.feeds_count = 0
        self.errors = {'errors': []}
        self.outlines = []
        body = doc.getElementsByTagName('body')[0]
        toplevel = [node for node in body.childNodes if is_outline(node)]
        for el in toplevel:
            sub_level = [node for node in el.childNodes if is_outline(node)]
            for node in sub_level:
                self.feeds_count += 1
                outline, error = process_outline(node)
                if error:
                    self.errors['errors'].append(error)
                else:
                    self.outlines.append(outline)

    def write_database(self, scan_start_time, status_string, status_extras):
        db = sqlite3.connect(self.sqlite_path)
        scan_end_time = time.time()
        try:
            db.executemany(INSERT_QUERY, [(scan_start_time, scan_end_time,
                                           self.new_count, self.feeds_count,
                                           status_string, status_extras)])
            db.commit()
            db.close()
        except Exception as error:
            print error

    def process(self):
        doc = minidom.parse(self.opml_path)
        last_check = self.bd_last_check()
        if (last_check and date_created_oml(doc) > datetime.fromtimestamp(last_check[0])) or not last_check:
            scan_start_time = time.time()
            self.get_outlines(doc)
            self.pocket(self.outlines)
            if self.errors['errors']:
                status_extras = json.dumps(self.errors)
            else:
                status_extras = ''
            if self.new_count == 0:
                status_string = 'failed'
            elif self.new_count == self.feeds_count:
                status_string = 'done'
            else:
                status_string = 'done with errors'

            self.write_database(scan_start_time, status_string, status_extras)
            line = 'new_count: {}; feeds_count:{}; status_string:{};'
            print line.format(self.new_count, self.feeds_count, status_string)
        else:
            print 'now new feeds in opml: {}'.format(self.opml_path)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config-file', dest='config_file', required=True,
                        type=argparse.FileType(mode='r'))
    args = parser.parse_args()
    # process(args.config_file)
    Subscriber(args.config_file).process()
