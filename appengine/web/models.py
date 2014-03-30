"""
"""
from __future__ import absolute_import
#import uuid
from webapp2 import cached_property
#from datetime import datetime

from google.appengine.ext import ndb # , blobstore
#from google.appengine.api import app_identity
#from apps.user.models import User
#from apps.program.models import Program

#from apps.base.template_helpers import url_for, abs_url_for
# from apps.base.rights import Right
# from apps.base.models import BaseModel
# from apps.attachment.models import Attachment
#
# from pytz.gae import pytz
# from apps.lib.utils import attr_setter, attr_getter, uuid36, uniqify, slugify#, shift_time # use uuid36 so it is emailable safely
# from string import lower
# from random import randint
#
# from google.appengine.api import search
# from apps.project.search import Search


def find(f, seq):
    """Return first item in sequence where f(item) == True."""
    for item in seq:
        if f(item):
            return item
    return None


#
# Bible structure
#

class BookHint(ndb.Model):
    """
        Book information
        The reason for book hint is mainly to reduce query:
        1. code : so I can verify if a book exists quickly
        2: num_of_chapters -> so I can display chapter selection easily from Canon later, without querying each book

        The reason why I don't store BookStructure directly:
        Book will have list of chapters, and each chapter will contain number of verses; it will also store pericope,
        I think it is too big to be stored as part of Canon
    """
    code = ndb.StringProperty()
    num_of_chapters = ndb.IntegerProperty(indexed=False)


class Canon(ndb.Model):
    # see https://en.wikipedia.org/wiki/Bible for the reasoning of the name
    # collection of books that form the bible
    # not separated by language / translation, but more on the canon type / structure
    # since different church/denomination may have different collection of books,
    # but when they got translated they have relatively same structure.
    #

    # meta data
    # key : should be a short code string to save on index, e.g: bible
    # note that this will be part of url & key for everything, and can not be changed later
    # try to make it not too long
    # we will need this to reconstruct the verse
    # NOTE: why not just use integer id ? i think short string will be easier if we ever need to update the data
    title = ndb.StringProperty()

    # add book hint to maintain book order / verify url quickly
    books = ndb.LocalStructuredProperty(BookHint, repeated=True)

    @property
    def code(self):
        return self.key.string_id()

    @classmethod
    def make_key(cls, canon_code):
        return ndb.Key(cls, canon_code)

    @classmethod
    def create(cls, canon_code, **kwargs):
        key = cls.make_key(canon_code)
        canon = cls(key=key, **kwargs)
        canon.put()
        return canon

    def get_hint(self, book_code):
        return find(lambda book: book.code == book_code, self.books)

    def get_book(self, book_code):
        # quick check
        if self.get_hint(book_code):
            return BookStructure.make_key(self.code, book_code).get()
        return None

    @classmethod
    def add_or_update_book(cls, canon_code, book_code, **kwargs):
        """
            Add a book to the cannon
        """
        #
        @ndb.transactional
        def txn(canon_code, book_code, **kwargs):
            canon_key = cls.make_key(canon_code)
            book = None
            canon = canon_key.get()

            if canon:
                book_codes = [book.code for book in canon.books]
                if book_code not in book_codes:
                    chapters = kwargs.get('chapters', [])

                    # add or update_hint
                    hint = canon.get_hint(book_code)
                    if hint:
                        hint.num_of_chapters = len(chapters)
                    else:
                        hint = BookHint(code=book_code, num_of_chapters=len(chapters))
                        canon.books.append(hint)

                    # add or update book
                    book_key = BookStructure.make_key(canon_code, book_code)
                    book = book_key.get()
                    if not book:
                        book = BookStructure(key=book_key)

                    # save all
                    for (k, v) in kwargs.iteritems():
                        if hasattr(book, k):
                            setattr(book, k, v)

                    ndb.put_multi([canon, book])
                else:
                    book = None

            return book

        return txn(canon_code, book_code, **kwargs)

    @classmethod
    def reset(cls, canon_code):
        """
            reset existing canon structure
        """
        canon_key = cls.make_key(canon_code)
        canon = canon_key.get()
        if canon:
            canon.books = []
            book_keys = []
            for book_key in BookStructure.query(ancestor=canon_key).iter(keys_only=True):
                book_keys.append(book_key)
            ndb.delete_multi(book_keys)
            canon.put()
        return canon


    @classmethod
    def build(cls, canon_code, canon_data):
        """
            build canon structure based on canon_data
            canon data should be array of array of num of verses
            e.g. [{
                    'book_code':'gen', # should make it all lowercase to be consistent
                    'title':'Genesis',
                    'chapters'=[31, 25, xxx]
                  },
                  {...}, ...
                ]

            will drop existing canon structure and rebuild from scratch
        """
        # first drop all existing books

        canon = cls.reset(canon_code)

        for book in canon_data:
            chapters = [ChapterStructure(num_of_verses=0)]
            for num_of_verses in book.get('chapters', []):
                chapters.append(ChapterStructure(num_of_verses=num_of_verses))
            book['chapters'] = chapters
            Canon.add_or_update_book(canon_code, **book)
        return canon

    @property
    def num_of_books(self):
        return len(self.books)



