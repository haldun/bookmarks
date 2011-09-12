import datetime
import hashlib
import logging
from lxml import etree
from pymongo.objectid import ObjectId
from bson.dbref import DBRef

class Importer(object):
  def __init__(self, db, owner, contents):
    self.db = db
    self.owner = owner
    self.contents = contents

  def import_bookmarks(self):
    collection = self.db.bookmarks
    url_digests = dict((b['url_digest'], b['_id'])
        for b in collection.find({'user': self.owner._id}, fields=['url_digest']))
    root = etree.fromstring(self.contents, etree.HTMLParser())
    bookmarks = list()

    for link in root.xpath('//a'):
      url = link.attrib.get('href')

      if not url or not url.startswith('http'):
        continue

      title = link.text
      url_digest = hashlib.md5(url.encode('utf8')).hexdigest()

      bookmark = {
	      "user" : self.owner._id,
	      'url': url,
	      'url_digest': url_digest,
	      'title': title or url,
      }

      if url_digest in url_digests:
        bookmark['_id'] = url_digests[url_digest]

      if 'add_date' in link.attrib:
        try:
          bookmark['modified'] = datetime.datetime.fromtimestamp(float(link.attrib['add_date']))
        except:
          pass

      if 'tags' in link.attrib:
        bookmark['tags'] = link.attrib['tags'].split(',')

      description_tag = link.getparent().getnext()
      if description_tag is not None and description_tag.tag == 'dd':
        bookmark['description'] = description_tag.text

      bookmarks.append(bookmark)

    if bookmarks:
      collection.insert(bookmarks)
