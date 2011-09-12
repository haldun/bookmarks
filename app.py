# Python imports
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

# App imports
import forms
import importer
import models
import uimodules

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
    mongoengine.connect(self.config.mongodb_database)

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
  def get_current_user(self):
    user_id = self.get_secure_cookie('user_id')
    if not user_id:
      return None
    return models.User.objects(id=user_id).first()

  def render_string(self, template_name, **kwargs):
    if self.current_user is not None:
      tags = self.application.memcache.get('%s/tags' % self.current_user.id)
      if tags is None:
        tags = list(models.Tag.objects.filter(user=self.current_user) \
                                 .order_by('-count').limit(20))
        self.application.memcache.set('%s/tags' % self.current_user.id, tags)
    else:
      tags = []
    return tornado.web.RequestHandler.render_string(
        self, template_name, popular_tags=tags, IS_DEBUG=self.application.config.debug, **kwargs)


class IndexHandler(BaseHandler):
  def get(self):
    form = forms.HelloForm()
    self.render('index.html', form=form)

  def post(self):
    form = forms.HelloForm(self)
    if form.validate():
      self.write('Hello %s' % form.planet.data)
    else:
      self.render('index.html', form=form)


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

    user = models.User.objects(email=guser['email']).first()
    if user is None:
      user = models.User(email=guser['email'], name=guser['name'])
      user.save()
    self.set_secure_cookie('user_id', str(user.id))
    self.redirect(self.reverse_url('home'))


class LogoutHandler(BaseHandler):
  def get(self):
    self.clear_cookie('user_id')
    self.redirect(self.reverse_url('home'))


class HomeHandler(BaseHandler):
  @tornado.web.authenticated
  def get(self):
    # self.current_user.compute_tags()
    query = {'user.$id': self.current_user.id}

    tag = self.get_argument('tag', None)
    if tag is not None:
      query['tags'] = tag

    bookmarks = models.Bookmark._get_collection().find(
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
    importer.Importer(self.current_user, file['body']).import_bookmarks()
    self.redirect(self.reverse_url('home'))


class EditBookmarkHandler(BaseHandler):
  @tornado.web.authenticated
  def get(self, id):
    try:
      bookmark = models.Bookmark.objects.get(user=self.current_user, id=id)
    except models.Bookmark.DoesNotExist:
      raise tornado.web.HTTPError(404)
    form = forms.BookmarkForm(obj=bookmark)
    self.render('edit.html', form=form)

  @tornado.web.authenticated
  def post(self, id):
    try:
      bookmark = models.Bookmark.objects.get(user=self.current_user, id=id)
    except models.Bookmark.DoesNotExist:
      raise tornado.web.HTTPError(404)
    form = forms.BookmarkForm(self, obj=bookmark)
    if form.validate():
      form.populate_obj(bookmark)
      bookmark.save()
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
      bookmark = self.current_user.get_bookmark_by_url(form.url.data)
      if bookmark is None:
        bookmark = models.Bookmark(user=self.current_user)
      form.populate_obj(bookmark)
      bookmark.save()
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
      bookmark = self.current_user.get_bookmark_by_url(form.url.data)
      if bookmark is None:
        bookmark = models.Bookmark(user=self.current_user)
      form.populate_obj(bookmark)
      bookmark.save()
      self.write('oldu')
    else:
      self.write('%s' % form.errors)


class TagsHandler(BaseHandler):
  @tornado.web.authenticated
  def get(self):
    self.render('tags.html',
        tags=models.Tag.objects.filter(user=self.current_user).limit(50).order_by('-count'))


def main():
  tornado.options.parse_command_line()
  http_server = tornado.httpserver.HTTPServer(Application())
  http_server.listen(options.port)
  tornado.ioloop.IOLoop.instance().start()

if __name__ == '__main__':
  main()
