import re
import yaml
from pkg_resources import resource_string

from twisted.trial.unittest import TestCase
from twisted.internet.defer import inlineCallbacks, returnValue

from vumi.application.base import SESSION_NEW, SESSION_CLOSE
from vumi.demos.decisiontree import (DecisionTreeWorker, TemplatedDecisionTree,
                                     PopulatedDecisionTree,
                                     TraversedDecisionTree)
from vumi.message import TransportUserMessage
from vumi.application.tests.test_base import ApplicationTestCase
from vumi.tests.utils import FakeRedis


class DecisionTreeTestCase(TestCase):

    def setUp(self):
        self.test_yaml = resource_string(__name__, "decision_tree_test.yaml")

    def test_session_decision_tree(self):
        dt1 = TemplatedDecisionTree()
        dt2 = PopulatedDecisionTree()
        dt3 = TraversedDecisionTree()
        # the new TraversedDecisionTree should not be completed
        self.assertFalse(dt3.is_completed())

        # just check the load operations don't blow up
        self.assertEquals(dt1.load_yaml_template(self.test_yaml), None)
        self.assertEquals(dt2.load_yaml_template(self.test_yaml), None)
        self.assertEquals(dt2.load_dummy_data(), None)
        self.assertEquals(dt3.load_yaml_template(self.test_yaml), None)
        self.assertEquals(dt3.load_dummy_data(), None)

        # simple backtracking test
        before = dt3.dumps()
        dt3.start()
        dt3.go_back()
        self.assertEquals(before, dt3.dumps())
        #dt3.set_language("swahili")

        # a fake interaction
        self.assertEquals(dt3.start(),
                'Hello.')
        self.assertEquals(dt3.question(),
                'Who are you?\n1. Simon\n2. David')
        dt3.answer(1)
        self.assertEquals(dt3.question(),
                'Which item?\n1. alpha\n2. beta')
        dt3.answer(1)
        self.assertEquals(dt3.question(),
                'How much stuff?')
        dt3.answer(42)
        self.assertEquals(dt3.question(),
                'How many things?')
        dt3.answer(23)
        dt3.go_up()
        self.assertEquals(dt3.question(),
                'Which item?\n1. alpha\n2. beta')
        dt3.answer(2)
        self.assertEquals(dt3.question(),
                'How much stuff?')
        dt3.answer(22)
        self.assertEquals(dt3.question(),
                'How many things?')
        dt3.answer(222)
        self.assertEquals(dt3.question(),
                'Which day was it?\n1. Today\n2. Yesterday\n3. An earlier day')
        dt3.answer(3)
        self.assertEquals(dt3.question(),
                'Which day was it [dd/mm/yyyy]?')
        dt3.answer("03/03/2011")
        self.assertEquals(dt3.finish(),
                'Thank you and goodbye.')


class TemplatedDecisionTreeTestCase(TestCase):
    """
    Tests for `TemplatedDecisionTree`.
    """

    def test_load_yaml_template_unsafe(self):
        """
        `load_yaml_template()` should not allow unsafe YAML tag execution.
        """
        dt = TemplatedDecisionTree()
        self.assertRaises(yaml.constructor.ConstructorError,
            lambda: dt.load_yaml_template('!!python/object/apply:int []'))
        # These attributes should not have been set.
        self.assertIdentical(dt.template, None)
        self.assertIdentical(dt.template_current, None)


class MockDecisionTreeWorker(DecisionTreeWorker):

    test_yaml = '''
        __data__:
            url: localhost:8080/api/get_data
            username: admin
            password: pass
            params:
                - telNo
            json: "{}"

        __start__:
            display:
                english: "Hello."
            next: users

        users:
            question:
                english: "Who are you?"
            options: name
            next: toys

        toys:
            question:
                english: "What kind of toys did you make?"
            options: name
            next: quantityMade

        quantityMade:
            question:
                english: "How many toys did you make?"
            validate: integer
            next: quantitySold

        quantitySold:
            question:
                english: "How many toys did you sell?"
            validate: integer
            next: recordTimestamp

        recordTimestamp:
            question:
                english: "When did this happen?"
            options:
                  - display:
                        english: "Today"
                    default: today
                    next: __finish__
                  - display:
                        english: "Yesterday"
                    default: yesterday
                    next: __finish__
                  - display:
                        english: "An earlier day"
                    next:
                        question:
                            english: "Which day was it [dd/mm/yyyy]?"
                        validate: date
                        next: __finish__

        __finish__:
            display:
                english: "Thank you! Your work was recorded successfully."

        __post__:
            url: localhost:8080/api/save_data
            username: admin
            password: pass
            params:
                - result
    '''

    def post_result(self, result):
        self.mock_result = result

    def call_for_json(self):
        return '''{
                    "users": [
                        {
                            "name":"David",
                            "toys": [
                                {
                                    "name":"truck",
                                    "quantityMade": 0,
                                    "recordTimestamp": 0,
                                    "toyId": "toy1",
                                    "quantitySold": 0
                                },
                                {
                                    "name": "car",
                                    "quantityMade": 0,
                                    "recordTimestamp": 0,
                                    "toyId": "toy2",
                                    "quantitySold": 0
                                }
                            ],
                            "userId": "user1"
                        },
                        {
                            "name":"Simon",
                            "userId": "user1"
                        }
                    ],
                    "msisdn": "456789"
                }'''


