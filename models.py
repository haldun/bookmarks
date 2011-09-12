from mongoengine import *
import datetime
import hashlib

class User(Document):
  email = StringField(required=True)
  name = StringField(max_length=200)
  date_modified = DateTimeField(default=datetime.datetime.now)

class Bookmark(Document):
  user = ReferenceField(User)
  url = StringField()
  url_digest = StringField()
  title = StringField()
  description = StringField()
  tags = ListField(StringField(max_length=60))
  date_modified = DateTimeField(default=datetime.datetime.now)

  def save(self, *args, **kwds):
    self.url_digest = hashlib.md5(self.url).hexdigest()
    return super(Bookmark, self).save(*args, **kwds)