#
# FUTURE: pericope
#
class PericopeStructure(ndb.Model):
    """
        Data to store pericope information.
        A pericope usually span multiple verses, or even multiple chapter, but never across book
        pericope will be id-ed based on order in the book

    """
    # we don't have title for pericope itself, will be saved as part of translation, using Content

    # pericope start & end will be the encoded key of "%d%d"%(chapter, verse)
    start = ndb.StringProperty(indexed=False)
    end = ndb.StringProperty(indexed=False)


class ChapterStructure(ndb.Model):
    """
        Chapter information, not used to store any data, just chapter information
        # NOTE: Chapter is 1 based !, remember to factor that into calculation when we construct the url
        #       key will be based on actual chapter id
        #       chapter 0 will always be empty
    """
    num_of_verses = ndb.IntegerProperty(indexed=False)
    details = ndb.JsonProperty()


class BookStructure(ndb.Model):
    """
        Store the Book of the Bible / Canon structure ( chapters / verses )
        doesn't save any data related to the content itself (title, etc)

        # the reason for the Book data is to store other information related with book
        # such as book pericope, and additional details.
    """

    # meta  data
    # parent: canon
    # key: canonical code for this book. e.g: 'Gen' # note that case is important ! Gen != gen
    # note that this cannot be changed later; but I think it is ok
    # the slug will be part of url & key, and have to be unique for the canon
    # make sure it is short, recognizable (at least by the programmer)

    # canonical title - to make admin job & display easier
    # this is not tied to a specific translation, but for ease of use, we better use a standard naming
    # ex: genesis
    title = ndb.StringProperty(required=True)

    # number of verses in each chapter
    # NOTE: chapter number is 1 based, chapter 0 is always empty
    chapters = ndb.StructuredProperty(ChapterStructure, repeated=True)

    # additional details
    details = ndb.JsonProperty()

    @classmethod
    def make_key(cls, canon_code, book_code):
        canon_key = Canon.make_key(canon_code)
        return ndb.Key(cls, book_code, parent=canon_key)

    @property
    def num_of_chapters(self):
        num_of_chapters = len(self.chapters)
        return num_of_chapters - 1 if num_of_chapters > 0 else 0

    def get_chapter(self, chapter):
        num = self.num_of_chapters
        return self.chapters[chapter] if (chapter > 0) and (chapter <= num) else None

        # FUTURE: has_many pericope

        #
        # content / translation based
        #


# #
# # ISO Language
# # see https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes
# #
# class Language(ndb.Model):
#     # This will be used to group bible based on language later
#     pass

#
# Translation
#

