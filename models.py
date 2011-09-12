from mongoengine import *

import datetime
import hashlib
import urllib

class User(Document):
  email = StringField(required=True)
  name = StringField(max_length=200)
  date_modified = DateTimeField(default=datetime.datetime.now)

  @property
  def avatar(self):
    if not hasattr(self, '_avatar'):
      self._avatar = "http://www.gravatar.com/avatar.php?%s" % \
        urllib.urlencode({'gravatar_id': hashlib.md5(self.email.lower()).hexdigest(),
                          'size': '20'})
    return self._avatar


class Bookmark(Document):
  user = ReferenceField(User)
  url = StringField()
  url_digest = StringField()
  title = StringField()
  description = StringField()
  tags = ListField(StringField(max_length=60))
  modified = DateTimeField(default=datetime.datetime.now)

  def save(self, *args, **kwds):
    self.url_digest = hashlib.md5(self.url.encode('utf8')).hexdigest()
    return super(Bookmark, self).save(*args, **kwds)
