import collections
import datetime
import hashlib
import urllib

from bson.dbref import DBRef
from mongoengine import *

class User(Document):
  email = StringField(required=True)
  name = StringField(max_length=200)
  date_modified = DateTimeField(default=datetime.datetime.now)

  meta = dict(
    indexes=['email']
  )

  @property
  def avatar(self):
    if not hasattr(self, '_avatar'):
      self._avatar = "http://www.gravatar.com/avatar.php?%s" % \
        urllib.urlencode({'gravatar_id': hashlib.md5(self.email.lower()).hexdigest(),
                          'size': '20'})
    return self._avatar

  def get_bookmark_by_url(self, url):
    url_digest = hashlib.md5(url.encode('utf8')).hexdigest()
    return Bookmark.objects.filter(user=self, url_digest=url_digest).first()

  def compute_tags(self):
    count = collections.defaultdict(int)
    tags = []
    for bookmark in Bookmark._get_collection().find({'user.$id': self._id}, fields=['tags']):
      if 'tags' not in bookmark:
        continue
      for tag in bookmark['tags']:
        count[tag] += 1

    for tag, count in count.items():
      tags.append({
        '_cls': 'Tag',
        "_types" : [
		      "Tag"
	      ],
	      "user" : DBRef('user', self._id),
	      'name': tag,
	      'count': count,
      })
    Tag._get_collection().remove({'user': DBRef('user', self._id)})
    Tag._get_collection().insert(tags)


class Bookmark(Document):
  user = ReferenceField(User)
  url = StringField()
  url_digest = StringField()
  title = StringField()
  description = StringField()
  tags = ListField(StringField(max_length=60))
  modified = DateTimeField(default=datetime.datetime.now)

  meta = dict(
    indexes=['user', 'url_digest', 'modified']
  )

  def save(self, *args, **kwds):
    self.url_digest = hashlib.md5(self.url.encode('utf8')).hexdigest()
    return super(Bookmark, self).save(*args, **kwds)


class Tag(Document):
  user = ReferenceField(User)
  name = StringField()
  count = IntField(default=0)

  meta = dict(
    indexes=['user']
  )
