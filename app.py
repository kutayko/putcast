import sqlite3
import datetime
import json
import urllib
import urllib2
import string
import random

from functools import wraps
from contextlib import closing
from urlparse import urljoin
from flask import Flask, request, session, g, redirect, url_for, \
     abort, render_template, flash
from werkzeug.contrib.atom import AtomFeed

import config


app = Flask(__name__)
app.config.from_object('config')

SUPPORTED_AUDIO = ('audio/mpeg')
SUPPORTED_VIDEO = ('video/x-msvideo')
SUPPORTED_VIDEO_DIRECT = ('video/mp4')


# DATABASE RELATED


def connect_db():
    return sqlite3.connect(app.config['DATABASE'])


def init_db():
    with closing(connect_db()) as db:
        with app.open_resource('schema.sql') as f:
            db.cursor().executescript(f.read())
        db.commit()


@app.before_request
def before_request():
    g.db = connect_db()


@app.teardown_request
def teardown_request(exception):
    g.db.close()


def query_db(query, args=(), one=False):
    cur = g.db.execute(query, args)
    rv = [dict((cur.description[idx][0], value)
               for idx, value in enumerate(row)) for row in cur.fetchall()]
    return (rv[0] if rv else None) if one else rv


# AUTH CHECK DECORATOR
def auth_required(f):
    '''
    Use as decorator.
    Redirects to index if user is not logged in.
    '''

    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            session['oauth_token']
            return f(*args, **kwargs)
        except KeyError:
            return redirect(url_for('index'))
    return decorated


# ROUTES


@app.route('/', methods=['GET'])
def index():
    if "oauth_token" in session:
        return redirect(url_for('list_feeds'))
    else:
        return redirect(url_for('about'))


@app.route('/about')
def about():
    return render_template('index.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/auth', methods=['GET'])
def auth():
    url = "%s/oauth2/authenticate?client_id=%s" % (config.PUTIO_API_URL, config.APP_ID)
    url = "%s&response_type=code&redirect_uri=%s/register" % (url, config.DOMAIN)
    return redirect(url)


@app.route('/register', methods=['GET'])
def register():
    code = request.args.get('code')
    error = request.args.get('error')
    if error:
        return "ERROR: %s" % error
    elif code:
        url = "%s/oauth2/access_token?client_id=%s&client_secret=%s" % (config.PUTIO_API_URL,
                                                                        config.APP_ID,
                                                                        config.APP_SECRET)
        url = "%s&grant_type=authorization_code&redirect_uri=%s/register" % (url, config.DOMAIN )
        url = "%s&code=%s" % (url, code)

        req = urllib2.Request(url)
        response = urllib2.urlopen(req)
        data = json.loads(response.read())
        if 'access_token' in data:
            session['oauth_token'] = data['access_token']
            user = putio_call('/account/info')
            session['username'] = user['info']['username']
    return redirect(url_for('index'))


@app.route('/feed/create', methods=['POST'])
@auth_required
def new_feed():
    try:
        name = request.form['feed_name']
        items = request.form['items']
        audio = request.form.get('audio', False)
        types = request.form.getlist('types')
    except KeyError:
        abort(400)
    
    audio = False
    video = False
    if 'audio' in types:
        audio = True
    if 'video' in types:
        video = True

    feed_token = generate_feed_token()
    query_db('insert into feeds (user_token, feed_token, name, audio, video) values (?, ? ,?, ?, ?)',
                [session['oauth_token'], feed_token, name, audio, video])

    for item in items.split(','):
        query_db('insert into items (feed_token, folder_id) values (?, ?)',
                [feed_token, item])
    
    g.db.commit()
    return redirect(url_for('index'))


@app.route('/feed/delete', methods=['POST'])
@auth_required
def delete_feed():
    raise NotImplementedError


