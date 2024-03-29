# Python imports
import collections
import datetime
import logging
import os

# Tornado imports
import tornado.auth
import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web

from tornado.options import define, options
from tornado.web import url

import mongoengine
import pylibmc
import yaml
import pymongo

from pymongo.objectid import ObjectId

# App imports
import forms
import importer
import uimodules
import util

# Options
define("port", default=8888, type=int)
define("config_file", default="app_config.yml", help="app_config file")

class Application(tornado.web.Application):
  def __init__(self):
    handlers = [
      url(r'/', IndexHandler, name='index'),
      url(r'/auth/google', GoogleAuthHandler, name='auth_google'),
      url(r'/logout', LogoutHandler, name='logout'),
      url(r'/home', HomeHandler, name='home'),
      url(r'/import', ImportHandler, name='import'),
      url(r'/edit/(?P<id>\w+)', EditBookmarkHandler, name='edit'),
      url(r'/new', NewBookmarkHandler, name='new'),
      url(r'/b', BookmarkletHandler, name='bookmarklet'),
      url(r'/tags', TagsHandler, name='tags'),
      url(r'/delete_multi', DeleteMultipleBookmarksHandler, name='delete_multi'),
    ]
    settings = dict(
      debug=self.config.debug,
      login_url='/auth/google',
      static_path=os.path.join(os.path.dirname(__file__), "static"),
      template_path=os.path.join(os.path.dirname(__file__), 'templates'),
      xsrf_cookies=True,
      cookie_secret=self.config.cookie_secret,
      ui_modules=uimodules,
    )
    tornado.web.Application.__init__(self, handlers, **settings)
    self.connection = pymongo.Connection()
    self.db = self.connection[self.config.mongodb_database]
    # Create pymongo indexes
    self.db.users.ensure_index('email')
    self.db.bookmarks.ensure_index('user')
    self.db.bookmarks.ensure_index([('user', pymongo.DESCENDING),
                                    ('url_digest', pymongo.DESCENDING)])
    self.db.tags.ensure_index('user')

  @property
  def config(self):
    if not hasattr(self, '_config'):
      logging.debug("Loading app config")
      stream = file(options.config_file, 'r')
      self._config = tornado.web._O(yaml.load(stream))
    return self._config

  @property
  def memcache(self):
    if not hasattr(self, '_memcache'):
      self._memcache = pylibmc.Client(
        self.config.memcache_servers,
        binary=True, behaviors={"tcp_nodelay": True, "ketama": True})
    return self._memcache


class BaseHandler(tornado.web.RequestHandler):
  @property
  def db(self):
    return self.application.db

  def get_current_user(self):
    user_id = self.get_secure_cookie('user_id')
    if not user_id:
      return None
    user = self.db.users.find_one({'_id': pymongo.objectid.ObjectId(user_id)})
    if user is None:
      return None
    return tornado.web._O(user)

  def render_string(self, template_name, **kwargs):
    if self.current_user is not None:
      tags = self.application.memcache.get('%s/tags' % self.current_user['_id'])
      if tags is None:
        tags = list(self.db.tags.find({'user': self.current_user['_id']},
                                      sort=[('count', pymongo.DESCENDING)],
                                      limit=20))
        self.application.memcache.set('%s/tags' % self.current_user['_id'], tags)
    else:
      tags = []
    return tornado.web.RequestHandler.render_string(
        self, template_name, popular_tags=tags,
        IS_DEBUG=self.application.config.debug, **kwargs)


class IndexHandler(BaseHandler):
  def get(self):
    self.render('index.html')


class GoogleAuthHandler(BaseHandler, tornado.auth.GoogleMixin):
  @tornado.web.asynchronous
  def get(self):
    if self.get_argument('openid.mode', None):
      self.get_authenticated_user(self.async_callback(self._on_auth))
      return
    self.authenticate_redirect()

  def _on_auth(self, guser):
    if not guser:
      raise tornado.web.HTTPError(500, "Google auth failed")

    user = self.db.users.find_one({'email': guser['email']})

    if user is None:
      user = {
        'email': guser['email'],
        'name': guser['name'],
      }
      self.db.users.insert(user)
    self.set_secure_cookie('user_id', str(user['_id']))
    self.redirect(self.reverse_url('home'))


class LogoutHandler(BaseHandler):
  def get(self):
    self.clear_cookie('user_id')
    self.redirect(self.reverse_url('index'))


