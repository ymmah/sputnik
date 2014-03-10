# Copyright (c) 2014, Mimetic Markets, Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# 1. Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
# IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
# TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
# PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED
# TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import sys
from pprint import pprint

from twisted.python import log
from twisted.internet import reactor, ssl

from autobahn.websocket import connectWS
from autobahn.wamp import WampClientFactory, WampCraClientProtocol
from datetime import datetime, timedelta

uri = 'ws://localhost:8000'
class TradingBot(WampCraClientProtocol):
    """
   Authenticated WAMP client using WAMP-Challenge-Response-Authentication ("WAMP-CRA").

   """

    def __init__(self):
        self.base_uri = self.getUri()
        self.markets = {}
        self.orders = {}
        self.last_internal_id = 0
        self.username = None

    def action(self):
        '''
        overwrite me
        '''
        return True

    def getUsernamePassword(self):
        return ['testuser1', 'testuser1']

    def getUri(self):
        return uri

    def startAutomation(self):
        pass

    """
    reactive events - on* 
    """

    def onSessionOpen(self):
        ## "authenticate" as anonymous
        ##
        #d = self.authenticate()
        self.getMarkets()
        self.subChat()
        ## authenticate as "foobar" with password "secret"
        ##
        [self.username, password] = self.getUsernamePassword()
        d = self.authenticate(authKey=self.username,
                              authExtra=None,
                              authSecret=password)

        d.addCallbacks(self.onAuthSuccess, self.onAuthError)

    def onClose(self, wasClean, code, reason):
        reactor.stop()

    def onAuthSuccess(self, permissions):
        print "Authentication Success!", permissions
        self.subOrders()
        self.subFills()
        self.getOpenOrders()

        self.startAutomation()


    def onAuthError(self, e):
        uri, desc, details = e.value.args
        print "Authentication Error!", uri, desc, details

    def onMarkets(self, event):
        pprint(event)
        self.markets = event[1]
        for ticker, contract in self.markets.iteritems():
            if contract['contract_type'] != "cash":
                self.subBook(ticker)
                self.subTrades(ticker)
                self.subSafePrices(ticker)
                self.getOHLCV(ticker)
        return event

    def onBook(self, topicUri, event):
        """
        overwrite me
        """
        pprint(["Book: ", topicUri, event])
        self.markets[event['contract']]['bids'] = event['bids']
        self.markets[event['contract']]['asks'] = event['asks']

    def onTrade(self, topicUri, event):
        """
        overwrite me
        """
        pprint(["Trade: ", topicUri, event])

    def onSafePrice(self, topicUri, event):
        """
        overwrite me
        """
        pprint(["SafePrice", topicUri, event])

    def onOpenOrders(self, event):
        pprint(event)
        self.orders = {}
        for id, order in event[1].iteritems():
            self.orders[int(id)] = order

    def onOrder(self, topicUri, order):
        """
        overwrite me
        """
        id = order['id']
        if id in self.orders and (order['is_cancelled'] or order['quantity_left'] == 0):
            del self.orders[id]
        else:
            # Try to find it in internal orders
            for search_id, search_order in self.orders.iteritems():
                if isinstance(search_id, basestring) and search_id.startswith('internal_'):
                    if (order['quantity'] == search_order['quantity'] and
                        order['side'] == search_order['side'] and
                        order['contract'] == search_order['contract'] and
                        order['price'] == search_order['price']):
                        del self.orders[search_id]
                        self.orders[id] = order

        pprint(["Order", topicUri, order])

    def onFill(self, topicUri, event):
        """
        overwrite me
        """
        pprint(["Fill", topicUri, event])

    def onChat(self, topicUri, event):
        pprint(["Chat", topicUri, event])

    def onPlaceOrder(self, event):
        pprint(event)

    def onOHLCV(self, event):
        pprint(event)

    def onRpcError(self, event):
        pprint(["RpcError", event.value.args])

    """
    Subscriptions
    """
    def subOrders(self):
        uri = "%s/feeds/orders#%s" % (self.base_uri, self.username)
        self.subscribe(uri, self.onOrder)
        print 'subscribed to: ', uri

    def subFills(self):
        uri = "%s/feeds/fills#%s" % (self.base_uri, self.username)
        self.subscribe(uri, self.onFill)
        print 'subscribed to: ', uri

    def subBook(self, ticker):
        uri = "%s/feeds/book#%s" % (self.base_uri, ticker)
        self.subscribe(uri, self.onBook)
        print 'subscribed to: ', uri

    def subTrades(self, ticker):
        uri = "%s/feeds/trades#%s" % (self.base_uri, ticker)
        self.subscribe(uri, self.onTrade)
        print 'subscribed to: ', uri

    def subSafePrices(self, ticker):
        uri = "%s/feeds/safe_prices#%s" % (self.base_uri, ticker)
        self.subscribe(uri, self.onSafePrice)
        print 'subscribed to: ', uri

    def subChat(self):
        uri = "%s/feeds/chat" % self.base_uri
        self.subscribe(uri, self.onChat)
        print 'subscribe to: ', uri

    """
    RPC calls
    """

    def getNewAddress(self):
        d = self.call(self.base_uri + "/rpc/get_new_address")
        d.addCallbacks(pprint, self.onRpcError)

    def getPositions(self):
        d = self.call(self.base_uri + "/rpc/get_positions")
        d.addCallbacks(pprint, self.onRpcError)

    def getMarkets(self):
        d = self.call(self.base_uri + "/rpc/get_markets")
        d.addCallbacks(self.onMarkets, self.onRpcError)

    def getOrderBook(self, ticker):
        d = self.call(self.base_uri + "/rpc/get_order_book", ticker)
        d.addCallbacks(pprint, self.onRpcError)

    def getOpenOrders(self):
        # store cache of open orders update asynchronously
        d = self.call(self.base_uri + "/rpc/get_open_orders")
        d.addCallbacks(self.onOpenOrders, self.onRpcError)

    def getOHLCV(self, ticker, period="day", start_datetime=datetime.now()-timedelta(days=2), end_datetime=datetime.now()):
        epoch = datetime.utcfromtimestamp(0)
        start_timestamp = int((start_datetime - epoch).total_seconds() * 1e6)
        end_timestamp = int((end_datetime - epoch).total_seconds() * 1e6)

        d = self.call(self.base_uri + "/rpc/get_ohlcv", ticker, period, start_timestamp, end_timestamp)
        d.addCallbacks(self.onOHLCV, self.onRpcError)

    def placeOrder(self, ticker, quantity, price, side):
        ord= {}
        ord['contract'] = ticker
        ord['quantity'] = quantity
        ord['price'] = price
        ord['side'] = side
        print "inside place order", ord
        print self.base_uri + "/rpc/place_order"
        d = self.call(self.base_uri + "/rpc/place_order", ord)
        d.addCallbacks(self.onPlaceOrder, self.onRpcError)

        self.last_internal_id += 1
        ord['quantity_left'] = ord['quantity']
        ord['is_cancelled'] = False
        self.orders['internal_%d' % self.last_internal_id] = ord

    def chat(self, message):
        print "chatting: ", message
        self.publish(self.base_uri + "/feeds/chat", message)

    def cancelOrder(self, id):
        """
        cancels an order by its id.
        :param id: order id
        """
        print "cancel order: %d" % id
        d = self.call(self.base_uri + "/rpc/cancel_order", id)
        d.addCallbacks(pprint, self.onRpcError)
        del self.orders[id]


if __name__ == '__main__':

    if len(sys.argv) > 1 and sys.argv[1] == 'debug':
        log.startLogging(sys.stdout)
        debug = True
    else:
        debug = False

    log.startLogging(sys.stdout)
    factory = WampClientFactory("ws://localhost:8000", debugWamp=debug)
    factory.protocol = TradingBot

    # null -> ....
    if factory.isSecure:
        contextFactory = ssl.ClientContextFactory()
    else:
        contextFactory = None

    connectWS(factory, contextFactory)
    reactor.run()