@app.route('/feeds', methods=['GET'])
@auth_required
def list_feeds():
    feeds = query_db('select * from feeds where user_token=?', [session['oauth_token']])
    response = []
    for feed in feeds:
        items = query_db('select * from items where feed_token=?', [feed['feed_token']])
        items_parsed = [item['folder_id'] for item in items]
        name_encoded = urllib.quote_plus(feed['name'])
        feed_response = {
            "name": feed['name'],
            "url": "%s/feed/%s/%s.atom" % (config.DOMAIN, feed['feed_token'], name_encoded),
            "audio": feed['audio'],
            "video": feed['video'],
            "items": json.dumps(items_parsed)
        }
        response.append(feed_response)
    return render_template('feeds.html',feeds=response)


@app.route('/feed/<feed_token>', methods=['GET'])
@app.route('/feed/<feed_token>/<name>.atom', methods=['GET'])
def get_feed(feed_token, name="putcast"):
    feed = query_db('select * from feeds where feed_token=?', [feed_token], one=True)
    if feed:
        # TODO: iTunes required fields
        atom_feed = AtomFeed(feed['name'],
                        feed_url=request.url,
                        url=request.host_url,
                        subtitle='PutCast - sync Put.io with iTunes')

        items = query_db('select * from items where feed_token=?', [feed_token])
        for item in items:
            feed_crawler(atom_feed, feed, item['folder_id'])
        return atom_feed.get_response()
    else:
        abort(404)


@app.route('/proxy/files/<int:parent_id>')
@auth_required
def putio_proxy(parent_id=0):
    return json.dumps(putio_call('/files/list?parent_id=%s' % parent_id))


# HELPERS


def feed_crawler(feed, db_feed, folder_id):
    audio = db_feed['audio']
    video = db_feed['video']
    token = db_feed['user_token']

    files = putio_call('/files/list?parent_id=%s' % folder_id, db_feed['user_token'])
    files = files['files']
    for f in files:
        if (audio and f['content_type'] in SUPPORTED_AUDIO) or \
                    (video and f['content_type'] in SUPPORTED_VIDEO_DIRECT):
            url = '%s/files/%s/download' % (config.PUTIO_API_URL, f['id'])
            #url = add_oauth_token(url, db_feed['user_token'])

            feed.add(
                title=f['name'],
                url=url,
                updated=datetime.datetime.strptime(f['created_at'], "%Y-%m-%dT%H:%M:%S")
            )

        if video and f['content_type'] in SUPPORTED_VIDEO:
            # TODO: Check if mp4 available
            url = '%s/files/%s/mp4/download' % (config.PUTIO_API_URL, f['id'])
            #url = add_oauth_token(url, db_feed['user_token'])

            feed.add(
                title=f['name'],
                url=url,
                updated=datetime.datetime.strptime(f['created_at'], "%Y-%m-%dT%H:%M:%S")
            )
        
        # TODO: mkv from content type?
        if video and f['name'].endswith(".mkv"):
            url = '%s/files/%s/mp4/download' % (config.PUTIO_API_URL, f['id'])
            #url = add_oauth_token(url, db_feed['user_token'])

            feed.add(
                title=f['name'],
                url=url,
                updated=datetime.datetime.strptime(f['created_at'], "%Y-%m-%dT%H:%M:%S")
            )

        if f['content_type'] == "application/x-directory":
            feed_crawler(feed, db_feed, f['id'])


def putio_call(query, token=None):
    url = "%s%s" % (config.PUTIO_API_URL, query)

    if token:
        pass
    elif 'oauth_token' in session:
        token = session['oauth_token']
    else:
        abort(401) 

    url = add_oauth_token(url, token)

    req = urllib2.Request(url)
    response = urllib2.urlopen(req)
    data = response.read()
    return json.loads(data)


def generate_feed_token():
    token =  ''.join(random.choice(string.ascii_letters + string.digits) for x in range(15))
    feed = query_db('select * from feeds where feed_token = ?', [token], one=True)
    if feed:
        return generate_feed_token()
    return token

def add_oauth_token(url, token):
    separator = "?"
    if "?" in url:
        separator = "&"
    url += "%soauth_token=%s" % (separator, token)
    return url

if __name__ == '__main__':
    app.debug = config.DEBUG
    #app.run(host="0.0.0.0", port=config.PORT)
    app.run()