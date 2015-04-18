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

INSERT_QUERY = '''INSERT INTO subscriber VALUES(?, ?, ?, ?, ?, ?)'''


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
    if head.getElementsByTagName('dateModified'):
        date = head.getElementsByTagName('dateModified')[0]
    else:
        date = head.getElementsByTagName('dateCreated')[0]

    date = getText(date.childNodes)
    date = datetime.strptime(' '.join(date.split()[:-1]),
                             '%a, %d %b %Y %H:%M:%S')
    return date


class Subscriber():
    def __init__(self, _file, opml_file):
        config = ConfigParser.ConfigParser()
        config.readfp(_file)
        self.sqlite_path = config.get('subscriber', 'sqlite_path')
        if opml_file:
            self.opml_path = opml_file
        else:
            self.opml_path = config.get('subscriber', 'opml_path')
        self.key = config.get('subscriber', 'pocket_consumer_key')
        self.token = config.get('subscriber', 'pocket_access_token')

    def bd_last_check(self):
        con = sqlite3.connect(self.sqlite_path)
        cur = con.cursor()
        try:
            cur.execute(CREATE_DB_QUERY)
            cur.execute(LAST_CHECK_QUERY)
            last_check = cur.fetchone()
            con.commit()
        except Exception as error:
            con.close()
            print error
        else:
            con.close()
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
                pass
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

    def process_outline(self, element):
        sub_level = [node for node in element.childNodes if is_outline(node)]
        if sub_level:
            for node in sub_level:
                self.process_outline(node)
        else:
            keys = element.attributes.keys()
            self.feeds_count += 1
            error = {}
            outline = {}
            try:
                for key in keys:
                    if 'title' in key.lower():
                        title = key
                        break
                    if 'text' in key.lower():
                        title = key
                outline['title'] = element.attributes[title].value
                print outline['title']
                assert outline['title'], 'no title'
            except Exception as er:
                error['element'] = repr(element)
                error['error'] = str(er)
            else:
                for key in keys:
                    if 'url' in key.lower():
                        url = key
                try:
                    outline['url'] = element.attributes[url].value
                    assert outline['url'], 'no url'
                except Exception as er:
                    error['element'] = [outline['title']]
                    error['error'] = str(er)
                else:
                    self.outlines.append(outline)
            finally:
                if error:
                    self.errors['errors'].append(error)

    def get_outlines(self, doc):
        self.feeds_count = 0
        self.errors = {'errors': []}
        self.outlines = []
        body = doc.getElementsByTagName('body')[0]
        toplevel = [node for node in body.childNodes if is_outline(node)]
        for el in toplevel:
            self.process_outline(el)

    def write_database(self, scan_start_time, status_string, status_extras):
        con = sqlite3.connect(self.sqlite_path)
        cur = con.cursor()
        scan_end_time = time.time()
        try:
            cur.execute(INSERT_QUERY,  (scan_start_time, scan_end_time,
                                        self.new_count, self.feeds_count,
                                        status_string, status_extras))
            con.commit()
        except Exception as error:
            print error
        finally:
            con.close()

    def get_all_from_db(self):
        db = sqlite3.connect(self.sqlite_path)
        cur = db.cursor()
        cur.execute('SELECT * FROM subscriber')
        print cur.fetchall()
        db.close()

    def run(self):
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
            print 'no new feeds in opml: {}'.format(self.opml_path)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--conf-file', dest='config_file', required=True,
                        type=argparse.FileType(mode='r'))
    parser.add_argument('--opml-file', dest='opml_file', type=str)

    args = parser.parse_args()
    Subscriber(args.config_file, opml_file=args.opml_file or None).run()
    # Subscriber(args.config_file).get_all_from_db()
