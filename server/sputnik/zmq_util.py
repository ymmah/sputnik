import inspect
import json
import logging
import zmq
import uuid
from txzmq import ZmqFactory, ZmqEndpoint
from txzmq import ZmqREQConnection, ZmqREPConnection
from txzmq import ZmqPullConnection, ZmqPushConnection
from twisted.internet.defer import Deferred, maybeDeferred
from functools import partial


logging.getLogger().setLevel(logging.DEBUG)


def export(obj):
    obj._exported = True
    return obj


class Export:
    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.mapper = {}
        for k in inspect.getmembers(wrapped.__class__, inspect.ismethod):
            if hasattr(k[1], "_exported"):
                self.mapper[k[0]] = k[1]

    def decode(self, message):
        logging.debug("Decoding message...")

        # deserialize
        try:
            request = json.loads(message)
        except:
            raise Exception("Invalid JSON received.")

        # extract method name and arguments
        method_name = request.get("method", None)
        args = request.get("args", [])
        kwargs = request.get("kwargs", {})

        # look up method
        method = self.mapper.get(method_name, None)
        if method_name is None:
            raise Exception("Method not found: %s" % method_name)

        # sanitize input
        if method_name == None:
            raise Exception("Missing method name.")
        if not isinstance(args, list):
            raise Exception("Arguments are not a list.")
        if not isinstance(kwargs, dict):
            raise Exception("Keyword arguments are not a dict.")
        
        return method_name, args, kwargs

    def encode(self, success, value):
        logging.debug("Encoding message...")

        # test to see if result serializes
        try:
            json.dumps(value)
        except:
            logging.warn("Message cannot be serialized. Converting to string.")
            value = str(value)
        
        if success:
            return json.dumps({"success":success, "result":value})
        return json.dumps({"success":success, "exception":value})

class AsyncExport(Export):
    def dispatch(self, method_name, args, kwargs):
        logging.info("Dispatching %s..." % method_name)
        logging.debug("method_name=%s, args=%s, kwars=%s" %
            (method_name, str(args), str(kwargs)))
        method = self.mapper[method_name]
        return maybeDeferred(method, self.wrapped, *args, **kwargs)

class SyncExport(Export):
    def dispatch(self, method_name, args, kwargs):
        logging.info("Dispatching %s..." % method_name)
        logging.debug("method_name=%s, args=%s, kwars=%s" %
            (method_name, str(args), str(kwargs)))
        method = self.mapper[method_name]
        return method(self.wrapped, *args, **kwargs)
 
class AsyncPullExport(AsyncExport):
    def __init__(self, wrapped, connection):
        AsyncExport.__init__(self, wrapped)
        self.connection = connection
        self.connection.onPull = self.onPull

    def onPull(self, message):
        try:
            # take the first part of the multipart message
            method_name, args, kwargs = self.decode(message[0])
        except Exception, e:
            return logging.warn("RPC Error: %s" % str(e))

        def result(value):
            logging.info("Got result for method %s." % method_name)

        def exception(failure):
            logging.warn("Caught exception in method %s." % method_name)
            logging.warn(failure)
        
        d = self.dispatch(method_name, args, kwargs)
        d.addCallbacks(result, exception)

class AsyncRouterExport(AsyncExport):
    def __init__(self, wrapped, connection):
        AsyncExport.__init__(self, wrapped)
        self.connection = connection
        self.connection.gotMessage = self.gotMessage

    def gotMessage(self, message_id, message):
        try:
            method_name, args, kwargs = self.decode(message)
        except Exception, e:
            logging.warn("RPC Error: %s" % message)
            return self.connection.reply(message_id, self.encode(False, str(e)))

        def result(value):
            logging.info("Got result for method %s." % method_name)
            self.connection.reply(message_id, self.encode(True, value))

        def exception(failure):
            logging.warn("Caught exception in method %s." % method_name)
            logging.warn(failure)
            self.connection.reply(message_id,
                self.encode(False, str(failure.value)))

        d = self.dispatch(method_name, args, kwargs)
        d.addCallbacks(result, exception)

class SyncPullExport(SyncExport):
    def __init__(self, wrapped, connection):
        SyncExport.__init__(self, wrapped)
        self.connection = connection

    def process(self, message):
        sender_id = message[0]
        message = message[1]
        try:
            # take the first part of the multipart message
            method_name, args, kwargs = self.decode(message)
        except Exception, e:
            return logging.warn("RPC Error: %s" % str(e))

        def result(value):
            logging.info("Got result for method %s." % method_name)

        def exception(failure):
            logging.warn("Caught exception in method %s." % method_name)
            logging.warn(failure)

        try:
            result(self.dispatch(method_name, args, kwargs))
        except Exception, e:
            exception(e)

