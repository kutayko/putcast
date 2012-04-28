import sqlite3
import datetime
import json
import urllib2
import string
import random

from contextlib import closing
from urlparse import urljoin
from flask import Flask, request, session, g, redirect, url_for, \
     abort, render_template, flash
from werkzeug.contrib.atom import AtomFeed

import config


app = Flask(__name__)
app.config.from_object('config')

SUPPORTED_AUDIO = ('audio/mpeg')
SUPPORTED_VIDEO = ('video/x-msvideo', 'application/octet-stream')
SUPPORTED_VIDEO_DIRECT = ('video/mp4')

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


@app.route('/', methods=['GET'])
def index():
    if "oauth_token" in session:
        response = putio_call('/account/info')
        return "Hello %s !!" % response['account']['username']
    else:
        return redirect(url_for('auth'))


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
        url = "/oauth2/access_token?client_id=%s&client_secret=%s" % (config.APP_ID, config.APP_SECRET)
        url = "%s&grant_type=authorization_code&redirect_uri=%s/register" % (url, config.DOMAIN )
        url = "%s&code=%s" % (url, code)

        data = putio_call(url)
        if 'access_token' in data:
            query_db('insert into users (token) values ("?")', [data['access_token']])
            session['oauth_token'] = data['access_token']
    return redirect(url_for('index'))

@app.route('/feed/create', methods=['POST'])
def new_feed():
    try:
        name = request.form['name']
        items = json.loads(request.form['items'])
        audio = request.form['audio']
        video = request.form['video']
    except KeyError:
        abort(400)
    
    feed_token = generate_feed_token()
    query_db('insert into feeds (user_token, feed_token, name, audio, video) values (?, ? ,?, ?, ?)',
                [session['oauth_token'], feed_token, name, bool(audio), bool(video)])

    for item in items:
        query_db('insert into items (feed_token, folder_id) values (?, ?)',
                [feed_token, item])

    return redirect(url_for('index'))

@app.route('/feed/delete', methods=['POST'])
def delete_feed():
    raise NotImplementedError

@app.route('/feed/<feed_token>', methods=['GET'])
@app.route('/feed/<feed_token>/<name>.atom', methods=['GET'])
def get_feed(feed_token, name="putcast"):
    feed = query_db('select * from Feeds where feed_token=?', [feed_token], one=True)
    if feed:
        # TODO: iTunes required fields
        atom_feed = AtomFeed(feed.name,
                        feed_url=request.url,
                        url=request.host_url,
                        subtitle='PutCast - sync Put.io with iTunes')

        items = query_db('select * from items where feed_token=?', [feed_token])
        for item in items:
            feed_crawler(atom_feed, item.folder_id, audio=feed.audio, video=feed.video)
        return atom_feed.get_response()
    else:
        abort(404)

@app.route('/feed/test', methods=['GET'])
def test_feed():
    feed = AtomFeed('PutCast',
                    feed_url='some url', url='root_url',
                    subtitle="referrer: %" % request.referrer)
    feed.add('Item name', "content",
                content_type="text",
                url='http://someurl.com/',
                updated=datetime.datetime.now()
            )
    return feed.get_response()

def feed_crawler(feed, folder_id, audio=True, video=True):
    files = putio_call('/files/list/%s' % item.folder_id)
    for f in files:
        if (audio and f['content_type'] in SUPPORTED_AUDIO) or \
                    (video and f['content_type'] in SUPPORTED_VIDEO_DIRECT):
                feed.add(title=f['name'],
                url='%s/files/%s/download' % (config.PUTIO_API_URL, f['id']),
                updated=datetime.datetime.strptime(f['created_at'], "%Y-%m-%dT%H:%M:%S")
            )

        if video and f['content_type'] in SUPPORTED_VIDEO:
            # TODO: Check if mp4 available
            feed.add(title=f['name'],
                url='%s/files/%s/mp4/download' % (config.PUTIO_API_URL, f['id']),
                updated=datetime.datetime.strptime(f['created_at'], "%Y-%m-%dT%H:%M:%S")
            )
        
        if f['content_type'] == "application/x-directory":
            feed_crawler(feed, f['id'], audio, video)

def putio_call(query):
    url = "%s%s" % (config.PUTIO_API_URL, query)
    if 'oauth_token' in session:
        url += "?oauth_token=%s" % session['oauth_token']
    req = urllib2.Request(url)
    response = urllib2.urlopen(req)
    data = response.read()
    return json.loads(data)

def generate_feed_token():
    token =  ''.join(random.choice(string.ascii_letters + string.digits) for x in range(15))
    feed = query_db('select * from feeds where hash = ?', [token], one=True)
    if feed:
        return generate_feed_token()
    return token

if __name__ == '__main__':
    app.run()