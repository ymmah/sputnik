#
# Copyright 2014 Mimetic Markets, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#

import sys
import os
from test_sputnik import fix_config, TestSputnik, FakeComponent
from twisted.internet import defer, reactor, task
from pprint import pprint

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "../server"))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "../tools"))

fix_config()

accountant_init = """
permissions add Deposit deposit login
permissions add Trade trade login
permissions add Withdraw withdraw login
"""

from sputnik.exception import AccountantException


class FakeEngine(FakeComponent):
    name = "engine"

    def place_order(self, order):
        self._log_call('place_order', order)
        # Always return a good fake result
        return defer.succeed(order.id)

    def cancel_order(self, id):
        self._log_call('cancel_order', id)
        # Always return success, with None
        return defer.succeed(None)


class FakeLedger(FakeComponent):
    name = "ledger"

    def post(self, *postings):
        self._log_call('post', *postings)
        return defer.succeed(None)


from sputnik import accountant


class FakeAccountantProxy(accountant.AccountantExport):
    def get_accountant_for_user(self, username):
        return 0


class FakeSafePriceNotifier():
    @property
    def safe_price(self):
        return defer.succeed(42)

class FakeWebserverNotifier():
    def __init__(self, ticker):
        self.ticker = ticker

    @property
    def wire_book(self):
        return defer.succeed({"contract": self.ticker,
                 "bids": [{"quantity": 1,
                           "price": 1}],
                 "asks": [{"quantity": 1,
                           "price": 2}]})


class TestAccountantBase(TestSputnik):
    def setUp(self):
        # This can't be run by itself because it needs TestSputnik.setUp
        if self.__class__.__name__ != "TestAccountantBase":
            self.run_leo(accountant_init)
            from sputnik import accountant
            from sputnik import ledger
            from sputnik import cashier
            from sputnik import engine2

            self.engines = {"BTC/MXN": engine2.AccountantExport(FakeEngine(), FakeSafePriceNotifier(), FakeWebserverNotifier('BTC/MXN')),
                            "BTC/PLN": engine2.AccountantExport(FakeEngine(), FakeSafePriceNotifier(), FakeWebserverNotifier('BTC/PLN')),
                            "BTC/HUF": engine2.AccountantExport(FakeEngine(), FakeSafePriceNotifier(), FakeWebserverNotifier('BTC/HUF')),
                            "NETS2014": engine2.AccountantExport(FakeEngine(), FakeSafePriceNotifier(), FakeWebserverNotifier('NETS2014')),
                            "NETS2015": engine2.AccountantExport(FakeEngine(), FakeSafePriceNotifier(), FakeWebserverNotifier('NETS2015')),
                            'USDBTC0W': engine2.AccountantExport(FakeEngine(), FakeSafePriceNotifier(), FakeWebserverNotifier('USDBTC0W'))}
            self.webserver = FakeComponent("webserver")
            self.cashier = cashier.AccountantExport(FakeComponent("cashier"))
            self.ledger = ledger.AccountantExport(ledger.Ledger(self.session.bind.engine, 5000))
            self.alerts_proxy = FakeComponent("alerts")
            # self.accountant_proxy = accountant.AccountantExport(FakeComponent("accountant"))
            
            from test_sputnik import FakeSendmail
            
            self.accountant = accountant.Accountant(self.session, self.engines,
                                                    self.cashier,
                                                    self.ledger,
                                                    self.webserver,
                                                    None,
                                                    self.alerts_proxy,
                                                    debug=True,
                                                    trial_period=False,
                                                    sendmail=FakeSendmail('test-email@m2.io'),
                                                    template_dir="../server/sputnik/admin_templates",                                                    
                                                    )
            self.accountant.accountant_proxy = FakeAccountantProxy(self.accountant)
            self.cashier_export = accountant.CashierExport(self.accountant)
            self.administrator_export = accountant.AdministratorExport(self.accountant)
            self.webserver_export = accountant.WebserverExport(self.accountant)
            self.engine_export = accountant.EngineExport(self.accountant)
            self.riskmanager_export = accountant.RiskManagerExport(self.accountant)