class HomeHandler(BaseHandler):
  @tornado.web.authenticated
  def get(self):
    compute_tags(self.db, self.current_user)
    query = {'user': self.current_user['_id']}

    tag = self.get_argument('tag', None)
    if tag is not None:
      query['tags'] = tag

    bookmarks = self.db.bookmarks.find(
        query,
        sort=[('modified', pymongo.DESCENDING)],
        skip=int(self.get_argument('offset', 0)),
        limit=25)
    self.render('home.html', bookmarks=(tornado.web._O(b) for b in bookmarks))


class ImportHandler(BaseHandler):
  @tornado.web.authenticated
  def get(self):
    self.render('import.html')

  @tornado.web.authenticated
  def post(self):
    file = self.request.files.get('file')[0]
    importer.Importer(self.db, self.current_user, file['body']).import_bookmarks()
    self.redirect(self.reverse_url('home'))


class EditBookmarkHandler(BaseHandler):
  @tornado.web.authenticated
  def get(self, id):
    bookmark = self.db.bookmarks.find_one(
      dict(user=ObjectId(self.current_user._id), _id=ObjectId(id)))
    if bookmark is None:
      raise tornado.web.HTTPError(404)
    form = forms.BookmarkForm(obj=tornado.web._O(bookmark))
    self.render('edit.html', form=form)

  @tornado.web.authenticated
  def post(self, id):
    bookmark = self.db.bookmarks.find_one(
      dict(user=ObjectId(self.current_user._id), _id=ObjectId(id)))
    if bookmark is None:
      raise tornado.web.HTTPError(404)
    bookmark = tornado.web._O(bookmark)
    form = forms.BookmarkForm(self, obj=bookmark)
    if form.validate():
      form.populate_obj(bookmark)
      self.db.bookmarks.save(bookmark)
      self.redirect(self.reverse_url('home'))
    else:
      self.render('edit.html', form=form)


class NewBookmarkHandler(BaseHandler):
  @tornado.web.authenticated
  def get(self):
    form = forms.BookmarkForm()
    self.render('new.html', form=form)

  @tornado.web.authenticated
  def post(self):
    form = forms.BookmarkForm(self)
    if form.validate():
      bookmark = self.db.bookmarks.find_one({
        'user': self.current_user._id, 'url': form.url.data})
      if bookmark is None:
        bookmark = dict(user=self.current_user._id,
                        modified=datetime.datetime.now())
      bookmark = tornado.web._O(bookmark)
      form.populate_obj(bookmark)
      self.db.bookmarks.insert(bookmark)
      self.redirect(self.reverse_url('home'))
    else:
      self.render('new.html', form=form)


class BookmarkletHandler(BaseHandler):
  @tornado.web.authenticated
  def get(self):
    form = forms.BookmarkletForm(self)
    if form.validate():
      if not form.title.data:
        form.title.data = form.url.data
      url_digest = util.md5(form.url.data)
      bookmark = self.db.bookmarks.find_one({
          'user': self.current_user._id,
          'url_digest': url_digest})
      if bookmark is None:
        bookmark = {'user': self.current_user._id,
                    'modified': datetime.datetime.now()}
      bookmark = tornado.web._O(bookmark)
      form.populate_obj(bookmark)
      self.db.bookmarks.save(bookmark)
      self.write('oldu')
    else:
      self.write('%s' % form.errors)


class TagsHandler(BaseHandler):
  @tornado.web.authenticated
  def get(self):
    tags = self.db.tags.find({'user': self.current_user._id},
                            sort=[('count', pymongo.DESCENDING)],
                            limit=20)
    self.render('tags.html', tags=(tornado.web._O(tag) for tag in tags))


class DeleteMultipleBookmarksHandler(BaseHandler):
  @tornado.web.authenticated
  def post(self):
    ids = [ObjectId(id) for id in self.get_arguments('ids[]')]
    bookmarks = self.db.bookmarks.remove({
      'user': self.current_user._id, '_id': {'$in': ids}})
    self.finish()


def compute_tags(db, user):
  count = collections.defaultdict(int)
  tags = []
  for bookmark in db.bookmarks.find({'user': user._id}, fields=['tags']):
    if 'tags' not in bookmark:
      continue
    for tag in bookmark['tags']:
      count[tag] += 1
  for tag, count in count.items():
    tags.append({
      "user" : user._id,
      'name': tag,
      'count': count,
    })
  db.tags.remove({'user': user._id})
  if tags:
    db.tags.insert(tags)

def main():
  tornado.options.parse_command_line()
  http_server = tornado.httpserver.HTTPServer(Application())
  http_server.listen(options.port)
  tornado.ioloop.IOLoop.instance().start()

if __name__ == '__main__':
  main()
