# Copyright 2019 Andrew Rowe.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import

import os
import re
import tempfile
import time
import unittest

import flask

from flask_ipban.ip_ban import IpBan

page_text = 'Hello, world. {}'
localhost = '127.0.0.1'


def hello_world(parameter=None):
    return page_text.format(parameter)


class TestIpBan(unittest.TestCase):

    def setUp(self):
        self.app = flask.Flask(__name__)
        self.ban_seconds = 2
        self.ip_ban = IpBan(self.app, ban_seconds=self.ban_seconds, ban_count=5)
        self.client = self.app.test_client()

        self.app.route('/')(hello_world)
        self.app.route('/good/<int:parameter>')(hello_world)

    def testAddRemoveIpWhitelist(self):
        self.assertEqual(self.ip_ban.ip_whitelist_add(localhost), 1)
        for x in range(self.ip_ban.ban_count * 2):
            response = self.client.get('/doesnotexist')
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.ip_ban.ip_whitelist_remove(localhost))
        for x in range(self.ip_ban.ban_count * 2):
            response = self.client.get('/doesnotexist')
        response = self.client.get('/')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.ip_ban.ip_whitelist_remove(localhost))

    def testAddRemoveUrlWhitelist(self):
        test_pattern = '^/no_exist/[0-9]+$'
        test_url = '/no_exist'
        self.assertTrue(re.match(test_pattern, test_url + '/123'))
        self.assertFalse(re.match(test_pattern, test_url))

        self.assertEqual(self.ip_ban.url_pattern_add(test_pattern), 1)
        for x in range(self.ip_ban.ban_count * 2):
            self.client.get('{}/{}'.format(test_url, x))
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

        self.assertTrue(self.ip_ban.url_pattern_remove(test_pattern))
        for x in range(self.ip_ban.ban_count * 2):
            self.client.get('{}/{}'.format(test_url, x))
        response = self.client.get('/')
        self.assertEqual(response.status_code, 403)

        self.assertFalse(self.ip_ban.url_pattern_remove(localhost))

    def testBlock(self):
        self.assertEqual(self.ip_ban.block([localhost, '123.1.1.3']), 2)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 403)

    def testTimeout(self):
        test_url = '/doesnotexist'
        for x in range(self.ip_ban.ban_count * 2):
            self.client.get('{}/{}'.format(test_url, x))
        response = self.client.get('/')
        self.assertEqual(response.status_code, 403)
        time.sleep(self.ban_seconds + 1)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

    def testManualBlockTimeout(self):
        self.ip_ban.block([localhost])
        response = self.client.get('/')
        self.assertEqual(response.status_code, 403)
        time.sleep(self.ban_seconds + 1)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

    def testBlockPermanent(self):
        self.ip_ban.block([localhost], permanent=True)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 403)
        time.sleep(self.ban_seconds + 2)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 403)

    def testAdd(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.ip_ban.add(ip=localhost, url='/', reason='spite')
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        for x in range(self.ip_ban.ban_count + 1):
            self.ip_ban.add(ip=localhost, url='/', reason='spite')
        response = self.client.get('/')
        self.assertEqual(response.status_code, 403)

    def testKeepOnBlocking(self):
        # block should not timeout if spamming continues
        test_url = '/doesnotexist'
        for x in range(self.ip_ban.ban_count * 2):
            self.client.get('{}/{}'.format(test_url, x))
        response = self.client.get('/')
        self.assertEqual(response.status_code, 403)
        for x in range(self.ban_seconds * 2):
            time.sleep(1)
            response = self.client.get('/')
            self.assertEqual(response.status_code, 403)

    def testAddRemoveUrlBlocklist(self):
        test_pattern = '^/good/[0-9]+$'
        test_url = '/good'
        self.assertTrue(re.match(test_pattern, test_url + '/123'))
        self.assertFalse(re.match(test_pattern, test_url))

        # no block
        response = self.client.get('{}/{}'.format(test_url, 456))
        self.assertEqual(response.status_code, 200)

        # getting index page is blocked after block url get
        self.assertEqual(self.ip_ban.url_block_pattern_add(test_pattern), 1)
        response = self.client.get('{}/{}'.format(test_url, 123))
        self.assertEqual(response.status_code, 403)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 403)

        # ban remains even after timeout
        time.sleep(self.ban_seconds + 1)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        response = self.client.get('{}/{}'.format(test_url, 123))
        self.assertEqual(response.status_code, 403)

        # ban remains even after pattern removed
        self.assertTrue(self.ip_ban.url_block_pattern_remove(test_pattern))
        response = self.client.get('{}/{}'.format(test_url, 200))
        self.assertEqual(response.status_code, 403)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 403)

        self.assertFalse(self.ip_ban.url_block_pattern_remove(localhost))

    def testLoadNuisances(self):
        self.app.route('/regextest/page.<parameter>')(hello_world)
        # test is ok before nuisances loaded
        response = self.client.get('/regextest/page.{e}?yolo={e}'.format(e='jsp'))
        self.assertEqual(response.status_code, 200)
        self.ip_ban.load_nuisances()

        # test blocked extensions
        for e in ['php', 'jsp', 'aspx', 'do', 'cgi']:
            self.assertTrue(self.ip_ban.test_pattern_blocklist('/regextest/page.{}'.format(e)), e)

        # and with parameters
        for e in ['php', 'jsp', 'aspx', 'do', 'cgi']:
            self.assertTrue(self.ip_ban.test_pattern_blocklist('/regextest/page.{e}?extension={e}'.format(e=e)), e)

        # test blocked url strings and patterns
        for e in ['/admin/assets/js/views/login.js', '/vip163mx00.mxmail.netease.com:25', '/manager/html']:
            self.assertTrue(self.ip_ban.test_pattern_blocklist(e), e)

        e = 'jsp'
        response = self.client.get('/regextest/page.{}'.format(e))
        self.assertEqual(response.status_code, 403, e)
        # this ip is no blocked
        response = self.client.get('/')
        self.assertEqual(response.status_code, 403)


tmp_file_name = os.path.join(tempfile.gettempdir(), 'blah.pickle')


class TestIpBanPersistence(unittest.TestCase):

    def setUp(self):
        self.app = flask.Flask(__name__)
        self.ban_seconds = 2
        self.ip_ban = IpBan(self.app, ban_seconds=self.ban_seconds, ban_count=5, persist=True,
                            persist_file_name=tmp_file_name)
        self.client = self.app.test_client()

        self.app.route('/')(hello_world)

    def testPersistence1(self):
        self.ip_ban.block(['123.456.765.111'])

    def testPersistence2(self):
        self.assertTrue('123.456.765.111' in self.ip_ban._ip_ban_list)
