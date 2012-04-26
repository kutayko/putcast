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
            # TODO: user_id nerden geliyor?
            query_db('insert into users set id=?, token=?', [user_id, data['access_token']])
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
    
    token = generate_feed_token()
    query_db('insert into feeds set token=?, name=?, audio=?, video=?',
                [token, name, bool(audio), bool(video)])

    for item in items:
        query_db('insert into items set token=?, folder_id=?',
                [token, item])

    return redirect(url_for('index'))

@app.route('/feed/<token>/<name>.atom', methods=['GET'])
def get_feed(token, name="putcast"):
    items = query_db('select * from items where token=?', [token])
    for item in items:
        folder = putio_call('/files/list/%s' % item)

        # TODO: iTunes required fields
        feed = AtomFeed(name,
                        feed_url='some url', url='root_url')
        results = json.loads(folder)
        for file in results['files']:
            if file['content_type'] == "audio/mpeg":
                feed.add(file['name'], None,
                            content_type=file['content_type'],
                            url='http://someurl.com/%s' % file['id'],
                            updated=file['created_at']
                        )
    return feed.get_response()


def putio_call(query):
    url = "%s%s" % (config.PUTIO_API_URL, query)
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