'''
Run the tests using testrunner.py script in the project root directory.

Usage: testrunner.py SDK_PATH TEST_PATH
Run unit tests for App Engine apps.

SDK_PATH    Path to the SDK installation
TEST_PATH   Path to package containing test modules

Options:
  -h, --help  show this help message and exit

'''
import unittest
import webapp2
import os
import webtest
from google.appengine.ext import testbed

from mock import Mock
from mock import patch

import boilerplate
from boilerplate import models
from boilerplate import config as boilerplate_config
import config
import routes
from boilerplate import routes as boilerplate_routes
from boilerplate.lib import utils
from boilerplate.lib import captcha
from boilerplate.lib import i18n
from boilerplate.lib import test_helpers

from web.models import Translation, Content, Canon, BookStructure, ChapterStructure, Translation, BookTranslation, ChapterTranslation

# setting HTTP_HOST in extra_environ parameter for TestApp is not enough for taskqueue stub
os.environ['HTTP_HOST'] = 'localhost'

# globals
network = False

# mock Internet calls
if not network:
    i18n.get_territory_from_ip = Mock(return_value=None)


class AppTest(unittest.TestCase, test_helpers.HandlerHelpers):
    def setUp(self):

        # create a WSGI application.
        webapp2_config = boilerplate_config.config
        webapp2_config.update(config.config)
        self.app = webapp2.WSGIApplication(config=webapp2_config)
        routes.add_routes(self.app)
        boilerplate_routes.add_routes(self.app)
        self.testapp = webtest.TestApp(self.app, extra_environ={'REMOTE_ADDR': '127.0.0.1'})

        # use absolute path for templates
        self.app.config['webapp2_extras.jinja2']['template_path'] = [
            os.path.join(os.path.dirname(boilerplate.__file__), '../templates'),
            os.path.join(os.path.dirname(boilerplate.__file__), 'templates')]

        # activate GAE stubs
        self.testbed = testbed.Testbed()
        self.testbed.activate()
        self.testbed.init_datastore_v3_stub()
        self.testbed.init_memcache_stub()
        self.testbed.init_urlfetch_stub()
        self.testbed.init_taskqueue_stub()
        self.testbed.init_mail_stub()
        self.mail_stub = self.testbed.get_stub(testbed.MAIL_SERVICE_NAME)
        self.taskqueue_stub = self.testbed.get_stub(testbed.TASKQUEUE_SERVICE_NAME)
        self.testbed.init_user_stub()

        self.headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_7_4) Version/6.0 Safari/536.25',
                        'Accept-Language': 'en_US'}

        # fix configuration if this is still a raw boilerplate code - required by test with mails
        if not utils.is_email_valid(self.app.config.get('contact_sender')):
            self.app.config['contact_sender'] = "noreply-testapp@example.com"
        if not utils.is_email_valid(self.app.config.get('contact_recipient')):
            self.app.config['contact_recipient'] = "support-testapp@example.com"

    def tearDown(self):
        self.testbed.deactivate()

    def test_config_environment(self):
        self.assertEquals(self.app.config.get('environment'), 'testing')