class SyncRouterExport(SyncExport):
    def __init__(self, wrapped, connection):
        SyncExport.__init__(self, wrapped)
        self.connection = connection

    def process(self, message):
        sender_id = message[0]
        message_id = message[1]
        message = message[3]
        try:
            method_name, args, kwargs = self.decode(message)
        except Exception, e:
            logging.warn("RPC Error: %s" % message)
            return self.connection.send_multipart(
                [sender_id, message_id, "", self.encode(False, str(e))])

        def result(value):
            logging.info("Got result for method %s." % method_name)
            self.connection.send_multipart(
                [sender_id, message_id, "", self.encode(True, value)])

        def exception(failure):
            logging.warn("Caught exception in method %s." % method_name)
            logging.warn(failure)
            self.connection.send_multipart(
                [sender_id, message_id, "", self.encode(False, str(failure))])

        try:
            result(self.dispatch(method_name, args, kwargs))
        except Exception, e:
            exception(e)

 
def router_share_async(obj, address):
    socket = ZmqREPConnection(ZmqFactory(), ZmqEndpoint("bind", address))
    return AsyncRouterExport(obj, socket)

def pull_share_async(obj, address):
    socket = ZmqPullConnection(ZmqFactory(), ZmqEndpoint("bind", address))
    return AsyncPullExport(obj, socket)

def router_share_sync(obj, address):
    context = zmq.Context()
    socket = context.socket(zmq.ROUTER)
    socket.bind(address)
    sre = SyncRouterExport(obj, socket)
    while True:
        sre.process(socket.recv_multipart())

def pull_share_sync(obj, address):
    context = zmq.Context()
    socket = context.socket(zmq.ROUTER)
    socket.bind(address)
    spe = SyncPullExport(obj, socket)
    while True:
        spe.process(socket.recv_multipart())


class RemoteException(Exception):
    pass

class Proxy:
    def __init__(self, connection):
        self._connection = connection

    def decode(self, message):
        logging.debug("Decoding message...")

        # deserialize
        try:
            response = json.loads(message)
        except:
            raise Exception("Invalid JSON received.")

        # extract success and result
        success = response.get("success", None)
        if success == None:
            raise Exception("Missing success status.")
        
        if success:
            return success, response.get("result", None)
        return success, response.get("exception", None)

    def encode(self, method_name, args, kwargs):
        logging.debug("Encoding message...")

        return json.dumps({"method":method_name, "args":args, "kwargs":kwargs})

    def __getattr__(self, key):
        if key.startswith("__") and key.endswith("__"):
            raise AttributeError

        def remote_method(*args, **kwargs):
            message = self.encode(key, args, kwargs)
            d = self.send(message)

            def strip_multipart(message):
                return message[0]

            def parse_result(message):
                success, result = self.decode(message)
                if success:
                    return result
                raise RemoteException(result)
            
            if isinstance(d, Deferred):
                d.addCallback(strip_multipart)
                d.addCallback(parse_result)
            
            return d

        return remote_method

class DealerProxyAsync(Proxy):
    def send(self, message):
        return self._connection.sendMsg(message)
 
class PushProxyAsync(Proxy):
    def send(self, message):
        return self._connection.push(message) 

class DealerProxySync(Proxy):
    def send(self, message):
        self._id = str(uuid.uuid4())
        self._connection.send_multipart([self._id, "", message])
        data = self._connection.recv_multipart()
        if data[0] != self._id:
            raise Exception("Invalid return ID.")
        message = data[2]
        success, result = self.decode(message)
        if success:
            return result
        raise RemoteException(result)
 
class PushProxySync(Proxy):
    def send(self, message):
        self._connection.send(message) 
        return None

def dealer_proxy_async(address):
    socket = ZmqREQConnection(ZmqFactory(), ZmqEndpoint("connect", address))
    return DealerProxyAsync(socket)

def push_proxy_async(address):
    socket = ZmqPushConnection(ZmqFactory(), ZmqEndpoint("connect", address))
    return PushProxyAsync(socket)

def dealer_proxy_sync(address):
    context = zmq.Context()
    socket = context.socket(zmq.DEALER)
    socket.connect(address)
    return DealerProxySync(socket)

def push_proxy_sync(address):
    context = zmq.Context()
    socket = context.socket(zmq.PUSH)
    socket.connect(address)
    return PushProxySync(socket)

