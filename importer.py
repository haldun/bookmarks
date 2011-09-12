import datetime
from lxml import etree
import models

class Importer(object):
  def __init__(self, owner, contents):
    self.owner = owner
    self.contents = contents

  def import_bookmarks(self):
    root = etree.fromstring(self.contents, etree.HTMLParser())
    for link in root.xpath('//a'):
      url = link.attrib.get('href')
      if not url or not url.startswith('http'):
        continue
      title = link.text

      bookmark = models.Bookmark(user=self.owner, title=title, url=url)

      if 'add_date' in link.attrib:
        try:
          bookmark.modified = datetime.datetime.fromtimestamp(link.attrib['add_date'])
        except:
          pass

      if 'tags' in link.attrib:
        bookmark.tags = link.attrib['tags'].split(',')

      bookmark.save()