class Content(ndb.Model):
    """
        the actual content of the translation, can be used as standalone or as part of others (ChapterTranslation)

        for standalone case:
            Parent will be Translation, grandparent will be Canon
            Key will be used to store the content id
            example:
                for verse:             V:Book.id:Chapter.id:Verse.id:
                for pericope title:    P:Book.id:Pericope.id:
        if this is used as part of other model, we don't need parent & key
    """
    text = ndb.TextProperty(indexed=False) # can be generic or markdown parsed
    details = ndb.JsonProperty() # to add additional detail to this content
    # FUTURE: we may be able to put a specific (not generic) translation footnotes / cross reference here

    @classmethod
    def make_key(cls, translation_key, content_type, book_code, chapter, verse):
        str_key = "%s:%s:%d:%d" % (content_type, book_code, chapter, verse)
        return ndb.Key(Content, str_key, parent=translation_key)

    @classmethod
    def add_or_update(cls, content_key, **kwargs):
        # get or update
        # construct key
        @ndb.transactional
        def txn(content_key, **kwargs):
            content = content_key.get()
            if not content:
                content = Content(key=content_key, **kwargs)
            for (k, v) in kwargs.iteritems():
                if hasattr(content, k):
                    setattr(content, k, v)
            content.put()
            return content

        return txn(content_key, **kwargs)


class ChapterTranslation(ndb.Model):
    """
        Store chapter translation
        To reduce query - we will store the translation per chapter instead of per verse
    """
    verses = ndb.LocalStructuredProperty(Content, repeated=True)
    details = ndb.JsonProperty() # to store additional details later

    @classmethod
    def make_key(cls, translation_key, book_code, chapter):
        str_key = "%s:%d" % (book_code, chapter)
        return ndb.Key(cls, str_key, parent=translation_key)

    @classmethod
    def build(cls, chapter_key, structure, chapter_data):
        chapter = chapter_key.get()
        if not chapter:
            chapter = ChapterTranslation(key=chapter_key)

        for (k, v) in chapter_data.iteritems():
            if isinstance(k, str):
                if hasattr(chapter, k):
                    setattr(chapter, k, v)
            elif isinstance(k, int): # if number, create / update verse
                if k <= structure.num_of_verses:
                    chapter.set_verse(k, v)
        chapter.put()

    def set_verse(self, verse_num, verse_data):
        if verse_num >= len(self.verses):
            self.verses.extend([Content()]*(verse_num + 1 - len(self.verses)))
        self.verses[verse_num] = Content(**verse_data)


class BookTranslation(ndb.Model):
    """
        Store book info
        This is not actual model, will be stored as StructuredProperty inside Translation
    """
    code = ndb.StringProperty(indexed=False)
    title = ndb.StringProperty(indexed=False) # the title of the book that will be displayed
    lookup = ndb.StringProperty(repeated=True,
                                indexed=False) # the short title that will be used for lookup, e.g. for Genesis: gn, gen
    details = ndb.JsonProperty() # to store additional details later


