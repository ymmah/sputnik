from Crypto import Random
import hashlib
import datetime

__author__ = 'satosushi'

import json
import treq

import logging

from jsonschema import validate
from Crypto.Cipher import AES

class Charge:
    def __init__(self,
                 product_price,
                 customer_name,
                 customer_email,
                 customer_phone,
                 payment_type,
                 send_sms=False,
                 currency='MXN',
                 product_name='MEXBT',
                 product_id='MXN',
                 image_url='http://www.sputnik.com/BC_Logo_.png'):
        self.product_price, self.currency = product_price, currency
        self.customer_name, self.customer_email, self.customer_phone = customer_name, customer_email, customer_phone
        self.payment_type, self.send_sms = payment_type, send_sms
        self.product_name, self.product_id = product_name, product_id
        self.image_url = image_url

    def json(self):
        return json.dumps({k:v for (k,v) in self.__dict__.iteritems() if v})

    @staticmethod
    def from_dict(x):
        return Charge(x['product_price'], x['customer_name'], x['customer_email'], x['customer_phone'],
                      x['payment_type'], x['send_sms'], x['currency'], x['product_name'], x['product_id'],
                      x['image_url'])



class Compropago:
    def make_public_handle(self, username):
        iv = Random.new().read(AES.block_size)
        return (iv + AES.new(self.aes_key, AES.MODE_CBC, iv).encrypt(self.pad(username))).encode('hex')

    def parse_public_handle(self, public_handle):
        cipher = public_handle.decode('hex')
        return self.unpad(
            AES.new(self.aes_key, AES.MODE_CBC, cipher[:AES.block_size]).decrypt(cipher[AES.block_size:]))

    base_URL = 'http://api.compropago.com'
    charge_URL = base_URL + '/v1/charges'
    headers = {'Accept': 'application/compropago+json',
               'Content-Type': 'application/json'}

    def __init__(self, key):
        self.key = key
        self.aes_key = hashlib.sha256('midly secret').digest()
        self.pad = lambda s: s + (AES.block_size - len(s) % AES.block_size) * chr(AES.block_size - len(s) % AES.block_size)
        self.unpad = lambda s: s[0:-ord(s[-1])]

    def parse_existing_bill(self, bill):
        validate(bill,
            {
                "type": "object",
                "required": True,
                "properties":
                {
                    "data":
                    {
                        "type": "object",
                        "required": True,
                        "properties":
                        {
                            "object":
                            {
                                "type": "object",
                                "required": True,
                                "properties":
                                {
                                    "id": {"type":"string", "required":True},
                                    "paid": {"type":"boolean", "required":True},
                                    "amount": {"type":"string", "required":True}
                                }
                            }
                        }
                    }
                }
            })
        bill = bill["data"]["object"]
        return {"id": bill["id"].encode("utf-8"), "payment_id": bill["id"].encode("utf-8"), "paid": bool(bill["paid"]), "amount": float(bill["amount"])}

    def parse_new_bill(self, bill):
        validate(bill,
        {
            "type": "object",
            "required": True,
            "properties":
            {
                "payment_id": {"type":"string", "required":True},
                "payment_instructions":
                {
                    "type": "object",
                    "required": True,
                    "properties":
                    {
                        "description": {"type":"string", "required":True},
                        "note_confirmation": {"type":"string", "required":True},
                        "note_expiration_date": {"type":"string", "required":True},
                        "step_1": {"type":"string", "required":True},
                        "step_2": {"type":"string", "required":True},
                        "step_3": {"type":"string", "required":True}
                    }
                }
            }
        })
        return {"id": bill["payment_id"].encode("utf-8"), "payment_id":bill["payment_id"].encode("utf-8"), "payment_instructions":bill["payment_instructions"]}

    def create_bill(self, charge):
        charge.customer_name = self.make_public_handle(charge.customer_name)
        d = treq.post(self.charge_URL,
                      data=charge.json(),
                      headers=self.headers, auth=(self.key, ''),
                      timeout=5)

        def handle_response(response):
            def parse_content(content):
                if response.code != 200:
                    # this should happen sufficiently rarely enough that it is
                    # worth logging here in addition to the failure
                    logging.warn("Received code: %s from Compropago for charge: %s. Content follows: %s" % (response.code, str(charge), content))
                    raise Exception("Compropago returned code: %s." % response.code)
                else:
                    # TODO: Once we are sure what Compropago returns,
                    # remove this spam
                    logging.info("Received 200 OK from Compropago. Charge: %s. Content follows: %s" % (str(charge), content))
                    # if the JSON cannot be decoded, let the error float up
                    cgo_bill = json.loads(content)
                    if "type" in cgo_bill and cgo_bill["type"] == "error":
                        raise Exception("Compropago error: %s" % str(cgo_bill))
                    return cgo_bill
            return response.content().addCallback(parse_content)

        # if there is a timeout or other network error, let it float up
        d.addCallback(handle_response)

        # if there is a timeout of other network error, let it float up
        d.addCallback(handle_response)

        # filter chain for successful method call follows
        d.addCallback(self.parse_new_bill)

        # Do not add any errbacks _HERE_, let the caller do that.

        return d

    def get_bill(self, payment_id):
        d = treq.get(self.charge_URL + '/' + payment_id, auth=(self.key, ''),
                     timeout=5)

        def handle_response(response):
            def parse_content(content):
                if response.code != 200:
                    # this should happen sufficiently rarely enough that it is
                    # worth logging here in addition to the failure
                    logging.warn("Received code: %s from Compropago for bill: %s. Content follows: %s" % (response.code, payment_id, content))
                    raise Exception("Compropago returned code: %s." % response.code)
                else:
                    # TODO: Once we are sure what Compropago returns,
                    # remove this spam
                    logging.info("Received 200 OK from Compropago. Bill: %s. Content follows: %s" % (payment_id, content))
                    # if the JSON cannot be decoded, let the error float up
                    cgo_bill = json.loads(content)
                    if "type" in cgo_bill and cgo_bill["type"] == "error":
                        raise Exception("Compropago error: %s" % str(cgo_bill))
                    return cgo_bill
            return response.content().addCallback(parse_content)

        # if there is a timeout or other network error, let it float up
        d.addCallback(handle_response)

        # filter chain for successful method call follows
        d.addCallback(self.parse_existing_bill)

        # Do not add any errbacks _HERE_, let the caller do that.

        return d

    def get_all(self):
        d = treq.get(self.charge_URL, auth=(self.key, ''))
        return d.addCallback(treq.json_content)

    def validate_response(self, payment_info):
        t = lambda x: dict(type=x, required=True)
        validate(payment_info, {
            'type': 'object',
            'required': True,

                                        'properties': {
                                            'id': t('string'),
                                            'object': t('string'),
                                            'created_at': t('string'),
                                            'paid': t('boolean'),
                                            'amount': t('string'),
                                            'currency': t('string'),
                                            'refunded': t('boolean'),
                                            'fee': t('string'),
                                            'fee_details': {'type': 'object', 'required': True,
                                                            'properties': {
                                                                'amount': t('string'),
                                                                'currency': t('string'),
                                                                'type': t('string'),
                                                                'description': t('string'),
                                                                'application': {'type': ['string', 'null'], 'required': True},
                                                                'amount_refunded': t('number')
                                                            }
                                            },
                                            'payment_details': {'type': 'object', 'required': True,
                                                                'properties': {
                                                                    'object': t('string'),
                                                                    'store': t('string'),
                                                                    'country': t('string'),
                                                                    'product_id': t('string'),
                                                                    'product_price': t('string'),
                                                                    'product_name': t('string'),
                                                                    'image_url': t('string'),
                                                                    'success_url': t('string'),
                                                                    'customer_name': t('string'),
                                                                    'customer_email': t('string'),
                                                                    'customer_phone': t('string')
                                                                }
                                            },
                                            'captured': t('boolean'),
                                            'failure_message': {'type': ['string', 'null'], 'required': True},
                                            'failure_code': {'type': ['string', 'null'], 'required': True},
                                            'amount_refunded': t('number'),
                                            'description': t('string'),
                                            'dispute': {'type': ['string', 'null'], 'required': True}
                                        }})
        return payment_info


def main():
    abtest = Compropago('sk_test_5b82f569d4833add')
    d = abtest.get_bill("78b0bf0a-1f5e-4c00-b2e8-d29df8af8765")
    def foo(x):
        print x
    d.addCallback(abtest.parse_bill)
    d.addCallback(foo)
#    bill = abtest.create_bill(Charge(11000, 'Satoshi Nakamoto', 'satoshi@bitcoin.it', '2221515801', 'OXXO'))
#    print bill
#    status = abtest.get_bill(bill['payment_id'])
#    print status
#    abtest.validate_response(status)
#    print abtest.get_all()

# 'sk_test_5b82f569d4833add'
if __name__ == '__main__':
    from twisted.internet import reactor
    main()
    reactor.run()
