#!/usr/bin/python

import logging
from collections import defaultdict

from twisted.internet import reactor
from twisted.internet.defer import Deferred
from twisted.protocols.policies import TimeoutMixin

from sqlalchemy.exc import SQLAlchemyError

from jsonschema import validate, ValidationError

import config
import database
from models import Posting, Journal, User, Contract
from zmq_util import router_share_async, export

class LedgerException(Exception):
    pass

ARGUMENT_ERROR = LedgerException(100, "Posting(s) cannot be decoded.")
UID_MISMATCH = LedgerException(101, "Batch postings must have the same UID.")
QUANTITY_MISMATCH = LedgerException(200, "Posting quantities do not balance.")
CONTRACT_MISMATCH = LedgerException(201, "Posting contracts do not match.")
TYPE_MISMATCH = LedgerException(202, "Posting types do not match.")
COUNT_MISMATCH = LedgerException(203, "Posting count is inconsistent.")
GROUP_TIMEOUT = LedgerException(300, "Timeout exceeded waiting for postings.")
INTERNAL_ERROR = LedgerException(998, "Invalid arguments supplied to commit.")
DATABASE_ERROR = LedgerException(999, "Database error.")

class PostingGroup(TimeoutMixin):
    def __init__(self, timeout=None):
        self.uid = None
        self.postings = []
        self.deferreds = []
        self.setTimeout(timeout)

    def add(self, posting):
        self.uid = posting["uid"]
        self.resetTimeout()
        result = Deferred()
        self.postings.append(posting)
        self.deferreds.append(result)
        return result

    def ready(self):
        # try to throw a COUNT_MISMATCH rather than a GROUP_TIMEOUT if the
        # counts are incorrect and we have postings coming in later
        max_count = max(posting["count"] for posting in self.postings)
        return len(self.postings) >= max_count

    def succeed(self):
        self.setTimeout(None)
        for deferred in self.deferreds:
            deferred.callback(True)

    def fail(self, exception):
        self.setTimeout(None)
        for deferred in self.deferreds:
            deferred.errback(exception)

    def timeoutConnection(self):
        logging.error("Posting group with uid: %s timed out." % self.uid)
        logging.error("Postings were:")
        for posting in self.postings:
            logging.error(str(posting))
        self.fail(GROUP_TIMEOUT)

class Ledger:
    def __init__(self, session, timeout=None):
        self.session = session
        self.pending = defaultdict(lambda: PostingGroup(timeout))

    def atomic_commit(self, postings):
        try:
            # sanity check
            if len(postings) == 0:
                raise INTERNAL_ERROR
            contracts = [posting["contract"] for posting in postings]
            types = [posting["type"] for posting in postings]
            counts = [posting["count"] for posting in postings]
            if not all(contract == contracts[0] for contract in contracts):
                raise CONTRACT_MISMATCH
            if not all(type == types[0] for type in types):
                raise TYPE_MISMATCH
            if not all(count == counts[0] for count in counts):
                raise COUNT_MISMATCH

            # balance check
            quantities = [posting["quantity"] for posting in postings]
            if sum(quantities) is not 0:
                raise QUANTITY_MISMATCH
            
            # create the journal and postings
            db_postings = []
            contract = self.session.query(Contract).filter_by(ticker=contracts[0]).one()
            for posting in postings:
                # TODO: change Posting contractor to take username
                user = self.session.query(User).filter_by(username=posting["user"]).one()
                quantity = posting["quantity"]
                side = posting["side"]
                db_postings.append(Posting(user, contract, quantity, side))
            journal = Journal(types[0], db_postings)

            # add all
            self.session.add_all(db_postings)
            self.session.add(journal)
            self.session.commit()
            return True

        except Exception, e:
            logging.error("Caught exception trying to commit. Postings were:")
            for posting in postings:
                logging.error(str(posting))
            logging.error("Stack trace follows:")
            logging.exception(e)
            if isinstance(e, SQLAlchemyError):
                raise DATABASE_ERROR
            raise e

        finally:
            # We have a long running session object, so we must make sure it
            # is clean at all times. If there is an exception in the exception
            # handler, session.rollback() might not get called. This way it is
            # guaranteed to happen.
            # 
            # This is safe to run after a commit.
            self.session.rollback()

    def post_one(self, posting):
        uid = posting["uid"]
        group = self.pending[uid]

        # acquire the deferred we will return
        response = group.add(posting)
        
        # Note: it is important we do _not_ check the posting group for
        # consistency yet. Wait until we have them all.

        if group.ready():
            try:
                self.atomic_commit(group.postings)
                group.succeed()
            except Exception, e:
                group.fail(e)
            del self.pending[uid]
       
        return response

    def post(self, postings):
        # an empty postings list might mean an error caller side
        # return ARGUMENT_ERROR
        if len(postings) == 0:
            logging.error("Received empty argument list.")
            raise ARGUMENT_ERROR

        # validate the posting
        try:
            validate(postings,
            {
                "type":"array",
                "items":
                {
                    "type":"object",
                    "required":True,
                    "properties":
                    {
                        "uid":{"type":"string", "required":True},
                        "count":{"type":"number", "required":True},
                        "type":{"type":"string", "required":True},
                        "user":{"type":"string", "required":True},
                        "contract":{"type":"string", "required":True},
                        "quantity":{"type":"number", "required":True},
                        "side":{"type":"string", "required":True}
                    }
                }
            })
        except ValidationError, e:
            logging.error("Received improperly formated posting(s):")
            logging.error(str(postings))
            logging.error("Exception follows:")
            logging.error(e)
            raise ARGUMENT_ERROR
      
        # make sure all the postings have the same uid
        uids = [posting["uid"] for posting in postings]
        if not all(uid == uids[0] for uid in uids):
            raise UID_MISMATCH
        
        # at this point, all posting will succeed or fail simulatenously
        # return the first one
        deferreds = [self.post_one(posting) for posting in postings]
        return deferreds[0]

class AccountantExport:
    def __init__(self, ledger):
        self.ledger = ledger

    def post(self, *postings):
        return self.ledger.post(list(postings))

if __name__ == "__main__":
    logging.basicConfig(format='%(asctime)s - %(levelname)s - %(funcName)s() %(lineno)d:\t %(message)s', level=logging.DEBUG)
    session = database.make_session()
    timeout = config.get("ledger", "accountant_export", None)
    ledger = Ledger(session, timeout)
    accountant_export = AccountantExport(ledger)
    router_share_async(accountant_export,
            config.get("ledger", "accountant_export"))
    reactor.run()
