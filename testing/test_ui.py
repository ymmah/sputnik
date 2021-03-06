#
# Copyright 2014 Mimetic Markets, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#

__author__ = 'sameer'

import unittest
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import random
import string


class TestSputnikUI(unittest.TestCase):
    def setUp(self):
        self.driver = webdriver.Chrome()
        self.driver.get('https://sputnikmkt.com')

    def tearDown(self):
        self.driver.close()

    def test_connect(self):
        self.assertEqual(self.driver.title, 'Sputnik Exchange Engine')

    def test_register(self):
        test_username = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        test_password = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        test_nickname = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        self.driver.find_element_by_id("register").click()
        self.driver.find_element_by_id("register_username").send_keys(test_username)
        self.driver.find_element_by_id("register_password").send_keys(test_password)
        self.driver.find_element_by_id("register_nickname").send_keys(test_nickname)
        self.driver.find_element_by_id("register_email").send_keys("test@m2.io")
        self.driver.find_element_by_id("register_eula").click()
        self.driver.find_element_by_id("register_button").click()
        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.ID, 'account_menu')), "Register and login failed")

    def test_login(self):
        self.driver.find_element_by_id("login").click()
        self.driver.find_element_by_id("login_username").send_keys("marketmaker")
        self.driver.find_element_by_id("login_password").send_keys("marketmaker")
        self.driver.find_element_by_id("login_button").click()
        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.ID, 'account_menu')), "Login failed")

    def test_trading(self):
        # First login
        self.driver.find_element_by_id("login").click()
        self.driver.find_element_by_id("login_username").send_keys("marketmaker")
        self.driver.find_element_by_id("login_password").send_keys("marketmaker")
        self.driver.find_element_by_id("login_button").click()
        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.ID, 'account_menu')), 'Login failed')

        # For now we'll assume we have funds to trade with
        qty = self.driver.find_element_by_id("buy_quantity")
        qty.clear()
        qty.send_keys("1")

        price = self.driver.find_element_by_id("buy_price")
        price.clear()
        price.send_keys("100")
        self.driver.find_element_by_id("buyButton").click()
        alert_check = EC.alert_is_present()
        alert = alert_check(self.driver)
        if alert:
            alert.accept()

        # For now we'll assume we have funds to trade with
        qty = self.driver.find_element_by_id("sell_quantity")
        qty.clear()
        qty.send_keys("1")

        price = self.driver.find_element_by_id("sell_price")
        price.clear()
        price.send_keys("100")
        self.driver.find_element_by_id("sellButton").click()
        alert = alert_check(self.driver)
        if alert:
            alert.accept()