class Translation(ndb.Model):
    """
        Store the translation information, book name, book alias, copyright, etc
    """
    # meta data
    # parent is canon
    # key is short code to identify this translation, e.g. en-KJV
    # it is best to use ISO639 language code + '-' + translation name, just to be consistent
    # note that key can't be changed later, and key case is important !, e.g. en-KJV != en-kjv
    # this will be used as part of url, and key lookup, so don't make it too long

    # books has to be in the same order / number as Book structure in the Canon
    # books[0] will be empty
    # code -> will be stored as a key
    format = ndb.StringProperty(default=None) # format of the text, default to plain text, maybe we can add more later
    language = ndb.StringProperty() # ISO-639 language code

    title = ndb.StringProperty()
    short_names = ndb.StringProperty(indexed=True, repeated=True) # short names lookup, eg: Gen 1:1 (NIV)

    details = ndb.JsonProperty()
    copyright = ndb.StringProperty(indexed=False) # will be shown at the bottom of chapter

    books = ndb.LocalStructuredProperty(BookTranslation, repeated=True)

    @cached_property
    def canon(self):
        return self.key.parent().get()

    @classmethod
    def make_key(cls, canon_code, translation_code):
        canon_key = Canon.make_key(canon_code)
        return ndb.Key(Translation, translation_code, parent=canon_key)

    @classmethod
    def create(cls, canon_code, translation_code, **kwargs):
        """
        Add a transaction to a canon. Should follow the canon structure
        """
        key = cls.make_key(canon_code, translation_code)
        translation = cls(key=key, **kwargs)
        translation.put()
        return translation

    def get_book(self, book_code):
        return find(lambda book: book.code == book_code, self.books)

    @classmethod
    def add_or_update_book(cls, translation_key, book_code, **kwargs):
        """
            Add a book to the translation

        """

        @ndb.transactional
        def txn(translation_key, book_code, **kwargs):
            translation = translation_key.get()
            canon = translation.canon
            if canon and translation:
                hint = canon.get_hint(book_code)
                if hint is None:
                    return None # should add only if it available in the structure
                book = translation.get_book(book_code)
                if not book:
                    book = BookTranslation(code=book_code)
                for (k, v) in kwargs.iteritems():
                    if hasattr(book, k):
                        setattr(book, k, v)
                ndb.put_multi([translation])
            return translation

        return txn(translation_key, book_code, **kwargs)

    @classmethod
    def build(cls, translation_key, translation_data):
        """
            update translation content / books info on the translation_data
            this method will always updated based on this dict format
            translation_data = {
                'title' : 'translation title',              # optional, default to 'NOT SET'
                'copyright' : 'translation copyright',      # optional
                'details' : {},                             # optional
                'books' : [                                 # optional
                            # array of books
                            {
                                'book_code': 'gen',         # REQUIRED, must be sync with Canon Book Structure
                                'title': 'book title',      # optional
                                'lookup': ['bk', 'bok'],    # optional
                                'details': {},              # optional
                                1: {                        # Chapter: optional, can be skipped if you don't want to update anything
                                    1: {                    : Verse: optional
                                        text:'verse 1 content',
                                        details: {}
                                        },
                                    2: {
                                        text: 'verse 2 content'.
                                       },
                                    etc ...
                                },
                                etc ...
                            }
                          ]
            }

            subsequent call to update will only update specified data, i.e.  you can ignore details, etc
        """
        translation = translation_key.get()
        canon = translation_key.parent().get()

        if translation and canon:
            books_data = translation_data.pop('books', [])

            # update translation data
            for (k, v) in translation_data.iteritems():
                if hasattr(translation, k):
                    setattr(translation, k, v)

            # update books
            for book_data in books_data:
                # set regular attributes
                book_code = book_data.pop('book_code', None)
                book = translation.add_or_update_book(translation.key, book_code)
                book_structure = canon.get_book(book_code)
                if book and book_structure:
                    for (k, v) in book_data.iteritems():
                        if isinstance(k, str):
                            if hasattr(book, k):
                                setattr(book, k, v)
                        elif isinstance(k, int): # if number, create / update chapter
                            chapter_structure = book_structure.get_chapter(k)
                            if chapter_structure:
                                chapter_key = ChapterTranslation.make_key(translation_key, book_code, k)
                                ChapterTranslation.build(chapter_key, chapter_structure, v)
        return translation

#
# Commentary part
#

class Series(ndb.Model):
    # Series of commentary
    # To group them into one topic
    pass


class Commentary(ndb.Model):
    # Main commentary / article
    # Has title, author, etc
    # has_many segments
    # has_many tags
    pass


class Segment(ndb.Model):
    # segment of an commentary -> maybe a paragraph
    # the goal is to display segment when user browse commentary
    # updated whenever commentary is updated
    # has_many ref related only to this segment
    #   ref to verse    => Canon.id:Book.id:Chapter.id:Verse.id
    #   ref to chapter  => Canon.id:Book.id:Chapter.id
    #   FUTURE: ref to multiple verse => not sure how to store this, simplest way is to store it as multiple ref to verse
    #           we need to be careful if user abuse it and mark whole book, or big portion of the book
    #           in that case we may use combination of ref to verse & ref to chapter
    # has_many tags -> copied from commentary, so we can query it based on tags
    #       if commentary change the tags, we have to update this though. Seem like a small price though
    pass


#
# Segmentation
#
class TagTopic(ndb.Model):
    # can be used to define tagging topics : denomination, emotion, etc.
    # maybe can use same tagging technique as
    pass

#
# FUTURE: Bookmark
#
