from wtforms import *
from wtforms.validators import *

import wtforms.fields
import wtforms.widgets

from util import MultiValueDict

class BaseForm(Form):
  def __init__(self, handler=None, obj=None, prefix='', formdata=None, **kwargs):
    if handler:
      formdata = MultiValueDict()
      for name in handler.request.arguments.keys():
        formdata.setlist(name, handler.get_arguments(name))
    Form.__init__(self, formdata, obj=obj, prefix=prefix, **kwargs)

class TagListField(wtforms.fields.Field):
  widget = wtforms.widgets.TextInput()

  def _value(self):
    if self.data:
      return u', '.join(self.data)
    return u''

  def process_formdata(self, valuelist):
    if valuelist:
      self.data = list(set(x.strip().lower() for x in valuelist[0].strip().split(',')))
      self.data.sort()
    else:
      self.data = []


class HelloForm(BaseForm):
  planet = TextField('name', validators=[Required()])


class BookmarkForm(BaseForm):
  title = TextField('Title', [Required()])
  url = TextField('Url', [Required()])
  description = TextAreaField('Description')
  tags = TagListField('Tags')


class BookmarkletForm(BaseForm):
  title = TextField('Title')
  url = TextField('Url', [Required()])
  description = TextAreaField('Description')
  tags = TagListField('Tags')