class TestDecisionTreeWorker(ApplicationTestCase):

    application_class = MockDecisionTreeWorker

    @inlineCallbacks
    def setUp(self):
        super(TestDecisionTreeWorker, self).setUp()
        self.worker = yield self.get_application({
            'worker_name': 'test_decision_tree_worker',
            })
        self.worker.r_server = FakeRedis()
        self.worker.session_manager.r_server = self.worker.r_server
        self.worker.set_yaml_template(self.worker.test_yaml)

    def tearDown(self):
        super(TestDecisionTreeWorker, self).tearDown()
        self.worker.r_server.teardown()

    def replace_timestamp(self, string):
        newstring = re.sub(r'imestamp": "\d*"',
                            'imestamp": "0"',
                            string)
        return newstring

    @inlineCallbacks
    def send(self, content, session_event=None, from_addr="456789"):
        msg = self.mkmsg_in(content, session_event=session_event,
                            from_addr=from_addr)
        yield self.dispatch(msg)

    @inlineCallbacks
    def recv(self, n=0):
        msgs = yield self.wait_for_dispatched_messages(n)

        def reply_code(msg):
            if msg['session_event'] == TransportUserMessage.SESSION_CLOSE:
                return 'end'
            return 'reply'

        returnValue([(reply_code(msg), msg['content']) for msg in msgs])

    @inlineCallbacks
    def test_session_new(self):
        yield self.send(None, TransportUserMessage.SESSION_NEW)
        [reply] = yield self.recv(1)
        self.assertEqual(reply[0], "reply")
        self.assertEqual(reply[1], "Who are you?\n1. David\n2. Simon")

    @inlineCallbacks
    def test_session_complete_menu_traversal(self):
        yield self.send(None, TransportUserMessage.SESSION_NEW)
        yield self.send("1", TransportUserMessage.SESSION_RESUME)
        yield self.send("1", TransportUserMessage.SESSION_RESUME)
        yield self.send("14", TransportUserMessage.SESSION_RESUME)
        yield self.send("10", TransportUserMessage.SESSION_RESUME)
        yield self.send("2", TransportUserMessage.SESSION_RESUME)
        replys = yield self.recv(1)
        self.assertEqual(len(replys), 6)
        self.assertEqual(replys[0][0], "reply")
        self.assertEqual(replys[0][1], "Who are you?\n1. David\n2. Simon")
        self.assertEqual(replys[1][0], "reply")
        self.assertEqual(replys[1][1], "What kind of toys did you make?"
                                    "\n1. truck\n2. car")
        self.assertEqual(replys[2][0], "reply")
        self.assertEqual(replys[2][1], "How many toys did you make?")
        self.assertEqual(replys[3][0], "reply")
        self.assertEqual(replys[3][1], "How many toys did you sell?")
        self.assertEqual(replys[4][0], "reply")
        self.assertEqual(replys[4][1], "When did this happen?"
                            + "\n1. Today\n2. Yesterday\n3. An earlier day")
        self.assertEqual(replys[5][0], "end")
        self.assertEqual(replys[5][1], "Thank you! Your work was"
                                    + " recorded successfully.")
        self.assertEqual(self.replace_timestamp(self.worker.mock_result),
                self.replace_timestamp(
                '{"msisdn": "456789", "users": '
                '[{"userId": "user1", "name": "David", '
                '"toys": [{"quantitySold": "10", "toyId": "toy1", '
                '"quantityMade": "14", "name": "truck", '
                '"recordTimestamp": "0"}, {"quantitySold": 0, '
                '"toyId": "toy2", "quantityMade": 0, "name": "car", '
                '"recordTimestamp": 0}]}, '
                '{"userId": "user1", "name": "Simon"}]}'
                ))

    @inlineCallbacks
    def test_session_complete_menu_traversal_with_bad_entries(self):
        # And strip the second user out of the retrieved data
        # to check that the first question is then skipped
        def call_for_json():
            return '''{
                        "users": [
                            {
                                "name":"David",
                                "toys": [
                                    {
                                        "name":"truck",
                                        "quantityMade": 0,
                                        "recordTimestamp": 0,
                                        "toyId": "toy1",
                                        "quantitySold": 0
                                    },
                                    {
                                        "name": "car",
                                        "quantityMade": 0,
                                        "recordTimestamp": 0,
                                        "toyId": "toy2",
                                        "quantitySold": 0
                                    }
                                ],
                                "userId": "user1"
                            }
                        ],
                        "msisdn": "456789"
                    }'''
        self.worker.call_for_json = call_for_json

        yield self.send(None, TransportUserMessage.SESSION_NEW)
        yield self.send("3", TransportUserMessage.SESSION_RESUME)
        # '3' was out of range, so repeat with '1'
        yield self.send("1", TransportUserMessage.SESSION_RESUME)
        yield self.send("14", TransportUserMessage.SESSION_RESUME)
        yield self.send("very little", TransportUserMessage.SESSION_RESUME)
        # 'very litte' was not an integer so repeat with '0.5'
        yield self.send("0.5", TransportUserMessage.SESSION_RESUME)
        # '0.5' is of course still not an integer so repeat with '0'
        yield self.send("0", TransportUserMessage.SESSION_RESUME)
        yield self.send("2", TransportUserMessage.SESSION_RESUME)
        replys = yield self.recv(1)
        self.assertEqual(len(replys), 8)
        self.assertEqual(replys[0][0], "reply")
        self.assertEqual(replys[0][1], "What kind of toys did you make?"
                                    "\n1. truck\n2. car")
        self.assertEqual(replys[1][0], "reply")
        self.assertEqual(replys[1][1], "What kind of toys did you make?"
                                    "\n1. truck\n2. car")
        self.assertEqual(replys[2][0], "reply")
        self.assertEqual(replys[2][1], "How many toys did you make?")
        self.assertEqual(replys[3][0], "reply")
        self.assertEqual(replys[3][1], "How many toys did you sell?")
        self.assertEqual(replys[4][0], "reply")
        self.assertEqual(replys[4][1], "How many toys did you sell?")
        self.assertEqual(replys[5][0], "reply")
        self.assertEqual(replys[5][1], "How many toys did you sell?")
        self.assertEqual(replys[6][0], "reply")
        self.assertEqual(replys[6][1], "When did this happen?"
                            + "\n1. Today\n2. Yesterday\n3. An earlier day")
        self.assertEqual(replys[7][0], "end")
        self.assertEqual(replys[7][1], "Thank you! Your work was"
                                    + " recorded successfully.")
        self.assertEqual(self.replace_timestamp(self.worker.mock_result),
                self.replace_timestamp(
                '{"msisdn": "456789", "users": '
                '[{"userId": "user1", "name": "David", '
                '"toys": [{"quantitySold": "0", "toyId": "toy1", '
                '"quantityMade": "14", "name": "truck", '
                '"recordTimestamp": "0"}, {"quantitySold": 0, '
                '"toyId": "toy2", "quantityMade": 0, "name": "car", '
                '"recordTimestamp": 0}]}]}'
                ))

    @inlineCallbacks
    def test_session_with_long_menus(self):
        # Replace the 'retrieved' data with many simple users
        def call_for_json():
            return '''{
                        "users": [
                            {"name":"Abrahem Smith"},
                            {"name":"Dominick Perez"},
                            {"name":"Hendrick Roux"},
                            {"name":"Jacoline Kennedy"},
                            {"name":"Kimberley Clarke"},
                            {"name":"Larry Suit"},
                            {"name":"Linda Lace"},
                            {"name":"Nkosazana Zuma"},
                            {"name":"Obama Perez"},
                            {"name":"Siphiwe Mbeki"},
                            {"name":"Thaba Zuma"},
                            {"name":"Thandiwe Mandela"}
                        ],
                        "msisdn": "456789"
                    }'''
        self.worker.call_for_json = call_for_json

        yield self.send(None, TransportUserMessage.SESSION_NEW)
        yield self.send("0", TransportUserMessage.SESSION_RESUME)
        replys = yield self.recv(1)
        self.assertEqual(len(replys), 2)
        self.assertTrue(len(replys[0][1]) <= 140)
        self.assertEqual(replys[0][0], "reply")
        self.assertEqual(replys[0][1], "Who are you?\n1. Abrahem Smith"
                "\n2. Dominick Perez\n3. Hendrick Roux\n4. Jacoline Kennedy"
                "\n5. Kimberley Clarke\n6. Larry Suit\n7. Linda Lace\n0. ...")
        self.assertTrue(len(replys[1][1]) <= 140)
        self.assertEqual(replys[1][0], "reply")
        self.assertEqual(replys[1][1], "Who are you?\n1. Nkosazana Zuma"
                "\n2. Obama Perez\n3. Siphiwe Mbeki\n4. Thaba Zuma"
                "\n5. Thandiwe Mandela")