class ModelTest(unittest.TestCase):
    def setUp(self):
        # activate GAE stubs
        self.testbed = testbed.Testbed()
        self.testbed.activate()
        self.testbed.init_datastore_v3_stub()
        self.testbed.init_memcache_stub()

    def tearDown(self):
        self.testbed.deactivate()

    def testCanon(self):
        #
        # test Canon.create
        #
        canon = Canon.create('TEST')
        self.assertIsNotNone(canon)
        # check if created and retrievable
        canon = Canon.make_key('TEST').get()
        self.assertIsNotNone(canon)

        #
        # test Canon.add_book
        #
        book1 = Canon.add_or_update_book('TEST', book_code='1tes', title='1 Testing', chapters=[ChapterStructure(num_of_verses=5), ChapterStructure(num_of_verses=3)])
        self.assertIsNotNone(book1)
        self.assertEqual(Canon.make_key('TEST').get().num_of_books, 1)

        # book should have canon as parent, and book id as key
        self.assertEqual(book1.key.parent(), canon.key)
        self.assertEqual(book1.key.string_id(), '1tes')

        book2 = Canon.add_or_update_book('TEST', book_code='2tes', title='2 Testing', chapters=[ChapterStructure(num_of_verses=5), ChapterStructure(num_of_verses=3), ChapterStructure(num_of_verses=4)])
        self.assertIsNotNone(book2)
        # book should have canon as parent, and book id as key
        self.assertEqual(book2.key.parent(), canon.key)
        self.assertEqual(book2.key.string_id(), '2tes')

        self.assertEqual(Canon.make_key('TEST').get().num_of_books, 2)
        self.assertEqual(BookStructure.query().count(1000), 2)

        #
        # test Canon.reset
        #
        Canon.reset('TEST')
        self.assertEqual(Canon.make_key('TEST').get().num_of_books, 0)
        self.assertEqual(BookStructure.query().count(1000), 0)

        #
        #  test Canon.build
        #
        Canon.build('TEST', [
            {'book_code':'gen',  'title':'Genesis', 'chapters':[2,3,4]},
            {'book_code':'1tes', 'title':'1 Testing', 'chapters':[5,6]},
            {'book_code':'2tes', 'title':'2 Testing', 'chapters':[7,8,9,10]},
        ])
        self.assertEqual(Canon.make_key('TEST').get().num_of_books, 3)
        self.assertEqual(BookStructure.query().count(1000), 3)

        book1 = BookStructure.make_key('TEST', 'gen').get()
        self.assertEqual(book1.num_of_chapters, 3)
        self.assertEqual(book1.get_chapter(1).num_of_verses, 2)
        self.assertEqual(book1.get_chapter(2).num_of_verses, 3)
        self.assertEqual(book1.get_chapter(3).num_of_verses, 4)

        book2 = BookStructure.make_key('TEST', '1tes').get()
        self.assertEqual(book2.num_of_chapters, 2)

        book3 = BookStructure.make_key('TEST', '2tes').get()
        self.assertEqual(book3.num_of_chapters, 4)


    def testTranslation(self):
        #
        # init
        #
        canon = Canon.create('TEST')

        #
        # Translation test
        #
        translation = Translation.create('TEST', 'en-TST', title='English Test')
        self.assertIsNotNone(translation)

        # check if created and retrievable
        translation = Translation.make_key('TEST', 'en-TST').get()
        self.assertIsNotNone(translation)

        #
        # Book Test
        #

        # test failed to add non-existant book
        book = Translation.add_or_update_book(translation.key, 'should-fail')
        self.assertIsNone(book) # should fail, book structure doesn't exist

        # test add book successfully
        book1 = Canon.add_or_update_book('TEST', book_code='1tes', title='1 Testing', chapters=[ChapterStructure(num_of_verses=5), ChapterStructure(num_of_verses=3)])
        book_translation = Translation.add_or_update_book(translation.key, '1tes')
        self.assertIsNotNone(book_translation)

        #
        # Translation build test
        #
        # build canon first
        Canon.build('TEST', [
            {'book_code':'gen',  'title':'Genesis', 'chapters':[2,3,4]},
            {'book_code':'1tes', 'title':'1 Testing', 'chapters':[5,6]},
            {'book_code':'2tes', 'title':'2 Testing', 'chapters':[7,8,9,10]},
        ])

        Translation.build(translation.key, translation_data={
            'title'     : 'translation title',
            'copyright' : 'translation copyright',
            'details' : {},
            'books' : [
                # array of books
                {
                    'book_code': 'gen',
                    'title': 'Genesis',
                    'lookup': ['gen'],
                    'details': {},
                    1: {
                        1: { 'text': 'In the beginning.', },
                        2: { 'text': 'And the earth was without form.', },
                    }

                }
            ]
        })

        chapter = ChapterTranslation.make_key(translation.key, 'gen', 1).get()
        self.assertIsNotNone(chapter)
        self.assertEqual(chapter.verses[1].text, 'In the beginning.')
        self.assertEqual(chapter.verses[2].text, 'And the earth was without form.')




if __name__ == "__main__":
    unittest.main()