class TestAccountantAudit(TestAccountantBase):
    def setUp(self):
        TestSputnik.setUp(self)

        # Mess up some users before we start the test
        self.create_account("messed_up_trader_a", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')

        from sputnik import models

        BTC = self.session.query(models.Contract).filter_by(ticker='BTC').one()
        BTCMXN = self.session.query(models.Contract).filter_by(ticker='BTC/MXN').one()
        messed_up_trader_a = self.session.query(models.User).filter_by(username='messed_up_trader_a').one()

        btc_position = self.session.query(models.Position).filter_by(username='messed_up_trader_a', contract=BTC).one()
        btc_position.pending_postings = 1
        btc_position.position = 50
        self.session.add(btc_position)

        btc_order = models.Order(messed_up_trader_a, BTCMXN, 1, 100, 'BUY')
        self.session.add(btc_order)

        self.session.commit()
        self.order_id = btc_order.id

        self.clock = task.Clock()
        reactor.callLater = self.clock.callLater

        TestAccountantBase.setUp(self)

    def test_messed_up_a(self):
        self.accountant.repair_user_positions()
        from sputnik import models, util
        import datetime

        BTC = self.session.query(models.Contract).filter_by(ticker="BTC").one()
        position = self.session.query(models.Position).filter_by(username="messed_up_trader_a").filter_by(
            contract_id=BTC.id).one()
        self.assertEqual(position.pending_postings, 0)
        self.assertEqual(position.position, 50)
        with self.assertRaisesRegexp(AccountantException, 'disabled_user'):
            self.webserver_export.place_order('test', {'username': 'messed_up_trader_a',
                                                       'contract': 'BTC/MXN',
                                                       'price': 1000000,
                                                       'quantity': 3000000,
                                                       'side': 'SELL',
                                                       'timestamp': util.dt_to_timestamp(datetime.datetime.utcnow())})
        self.clock.advance(300)
        self.assertEqual(position.position, 0)
        with self.assertRaisesRegexp(AccountantException, 'trade_not_permitted'):
            self.webserver_export.place_order('test', {'username': 'messed_up_trader_a',
                                                       'contract': 'BTC/MXN',
                                                       'price': 1000000,
                                                       'quantity': 3000000,
                                                       'side': 'SELL',
                                                       'timestamp': util.dt_to_timestamp(datetime.datetime.utcnow())})


class TestAccountant(TestAccountantBase):
    def setUp(self):
        TestSputnik.setUp(self)
        TestAccountantBase.setUp(self)


    def set_permissions_group(self, username, groupname):
        from sputnik import models

        user = self.session.query(models.User).filter_by(username=username).one()
        group = self.session.query(models.PermissionGroup).filter_by(name=groupname).one()
        user.permissions = group
        self.session.merge(user)
        self.session.commit()

class TestCashierExport(TestAccountant):
    def test_deposit_cash_permission_allowed(self):
        from sputnik import models

        self.create_account('test', '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.set_permissions_group('test', 'Deposit')

        d = self.cashier_export.deposit_cash("test", "18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv", 10)

        def onSuccess(result):
            position = self.session.query(models.Position).filter_by(
                username="test").one()
            self.assertEqual(position.position, 10)
            self.assertTrue(self.webserver.component.check_for_calls([('transaction',
                                                                       (u'onlinecash',
                                                                        {'contract': u'BTC',
                                                                         'quantity': 10,
                                                                         'direction': 'debit',
                                                                         'type': u'Deposit'}),
                                                                       {}),
                                                                      ('transaction',
                                                                       (u'test',
                                                                        {'contract': u'BTC',
                                                                         'quantity': 10,
                                                                         'direction': 'credit',
                                                                         'type': u'Deposit'}),
                                                                       {})]))

        d.addCallback(onSuccess)
        return d

    def test_deposit_cash_too_much(self):
        from sputnik import models

        self.create_account('test', '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.set_permissions_group('test', 'Deposit')

        # Set a deposit limit
        self.accountant.deposit_limits['BTC'] = 100000000

        d = self.cashier_export.deposit_cash("test", "18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv", 1000000000)

        def onSuccess(result):
            position = self.session.query(models.Position).filter_by(
                username="test").one()

            self.assertEqual(position.position, self.accountant.deposit_limits['BTC'])

            # Make sure the overflow position gets the cash
            overflow_position = self.session.query(models.Position).filter_by(
                username="depositoverflow").one()
            self.assertEqual(overflow_position.position, 1000000000 - self.accountant.deposit_limits['BTC'])
            self.assertTrue(self.webserver.component.check_for_calls([('transaction',
                                                                       ('onlinecash',
                                                                        {'contract': u'BTC',
                                                                         'direction': 'debit',
                                                                         'quantity': 1000000000,
                                                                         'type': 'Deposit'}),
                                                                       {}),
                                                                      ('transaction',
                                                                       (u'test',
                                                                        {'contract': u'BTC',
                                                                         'direction': 'credit',
                                                                         'quantity': 1000000000,
                                                                         'type': 'Deposit'}),
                                                                       {}),
                                                                      ('transaction',
                                                                       (u'test',
                                                                        {'contract': u'BTC',
                                                                         'direction': 'debit',
                                                                         'quantity': 900000000,
                                                                         'type': 'Deposit'}),
                                                                       {}),
                                                                      ('transaction',
                                                                       ('depositoverflow',
                                                                        {'contract': u'BTC',
                                                                         'direction': 'credit',
                                                                         'quantity': 900000000,
                                                                         'type': 'Deposit'}),
                                                                       {})]))
            self.assertTrue(self.accountant.sendmail.component.check_for_calls([('send_mail',
                                                                                 (
                                                                                 'Hello anonymous (test),\n\nWe received your deposit, however 9.00 BTC was not\ncredited to your account because you have exceeded your permitted deposit limit.\n\nPlease contact support with any questions.\n',),
                                                                                 {
                                                                                 'subject': 'Your deposit was not fully processed',
                                                                                 'to_address': u'<> anonymous'})]))

        d.addCallback(onSuccess)
        return d

    def test_deposit_cash_permission_denied(self):
        from sputnik import models

        self.create_account('test', '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.session.commit()

        d = self.cashier_export.deposit_cash("test", "18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv", 10)

        def onSuccess(result):
            # Make sure the position didn't get updated
            position = self.session.query(models.Position).filter_by(
                username="test").one()
            self.assertEqual(position.position, 0)

            # Make sure the overflow position gets the cash
            overflow_position = self.session.query(models.Position).filter_by(
                username="depositoverflow").one()
            self.assertEqual(overflow_position.position, 10)
            self.assertTrue(self.webserver.component.check_for_calls([('transaction',
                                                                       ('onlinecash',
                                                                        {'contract': u'BTC',
                                                                         'direction': 'debit',
                                                                         'quantity': 10,
                                                                         'type': 'Deposit'}),
                                                                       {}),
                                                                      ('transaction',
                                                                       (u'test',
                                                                        {'contract': u'BTC',
                                                                         'direction': 'credit',
                                                                         'quantity': 10,
                                                                         'type': 'Deposit'}),
                                                                       {}),
                                                                      ('transaction',
                                                                       (u'test',
                                                                        {'contract': u'BTC',
                                                                         'direction': 'debit',
                                                                         'quantity': 10,
                                                                         'type': 'Deposit'}),
                                                                       {}),
                                                                      ('transaction',
                                                                       ('depositoverflow',
                                                                        {'contract': u'BTC',
                                                                         'direction': 'credit',
                                                                         'quantity': 10,
                                                                         'type': 'Deposit'}),
                                                                       {})]
            ))
            self.assertTrue(self.accountant.sendmail.component.check_for_calls([('send_mail',
                                                                                 (
                                                                                 'Hello anonymous (test),\n\nWe received your deposit, however 0.00 BTC was not\ncredited to your account because you have exceeded your permitted deposit limit.\n\nPlease contact support with any questions.\n',),
                                                                                 {
                                                                                 'subject': 'Your deposit was not fully processed',
                                                                                 'to_address': u'<> anonymous'})]))

        d.addCallback(onSuccess)
        return d

    def test_transfer_position(self):
        from sputnik import models

        self.create_account("from_account", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.create_account("to_account", '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.set_permissions_group('from_account', 'Deposit')
        self.set_permissions_group('to_account', 'Deposit')
        self.cashier_export.deposit_cash("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 10)
        self.cashier_export.deposit_cash("test", '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 10)

        from sputnik import util

        uid = util.get_uid()
        d1 = self.administrator_export.transfer_position('from_account', 'BTC', 'debit', 5, 'note', uid)
        d2 = self.administrator_export.transfer_position('to_account', 'BTC', 'credit', 5, None, uid)
        d = defer.DeferredList([d1, d2])

        def onSuccess(result):
            from_position = self.session.query(models.Position).filter_by(username='from_account').one()
            to_position = self.session.query(models.Position).filter_by(username='to_account').one()

            self.assertEqual(from_position.position, 5)
            self.assertEqual(to_position.position, 15)
            self.assertTrue(self.webserver.component.check_for_calls([('transaction',
                                                                       ('onlinecash',
                                                                        {'contract': u'BTC',
                                                                         'direction': 'debit',
                                                                         'quantity': 10,
                                                                         'type': 'Deposit'}),
                                                                       {}),
                                                                      ('transaction',
                                                                       (u'from_account',
                                                                        {'contract': u'BTC',
                                                                         'direction': 'credit',
                                                                         'quantity': 10,
                                                                         'type': 'Deposit'}),
                                                                       {}),
                                                                      ('transaction',
                                                                       ('onlinecash',
                                                                        {'contract': u'BTC',
                                                                         'direction': 'debit',
                                                                         'quantity': 10,
                                                                         'type': 'Deposit'}),
                                                                       {}),
                                                                      ('transaction',
                                                                       (u'to_account',
                                                                        {'contract': u'BTC',
                                                                         'direction': 'credit',
                                                                         'quantity': 10,
                                                                         'type': 'Deposit'}),
                                                                       {}),
                                                                      ('transaction',
                                                                       ('from_account',
                                                                        {'contract': 'BTC',
                                                                         'direction': 'debit',
                                                                         'quantity': 5,
                                                                         'type': 'Transfer'}),
                                                                       {}),
                                                                      ('transaction',
                                                                       ('to_account',
                                                                        {'contract': 'BTC',
                                                                         'direction': 'credit',
                                                                         'quantity': 5,
                                                                         'type': 'Transfer'}),
                                                                       {})]
            ))

        d.addCallback(onSuccess)
        return d

    def test_get_position(self):
        self.create_account('test', '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.set_permissions_group('test', 'Deposit')

        self.cashier_export.deposit_cash("test", "18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv", 10)
        position = self.cashier_export.get_position('test', 'BTC')
        self.assertEqual(position, 10)


class TestAdministratorExport(TestAccountant):
    def test_change_fee_group(self):
        self.create_account('test', '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        from sputnik import models
        id = self.session.query(models.FeeGroup.id).filter_by(name='MarketMaker').one().id
        self.administrator_export.change_fee_group('test', id)
        test = self.get_user('test')
        self.assertEqual(test.fees.id, id)

    def test_reload_fee_group(self):
        from sputnik import models
        id = self.session.query(models.FeeGroup.id).filter_by(name='MarketMaker').one().id
        self.administrator_export.reload_fee_group(None, id)

        # TODO: What can we assert here?

    def test_clear_contract_prediction(self):
        self.create_account("short_account", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.create_account("long_account", '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')

        from sputnik import util
        from sputnik import models
        import datetime

        # Create a short and a long position
        uid = util.get_uid()
        d1 = self.administrator_export.transfer_position('short_account', 'NETS2015', 'debit', 5, 'note', uid)
        d2 = self.administrator_export.transfer_position('long_account', 'NETS2015', 'credit', 5, None, uid)


        # Deposit cash
        self.set_permissions_group('short_account', 'Deposit')
        self.set_permissions_group('long_account', 'Deposit')

        self.cashier_export.deposit_cash("short_account", "18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv", 53000000)
        self.cashier_export.deposit_cash("long_account", "28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv", 3000000)


        # Create some orders
        self.set_permissions_group("short_account", 'Trade')
        self.set_permissions_group("long_account", "Trade")

        self.webserver_export.place_order('short_account', {'username': 'short_account',
                                                            'contract': 'NETS2015',
                                                            'price': 900,
                                                            'quantity': 3,
                                                            'side': 'SELL',
                                                            'timestamp': util.dt_to_timestamp(
                                                                datetime.datetime.utcnow())})

        self.webserver_export.place_order('long_account', {'username': 'long_account',
                                                           'contract': 'NETS2015',
                                                           'price': 100,
                                                           'quantity': 3,
                                                           'side': 'BUY',
                                                           'timestamp': util.dt_to_timestamp(
                                                               datetime.datetime.utcnow())})
        d = defer.DeferredList([d1, d2])

        def on_setup_done(results):
            uid = util.get_uid()

            # Set the contract to have already expired in the past
            NETS = self.session.query(models.Contract).filter_by(ticker='NETS2015').one()
            NETS.expiration = datetime.datetime.utcnow() - datetime.timedelta(days=1)
            self.session.add(NETS)
            self.session.commit()

            d = self.administrator_export.clear_contract(None, 'NETS2015', 1000, uid)

            def on_clear(results):
                BTC = self.session.query(models.Contract).filter_by(ticker='BTC').one()
                short_positions = self.session.query(models.Position).filter_by(username='short_account')
                long_positions = self.session.query(models.Position).filter_by(username='long_account')
                self.assertEqual(short_positions.filter_by(contract=NETS).one().position, 0)
                self.assertEqual(long_positions.filter_by(contract=NETS).one().position, 0)

                self.assertEqual(short_positions.filter_by(contract=BTC).one().position, 53000000 - 5000000)
                self.assertEqual(long_positions.filter_by(contract=BTC).one().position, 3000000 + 5000000)

                short_orders = self.session.query(models.Order).filter_by(username='short_account').filter_by(
                    is_cancelled=False).all()
                long_orders = self.session.query(models.Order).filter_by(username='long_account').filter_by(
                    is_cancelled=False).all()
                self.assertEquals(long_orders, [])
                self.assertEquals(short_orders, [])

            d.addCallback(on_clear)
            return d

        d.addCallback(on_setup_done)
        return d

    def test_clear_contract_futures(self):
        from sputnik import util
        from sputnik import models
        import datetime

        self.create_account("short_account", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.create_account("long_account", '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')

        # Deposit cash
        self.set_permissions_group('short_account', 'Deposit')
        self.set_permissions_group('long_account', 'Deposit')

        self.cashier_export.deposit_cash("short_account", "18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv", 5000000)
        self.cashier_export.deposit_cash("long_account", "28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv", 5000000)

        self.set_permissions_group("short_account", 'Trade')
        self.set_permissions_group("long_account", "Trade")

        o1 = self.webserver_export.place_order('short_account', {'username': 'short_account',
                                                                 'contract': 'USDBTC0W',
                                                                 'price': 1100,
                                                                 'quantity': 1,
                                                                 'side': 'SELL',
                                                                 'timestamp': util.dt_to_timestamp(
                                                                     datetime.datetime.utcnow())})

        o2 = self.webserver_export.place_order('long_account', {'username': 'long_account',
                                                                'contract': 'USDBTC0W',
                                                                'price': 900,
                                                                'quantity': 1,
                                                                'side': 'BUY',
                                                                'timestamp': util.dt_to_timestamp(
                                                                    datetime.datetime.utcnow())})

        # Make like a trade happened
        uid = util.get_uid()
        long_transaction = {
            'username': 'long_account',
            'aggressive': True,
            'contract': 'USDBTC0W',
            'order': o1,
            'other_order': o2,
            'side': 'BUY',
            'price': 1000,
            'quantity': 1,
            'timestamp': 234234,
            'uid': uid
        }

        import copy

        short_transaction = copy.copy(long_transaction)
        short_transaction['aggressive'] = False
        short_transaction['order'] = o2
        short_transaction['other_order'] = o1
        short_transaction['side'] = 'SELL'
        short_transaction['username'] = 'short_account'

        d1 = self.accountant.post_transaction('short_account', short_transaction)
        d2 = self.accountant.post_transaction('long_account', long_transaction)

        d = defer.DeferredList([d1, d2])

        def on_setup_done(results):
            uid = util.get_uid()

            # Set the contract to have already expired in the past
            USDBTC = self.session.query(models.Contract).filter_by(ticker='USDBTC0W').one()
            USDBTC.expiration = datetime.datetime.utcnow() - datetime.timedelta(days=1)
            self.session.add(USDBTC)
            self.session.commit()

            # Clear at 50 more than it was traded for
            d = self.administrator_export.clear_contract(None, 'USDBTC0W', 1050, uid)

            def on_clear(results):
                BTC = self.session.query(models.Contract).filter_by(ticker='BTC').one()
                short_positions = self.session.query(models.Position).filter_by(username='short_account')
                long_positions = self.session.query(models.Position).filter_by(username='long_account')
                clearing_positions = self.session.query(models.Position).filter_by(username='clearing_USDBTC0W')

                # Clearing account should be totally empty
                for position in clearing_positions:
                    self.assertEqual(position.position, 0)

                # short_account should have lost 50 x lotsize / denominator plus fees (200bps of transaction size)
                for position in short_positions:
                    if position.contract.ticker == 'BTC':
                        self.assertEqual(position.position, 5000000 - 50 * 100000 / 1000 - 1000 * 100000 / 1000 * 0.02)
                    if position.contract.ticker == 'USDBTC0W':
                        self.assertEqual(position.position, 0)

                # Long account should have gained 50 x lotsize / denominator - fees (200bps)
                for position in long_positions:
                    if position.contract.ticker == 'BTC':
                        self.assertEqual(position.position, 5000000 + 50 * 100000 / 1000 - 1000 * 100000 / 1000 * 0.02)
                    if position.contract.ticker == 'USDBTC0W':
                        self.assertEqual(position.position, 0)

            d.addCallback(on_clear)
            return d

        d.addCallback(on_setup_done)

    def test_transfer_position(self):
        from sputnik import models

        self.create_account("from_account", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.create_account("to_account", '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.set_permissions_group('from_account', 'Deposit')
        self.set_permissions_group('to_account', 'Deposit')
        self.cashier_export.deposit_cash("from_account", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 10)
        self.cashier_export.deposit_cash("to_account", '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 10)

        from sputnik import util

        uid = util.get_uid()
        d1 = self.administrator_export.transfer_position('from_account', 'BTC', 'debit', 5, 'note', uid)
        d2 = self.administrator_export.transfer_position('to_account', 'BTC', 'credit', 5, None, uid)
        d = defer.DeferredList([d1, d2])

        def onSuccess(result):
            from_position = self.session.query(models.Position).filter_by(username='from_account').one()
            to_position = self.session.query(models.Position).filter_by(username='to_account').one()

            self.assertEqual(from_position.position, 5)
            self.assertEqual(to_position.position, 15)
            self.assertTrue(self.webserver.component.check_for_calls([('transaction',
                                                                       ('onlinecash',
                                                                        {'contract': u'BTC',
                                                                         'direction': 'debit',
                                                                         'quantity': 10,
                                                                         'type': 'Deposit'}),
                                                                       {}),
                                                                      ('transaction',
                                                                       (u'from_account',
                                                                        {'contract': u'BTC',
                                                                         'direction': 'credit',
                                                                         'quantity': 10,
                                                                         'type': 'Deposit'}),
                                                                       {}),
                                                                      ('transaction',
                                                                       ('onlinecash',
                                                                        {'contract': u'BTC',
                                                                         'direction': 'debit',
                                                                         'quantity': 10,
                                                                         'type': 'Deposit'}),
                                                                       {}),
                                                                      ('transaction',
                                                                       (u'to_account',
                                                                        {'contract': u'BTC',
                                                                         'direction': 'credit',
                                                                         'quantity': 10,
                                                                         'type': 'Deposit'}),
                                                                       {}),
                                                                      ('transaction',
                                                                       ('from_account',
                                                                        {'contract': 'BTC',
                                                                         'direction': 'debit',
                                                                         'quantity': 5,
                                                                         'type': 'Transfer'}),
                                                                       {}),
                                                                      ('transaction',
                                                                       ('to_account',
                                                                        {'contract': 'BTC',
                                                                         'direction': 'credit',
                                                                         'quantity': 5,
                                                                         'type': 'Transfer'}),
                                                                       {})]
            ))


        d.addCallback(onSuccess)
        return d

    def test_adjust_position(self):
        from sputnik import models

        self.create_account("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.set_permissions_group('test', 'Deposit')
        self.cashier_export.deposit_cash('test', '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 10)

        d = self.administrator_export.adjust_position('test', 'BTC', 10, admin_username='test_admin')

        def onSuccess(result):
            position = self.session.query(models.Position).filter_by(
                username="test").one()
            self.assertEqual(position.position, 20)
            self.assertTrue(self.webserver.component.check_for_calls([('transaction',
                                                                       ('onlinecash',
                                                                        {'contract': u'BTC',
                                                                         'direction': 'debit',
                                                                         'quantity': 10,
                                                                         'type': 'Deposit'}),
                                                                       {}),
                                                                      ('transaction',
                                                                       (u'test',
                                                                        {'contract': u'BTC',
                                                                         'direction': 'credit',
                                                                         'quantity': 10,
                                                                         'type': 'Deposit'}),
                                                                       {}),
                                                                      ('transaction',
                                                                       ('test',
                                                                        {'contract': 'BTC',
                                                                         'direction': 'credit',
                                                                         'quantity': 10,
                                                                         'type': 'Transfer'}),
                                                                       {}),
                                                                      ('transaction',
                                                                       ('adjustments',
                                                                        {'contract': 'BTC',
                                                                         'direction': 'debit',
                                                                         'quantity': 10,
                                                                         'type': 'Transfer'}),
                                                                       {})]))

        d.addCallback(onSuccess)
        return d

    def test_change_permission_group(self):
        from sputnik import models

        self.create_account("test")
        id = self.session.query(models.PermissionGroup.id).filter_by(name='Deposit').one().id
        self.administrator_export.change_permission_group('test', id)
        user = self.session.query(models.User).filter_by(username='test').one()
        self.assertEqual(user.permission_group_id, id)


class TestEngineExport(TestAccountant):
    def test_post_transaction_predictions(self):
        from sputnik import util, models
        import datetime

        self.create_account("aggressive_user", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.create_account("passive_user", '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', )
        self.set_permissions_group("aggressive_user", 'Deposit')
        self.set_permissions_group("passive_user", "Deposit")
        self.cashier_export.deposit_cash('aggressive_user', '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)
        self.cashier_export.deposit_cash('passive_user', '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 3000000)

        self.set_permissions_group("aggressive_user", 'Trade')
        self.set_permissions_group("passive_user", "Trade")

        passive_order = self.webserver_export.place_order('passive_user', {'username': 'passive_user',
                                                                           'contract': 'NETS2015',
                                                                           'price': 500,
                                                                           'quantity': 3,
                                                                           'side': 'BUY',
                                                                           'timestamp': util.dt_to_timestamp(
                                                                               datetime.datetime.utcnow())})

        aggressive_order = self.webserver_export.place_order('aggressive_user', {'username': 'aggressive_user',
                                                                                 'contract': 'NETS2015',
                                                                                 'price': 500,
                                                                                 'quantity': 3,
                                                                                 'side': 'SELL',
                                                                                 'timestamp': util.dt_to_timestamp(
                                                                                     datetime.datetime.utcnow())})

        uid = util.get_uid()
        timestamp = util.dt_to_timestamp(datetime.datetime.utcnow())
        aggressive = {'username': 'aggressive_user',
                      'aggressive': True,
                      'contract': 'NETS2015',
                      'price': 500,
                      'quantity': 3,
                      'order': aggressive_order,
                      'other_order': passive_order,
                      'side': 'SELL',
                      'uid': uid,
                      'timestamp': timestamp}

        passive = {'username': 'passive_user',
                   'aggressive': False,
                   'contract': 'NETS2015',
                   'price': 500,
                   'quantity': 3,
                   'order': passive_order,
                   'other_order': aggressive_order,
                   'side': 'BUY',
                   'uid': uid,
                   'timestamp': timestamp}

        d1 = self.engine_export.post_transaction('aggressive_user', aggressive)
        d2 = self.engine_export.post_transaction('passive_user', passive)

        def onSuccess(result):
            # Inspect the positions
            BTC = self.session.query(models.Contract).filter_by(ticker='BTC').one()
            NETS2015 = self.session.query(models.Contract).filter_by(ticker='NETS2015').one()

            aggressive_user_btc_position = self.session.query(models.Position).filter_by(username='aggressive_user',
                                                                                         contract=BTC).one()
            passive_user_btc_position = self.session.query(models.Position).filter_by(username='passive_user',
                                                                                      contract=BTC).one()
            aggressive_user_NETS2015_position = self.session.query(models.Position).filter_by(
                username='aggressive_user',
                contract=NETS2015).one()
            passive_user_NETS2015_position = self.session.query(models.Position).filter_by(username='passive_user',
                                                                                           contract=NETS2015).one()

            # This is based a 200bps fee on both sides
            self.assertEqual(aggressive_user_btc_position.position, 5000000 + 1500000 * 0.98)
            self.assertEqual(passive_user_btc_position.position, 3000000 - 1500000 * 1.02)
            self.assertEqual(aggressive_user_btc_position.pending_postings, 0)
            self.assertEqual(passive_user_btc_position.pending_postings, 0)

            # There is no fee for prediction contracts on trade
            self.assertEqual(aggressive_user_NETS2015_position.position, -3)
            self.assertEqual(passive_user_NETS2015_position.position, 3)

        dl = defer.DeferredList([d1, d2])
        dl.addCallback(onSuccess)
        return dl

    def test_post_transaction(self):
        from sputnik import util, models
        import datetime

        self.create_account("aggressive_user", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.create_account("passive_user", '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 'MXN')
        self.set_permissions_group("aggressive_user", 'Deposit')
        self.set_permissions_group("passive_user", "Deposit")
        self.cashier_export.deposit_cash('aggressive_user', '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)
        self.cashier_export.deposit_cash('passive_user', '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 3000000)

        self.add_address('aggressive_user', 'MXN_address', 'MXN')
        self.add_address('passive_user', 'BTC_address', 'BTC')

        self.cashier_export.deposit_cash('aggressive_user', 'MXN_address', 500000)
        self.cashier_export.deposit_cash('passive_user', 'BTC_address', 400000000)

        self.set_permissions_group("aggressive_user", 'Trade')
        self.set_permissions_group("passive_user", "Trade")

        passive_order = self.webserver_export.place_order('passive_user', {'username': 'passive_user',
                                                                           'contract': 'BTC/MXN',
                                                                           'price': 60000000,
                                                                           'quantity': 3000000,
                                                                           'side': 'BUY',
                                                                           'timestamp': util.dt_to_timestamp(
                                                                               datetime.datetime.utcnow())})

        aggressive_order = self.webserver_export.place_order('aggressive_user', {'username': 'aggressive_user',
                                                                                 'contract': 'BTC/MXN',
                                                                                 'price': 60000000,
                                                                                 'quantity': 3000000,
                                                                                 'side': 'SELL',
                                                                                 'timestamp': util.dt_to_timestamp(
                                                                                     datetime.datetime.utcnow())})

        uid = util.get_uid()
        timestamp = util.dt_to_timestamp(datetime.datetime.utcnow())
        aggressive = {'username': 'aggressive_user',
                      'aggressive': True,
                      'contract': 'BTC/MXN',
                      'price': 60000000,
                      'quantity': 3000000,
                      'order': aggressive_order,
                      'other_order': passive_order,
                      'side': 'SELL',
                      'uid': uid,
                      'timestamp': timestamp}

        passive = {'username': 'passive_user',
                   'aggressive': False,
                   'contract': 'BTC/MXN',
                   'price': 60000000,
                   'quantity': 3000000,
                   'order': passive_order,
                   'other_order': aggressive_order,
                   'side': 'BUY',
                   'uid': uid,
                   'timestamp': timestamp}

        d1 = self.engine_export.post_transaction('aggressive_user', aggressive)
        d2 = self.engine_export.post_transaction('passive_user', passive)

        def onSuccess(result):
            # Inspect the positions
            BTC = self.session.query(models.Contract).filter_by(ticker='BTC').one()
            MXN = self.session.query(models.Contract).filter_by(ticker='MXN').one()
            aggressive_user_btc_position = self.session.query(models.Position).filter_by(username='aggressive_user',
                                                                                         contract=BTC).one()
            passive_user_btc_position = self.session.query(models.Position).filter_by(username='passive_user',
                                                                                      contract=BTC).one()
            aggressive_user_mxn_position = self.session.query(models.Position).filter_by(username='aggressive_user',
                                                                                         contract=MXN).one()
            passive_user_mxn_position = self.session.query(models.Position).filter_by(username='passive_user',
                                                                                      contract=MXN).one()

            # This is based on all BTC fees being zero
            self.assertEqual(aggressive_user_btc_position.position, 2000000)
            self.assertEqual(passive_user_btc_position.position, 400000000 + 3000000)

            # This is based on 100bps MXN fee charged to both sides (see test_sputnik.py)
            self.assertEqual(aggressive_user_mxn_position.position, round(1800000 * 0.99) + 500000)
            self.assertEqual(passive_user_mxn_position.position, round(3000000 - 1800000 * 1.01))

        dl = defer.DeferredList([d1, d2])
        dl.addCallback(onSuccess)
        return dl

    """
    # Not implemented yet
    def test_safe_prices(self):
        self.engine_export.safe_prices('BTC', 42)
        self.assertEqual(self.accountant.safe_prices['BTC'], 42)
    """


class TestWebserverExport(TestAccountant):
    def test_place_order(self):
        self.create_account("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.add_address("test", '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 'MXN')
        self.set_permissions_group("test", 'Deposit')
        self.cashier_export.deposit_cash('test', '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)
        # We should not need MXN to sell BTC for MXN
        # self.cashier_export.deposit_cash('test', '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)
        self.set_permissions_group("test", 'Trade')

        from sputnik import util
        import datetime
        # Place a sell order, we have enough cash
        id = self.webserver_export.place_order('test', {'username': 'test',
                                                        'contract': 'BTC/MXN',
                                                        'price': 1000000,
                                                        'quantity': 3000000,
                                                        'side': 'SELL',
                                                        'timestamp': util.dt_to_timestamp(datetime.datetime.utcnow())})

        from sputnik import models

        order = self.session.query(models.Order).filter_by(id=id).one()
        self.assertEqual(order.username, 'test')
        self.assertEqual(order.contract.ticker, 'BTC/MXN')
        self.assertEqual(order.price, 1000000)
        self.assertEqual(order.quantity, 3000000)
        self.assertEqual(order.side, 'SELL')

        # Check margin
        from sputnik import margin

        test = self.get_user('test')
        margin = margin.calculate_margin(test, self.session)
        self.assertEqual(margin[0], 3000000)
        self.assertEqual(margin[1], 3000000)
        from sputnik import engine2

        self.assertTrue(self.engines['BTC/MXN'].component.check_for_calls([('place_order',
                                                                            (engine2.Order(**{'contract': 5,
                                                                                              'id': 1,
                                                                                              'price': 1000000,
                                                                                              'quantity': 3000000,
                                                                                              'side': 1,
                                                                                              'username': u'test'}),),
                                                                            {})]))

    def test_place_order_prediction_expired(self):
        self.create_account("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.set_permissions_group("test", 'Deposit')
        self.cashier_export.deposit_cash("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)
        self.set_permissions_group("test", 'Trade')

        # Place a buy order, we have enough cash
        from sputnik import util
        import datetime

        with self.assertRaisesRegexp(AccountantException, 'contract_expired'):
            self.webserver_export.place_order('test', {'username': 'test',
                                                       'contract': 'NETS2014',
                                                       'price': 500,
                                                       'quantity': 3,
                                                       'side': 'BUY',
                                                       'timestamp': util.dt_to_timestamp(datetime.datetime.utcnow())})

    def test_place_order_prediction_buy(self):
        self.create_account("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.set_permissions_group("test", 'Deposit')
        self.cashier_export.deposit_cash("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)
        self.set_permissions_group("test", 'Trade')

        # Place a buy order, we have enough cash
        from sputnik import util
        import datetime

        id = self.webserver_export.place_order('test', {'username': 'test',
                                                        'contract': 'NETS2015',
                                                        'price': 500,
                                                        'quantity': 3,
                                                        'side': 'BUY',
                                                        'timestamp': util.dt_to_timestamp(datetime.datetime.utcnow())})

        from sputnik import models

        order = self.session.query(models.Order).filter_by(id=id).one()
        self.assertEqual(order.username, 'test')
        self.assertEqual(order.contract.ticker, 'NETS2015')
        self.assertEqual(order.price, 500)
        self.assertEqual(order.quantity, 3)
        self.assertEqual(order.side, 'BUY')
        from sputnik import engine2

        self.assertTrue(self.engines['NETS2015'].component.check_for_calls([('place_order',
                                                                             (engine2.Order(**{'contract': 8,
                                                                                               'id': 1,
                                                                                               'price': 500,
                                                                                               'quantity': 3,
                                                                                               'side': -1,
                                                                                               'username': u'test'}),),
                                                                             {})]))

        # Check to make sure margin is right
        from sputnik import margin

        test = self.get_user('test')

        [low_margin, high_margin, max_cash_spent] = margin.calculate_margin(test, self.session)
        # 200bps fee
        self.assertEqual(low_margin, 1500000 * 1.02)
        self.assertEqual(high_margin, 1500000 * 1.02)


    def test_place_order_prediction_sell(self):
        self.create_account("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.set_permissions_group("test", 'Deposit')
        self.cashier_export.deposit_cash("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)
        self.set_permissions_group("test", 'Trade')

        # Place a buy order, we have enough cash
        from sputnik import util
        import datetime

        id = self.webserver_export.place_order('test', {'username': 'test',
                                                        'contract': 'NETS2015',
                                                        'price': 100,
                                                        'quantity': 3,
                                                        'side': 'SELL',
                                                        'timestamp': util.dt_to_timestamp(datetime.datetime.utcnow())})

        from sputnik import models

        order = self.session.query(models.Order).filter_by(id=id).one()
        self.assertEqual(order.username, 'test')
        self.assertEqual(order.contract.ticker, 'NETS2015')
        self.assertEqual(order.price, 100)
        self.assertEqual(order.quantity, 3)
        self.assertEqual(order.side, 'SELL')

        from sputnik import engine2

        self.assertTrue(self.engines['NETS2015'].component.check_for_calls([('place_order',
                                                                             (engine2.Order(**{'contract': 8,
                                                                                               'id': 1,
                                                                                               'price': 100,
                                                                                               'quantity': 3,
                                                                                               'side': 1,
                                                                                               'username': u'test'}),),
                                                                             {})]))

        # Check to make sure margin is right
        from sputnik import margin

        test = self.get_user('test')
        [low_margin, high_margin, max_cash_spent] = margin.calculate_margin(test, self.session)
        # 200bps fee
        self.assertEqual(low_margin, 2700000 + 300000 * 0.02)
        self.assertEqual(high_margin, 2700000 + 300000 * 0.02)


    def test_place_order_no_perms(self):
        self.create_account("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.add_address("test", '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 'MXN')
        self.set_permissions_group("test", 'Deposit')
        self.cashier_export.deposit_cash("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)
        self.cashier_export.deposit_cash("test", '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)

        # Place a sell order, we have enough cash
        from sputnik import accountant
        from sputnik import util
        import datetime

        with self.assertRaisesRegexp(AccountantException, 'trade_not_permitted'):
            self.webserver_export.place_order('test', {'username': 'test',
                                                       'contract': 'BTC/MXN',
                                                       'price': 1000000,
                                                       'quantity': 3000000,
                                                       'side': 'SELL',
                                                       'timestamp': util.dt_to_timestamp(datetime.datetime.utcnow())})


    def test_place_order_no_cash(self):
        self.create_account("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.set_permissions_group("test", 'Trade')

        # Place a sell order, we have no cash
        from sputnik import accountant
        from sputnik import util
        import datetime

        with self.assertRaisesRegexp(AccountantException, 'insufficient_margin'):
            self.webserver_export.place_order('test', {'username': 'test',
                                                       'contract': 'BTC/MXN',
                                                       'price': 1000000,
                                                       'quantity': 3000000,
                                                       'side': 'SELL',
                                                       'timestamp': util.dt_to_timestamp(datetime.datetime.utcnow())})

    def test_place_order_little_cash(self):
        self.create_account("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.add_address("test", '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 'MXN')
        self.set_permissions_group("test", 'Deposit')
        self.cashier_export.deposit_cash("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)
        self.cashier_export.deposit_cash("test", '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)
        self.set_permissions_group("test", 'Trade')


        # Place a sell order, we have too little cash
        from sputnik import accountant
        from sputnik import util
        import datetime

        with self.assertRaisesRegexp(AccountantException, 'insufficient_margin'):
            result = self.webserver_export.place_order('test', {'username': 'test',
                                                                'contract': 'BTC/MXN',
                                                                'price': 1000000,
                                                                'quantity': 9000000,
                                                                'side': 'SELL',
                                                                'timestamp': util.dt_to_timestamp(
                                                                    datetime.datetime.utcnow())})


    def test_place_many_orders(self):
        self.create_account("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.add_address("test", '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 'MXN')
        self.set_permissions_group("test", 'Deposit')
        self.cashier_export.deposit_cash("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)
        # We should not need MXN to sell BTC for MXN
        # self.cashier_export.deposit_cash("test", '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)
        self.set_permissions_group("test", 'Trade')

        # Place a sell order, we have enough cash
        from sputnik import util
        import datetime

        id = self.webserver_export.place_order('test', {'username': 'test',
                                                        'contract': 'BTC/MXN',
                                                        'price': 1000000,
                                                        'quantity': 3000000,
                                                        'side': 'SELL',
                                                        'timestamp': util.dt_to_timestamp(datetime.datetime.utcnow())})

        from sputnik import models

        order = self.session.query(models.Order).filter_by(id=id).one()
        self.assertEqual(order.username, 'test')
        self.assertEqual(order.contract.ticker, 'BTC/MXN')
        self.assertEqual(order.price, 1000000)
        self.assertEqual(order.quantity, 3000000)
        self.assertEqual(order.side, 'SELL')
        from sputnik import engine2

        self.assertTrue(self.engines['BTC/MXN'].component.check_for_calls([('place_order',
                                                                            (engine2.Order(**{'contract': 5,
                                                                                              'id': 1,
                                                                                              'price': 1000000,
                                                                                              'quantity': 3000000,
                                                                                              'side': 1,
                                                                                              'username': u'test'}),),
                                                                            {})]))

        # Place another sell, we have insufficient cash now
        from sputnik import accountant
        from sputnik import util
        import datetime

        with self.assertRaisesRegexp(AccountantException, 'insufficient_margin'):
            self.webserver_export.place_order('test', {'username': 'test',
                                                       'contract': 'BTC/MXN',
                                                       'price': 1000000,
                                                       'quantity': 3000000,
                                                       'side': 'SELL',
                                                       'timestamp': util.dt_to_timestamp(
                                                           datetime.datetime.utcnow())})


    def test_cancel_order_success(self):
        self.create_account("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.add_address("test", '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 'MXN')
        self.set_permissions_group("test", 'Deposit')
        self.cashier_export.deposit_cash("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)
        self.cashier_export.deposit_cash("test", '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)
        self.set_permissions_group("test", 'Trade')

        # Place a sell order, we have enough cash
        from sputnik import util
        import datetime

        id = self.webserver_export.place_order('test', {'username': 'test',
                                                        'contract': 'BTC/MXN',
                                                        'price': 1000000,
                                                        'quantity': 3000000,
                                                        'side': 'SELL',
                                                        'timestamp': util.dt_to_timestamp(datetime.datetime.utcnow())})

        def cancelSuccess(result):
            self.assertEquals(result, None)

        def cancelFail(failure):
            self.assertTrue(False)

        d = self.webserver_export.cancel_order('test', id)
        d.addCallbacks(cancelSuccess, cancelFail)
        return d

    def test_cancel_order_wrong_user(self):
        self.create_account("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.add_address("test", '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 'MXN')
        self.set_permissions_group("test", 'Deposit')
        self.cashier_export.deposit_cash("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)
        self.cashier_export.deposit_cash("test", '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)
        self.set_permissions_group("test", 'Trade')

        # Place a sell order, we have enough cash
        from sputnik import util
        import datetime

        id = self.webserver_export.place_order('test', {'username': 'test',
                                                        'contract': 'BTC/MXN',
                                                        'price': 1000000,
                                                        'quantity': 3000000,
                                                        'side': 'SELL',
                                                        'timestamp': util.dt_to_timestamp(datetime.datetime.utcnow())})


        def cancelSuccess(result):
            self.assertTrue(False)

        def cancelFail(failure):
            self.assertTrue(False)

        from sputnik import accountant

        with self.assertRaisesRegexp(AccountantException, "user_order_mismatch"):
            d = self.webserver_export.cancel_order('wrong', id)
            d.addCallbacks(cancelSuccess, cancelFail)
            return d

    def test_cancel_order_no_order(self):
        self.create_account("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.add_address("test", '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 'MXN')
        self.set_permissions_group("test", 'Deposit')
        self.cashier_export.deposit_cash("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)
        self.cashier_export.deposit_cash("test", '28cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)
        self.set_permissions_group("test", 'Trade')

        def cancelSuccess(result):
            self.assertTrue(False)

        def cancelFail(failure):
            self.assertTrue(False)

        from sputnik import accountant

        id = 5
        with self.assertRaisesRegexp(AccountantException, "no_order_found"):
            d = self.webserver_export.cancel_order('wrong', id)
            d.addCallbacks(cancelSuccess, cancelFail)
            return d

    def test_request_withdrawal_success(self):
        self.create_account("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.set_permissions_group('test', 'Deposit')
        self.cashier_export.deposit_cash('test', '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)
        self.set_permissions_group('test', 'Withdraw')
        result = self.webserver_export.request_withdrawal('test', 'BTC', 3000000, 'bad_address')

        # Make sure it returns success
        self.assertTrue(self.successResultOf(result))

        # Check that the positions are changed
        from sputnik import models

        user_position = self.session.query(models.Position).filter_by(username='test').one()
        pending_position = self.session.query(models.Position).filter_by(username='pendingwithdrawal').one()

        self.assertEqual(user_position.position, 2000000)
        self.assertEqual(pending_position.position, 3000000)

        self.assertTrue(self.webserver.component.check_for_calls([('transaction',
                                                                   (u'onlinecash',
                                                                    {'contract': u'BTC',
                                                                     'quantity': 5000000,
                                                                     'direction': 'debit',
                                                                     'type': u'Deposit'}),
                                                                   {}),
                                                                  ('transaction',
                                                                   (u'test',
                                                                    {'contract': u'BTC',
                                                                     'direction': 'credit',
                                                                     'quantity': 5000000,
                                                                     'type': u'Deposit'}),
                                                                   {}),
                                                                  ('transaction',
                                                                   (u'pendingwithdrawal',
                                                                    {'contract': u'BTC',
                                                                     'direction': 'credit',
                                                                     'quantity': 3000000,
                                                                     'type': u'Withdrawal'}),
                                                                   {}),
                                                                  ('transaction',
                                                                   (u'test',
                                                                    {'contract': u'BTC',
                                                                     'direction': 'debit',
                                                                     'quantity': 3000000,
                                                                     'type': u'Withdrawal'}),
                                                                   {})]))
        self.assertTrue(
            self.cashier.component.check_for_calls(
                [('request_withdrawal', ('test', 'BTC', 'bad_address', 3000000), {})]))


    def test_request_withdrawal_no_perms(self):
        self.create_account("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')

        from sputnik import accountant

        with self.assertRaisesRegexp(AccountantException, "withdraw_not_permitted"):
            self.webserver_export.request_withdrawal('test', 'BTC', 3000000, 'bad_address')

        self.assertEqual(self.cashier.component.log, [])

    def test_request_withdrawal_no_margin_btc(self):
        self.create_account("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.set_permissions_group('test', 'Deposit')
        self.cashier_export.deposit_cash('test', '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)
        self.set_permissions_group('test', 'Withdraw')

        from sputnik import accountant

        with self.assertRaisesRegexp(AccountantException, "insufficient_margin"):
            self.webserver_export.request_withdrawal('test', 'BTC', 8000000, 'bad_address')

        self.assertEqual(self.cashier.component.log, [])

    def test_request_withdrawal_no_margin_fiat(self):
        self.create_account("test", '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv')
        self.set_permissions_group('test', 'Deposit')
        self.cashier_export.deposit_cash('test', '18cPi8tehBK7NYKfw3nNbPE4xTL8P8DJAv', 5000000)
        self.set_permissions_group('test', 'Withdraw')

        from sputnik import accountant

        with self.assertRaisesRegexp(AccountantException, "insufficient_margin"):
            self.webserver_export.request_withdrawal('test', 'MXN', 8000000, 'bad_address')

        self.assertEqual(self.cashier.component.log, [])

class TestRiskManagerExport(TestAccountant):
    def setUp(self):
        TestAccountant.setUp(self)

        self.create_account("test")
        self.user = self.get_user("test")

    def test_liquidate_best_prediction(self):
        self.create_position('BTC', 4000)
        self.create_position('USDBTC0W', 4, reference_price=4002)
        self.create_position('NETS2015', -4)
        self.accountant.safe_prices['USDBTC0W'] = 1202
        self.accountant.safe_prices['NETS2015'] = 500

        d = self.riskmanager_export.liquidate_best('test')
        def onLiquidated(id):
            from sputnik import models
            order = self.session.query(models.Order).filter_by(id=id).one()
            # Make sure we pick the NETS2015 contract
            self.assertEqual(order.contract.ticker, 'NETS2015')
            self.assertEqual(order.side, 'BUY')

        d.addCallback(onLiquidated)
        return d


    def test_liquidate_best_futures(self):
        self.create_position('BTC', 4000)
        self.create_position('USDBTC0W', -4, reference_price=1000)
        self.create_position('NETS2015', 1)
        self.accountant.safe_prices['USDBTC0W'] = 1202
        self.accountant.safe_prices['NETS2015'] = 500

        d = self.riskmanager_export.liquidate_best('test')
        def onLiquidated(id):
            from sputnik import models
            order = self.session.query(models.Order).filter_by(id=id).one()
            # Make sure we pick the USDBTC0W contract
            self.assertEqual(order.contract.ticker, 'USDBTC0W')
            self.assertEqual(order.side, 'BUY')

        d.addCallback(onLiquidated)
        return d


