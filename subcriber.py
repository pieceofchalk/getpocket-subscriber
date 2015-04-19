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
import feedparser


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


def pocket_add(data):
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
    except Exception as error:
        print error


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

    def send_to_pocket(self, item):
        try:
            data = {"url": item.link, "title": item.title,
                    "consumer_key": self.key,
                    "access_token": self.token}
            pocket_add(data)
        except Exception as error:
            print item, error
        else:
            print '+' * 10, data['url'], data['title']
            self.new_count += 1

    def rss_to_pocket(self, feeds):
        for url in feeds:
            k = 0
            try:
                rss = feedparser.parse(url)
            except Exception as error:
                self.errors['errors'].append({'feed': url, 'error': error})
            else:
                if 'title' in rss.feed:
                    print rss.feed.title
                else:
                    print url
                for item in rss.entries:
                    k += 1 
                    if ('published_parsed' in rss.feed
                        and time.mktime(item.published_parsed) > self.last_run
                            or ('updated_parsed' in rss.feed
                                and time.mktime(item.updated_parsed)) > self.last_run):
                        self.send_to_pocket(item)
                    percents = '{}%'.format(int(k / (len(rss.entries)/100.0)))
                    sys.stdout.write(percents)
                    sys.stdout.flush()
                    sys.stdout.write('\b' * len(percents))
                sys.stdout.write('\b' * 18)

    def parse_outline(self, element):
        sub_level = [node for node in element.childNodes if is_outline(node)]
        if sub_level:
            for node in sub_level:
                self.parse_outline(node)
        else:
            self.feeds_count += 1
            keys = element.attributes.keys()
            if 'xmlUrl' in keys:
                self.feeds.append(element.attributes['xmlUrl'].value)
            else:
                el_repr = ';'.join('{}:{}'.format(key, element.attributes[key].value) for key in keys)
                self.errors['errors'].append({'feed': el_repr, 'error': 'No xmlUrl'})

    def parse_opml(self):
        doc = minidom.parse(self.opml_path)
        self.feeds_count = 0
        self.feeds = []
        body = doc.getElementsByTagName('body')[0]
        toplevel = [node for node in body.childNodes if is_outline(node)]
        for el in toplevel:
            self.parse_outline(el)

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
        self.last_run = self.bd_last_check()
        scan_start_time = time.time()
        self.new_count = 0
        self.errors = {'errors': []}
        self.parse_opml()
        # print self.feeds
        self.rss_to_pocket(self.feeds)

        if self.errors['errors']:
            status_extras = json.dumps(self.errors)
            status_string = 'done with errors'
            if self.new_count == 0:
                status_string = 'failed'
        else:
            status_extras = ''
            status_string = 'done'

        self.write_database(scan_start_time, status_string, status_extras)
        line = 'new_count: {}; feeds_count:{}; status_string:{};'
        print line.format(self.new_count, self.feeds_count, status_string)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--conf', dest='config_file', required=True,
                        type=argparse.FileType(mode='r'))
    parser.add_argument('--opml', dest='opml_file', type=str)

    args = parser.parse_args()
    Subscriber(args.config_file, opml_file=args.opml_file or None).run()
    # Subscriber(args.config_file).get_all_from_db()
