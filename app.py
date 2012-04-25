import sqlite3
import datetime
import json
import urllib2
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


@app.route('/')
def index():
    url = "%s/oauth2/authenticate?client_id=%s" % (config.PUTIO_API_URL, config.APP_ID)
    url = "%s&response_type=code&redirect_uri=%s/register" % (url, config.DOMAIN)
    return redirect(url)

@app.route('/register')
def register():
    code = request.args.get('code')
    error = request.args.get('error')
    if error:
        return "ERROR: %s" % error
    elif code:
        url = "%s/oauth2/access_token" % config.PUTIO_API_URL
        url = "%s?client_id=%s&client_secret=%s" % (url, config.APP_ID, config.APP_SECRET)
        url = "%s&grant_type=authorization_code&redirect_uri=%s/register" % (url, config.DOMAIN )
        url = "%s&code=%s" % (url, code)

        try:
            req = urllib2.Request(url)
            response = urllib2.urlopen(req)
            data = json.dumps(response.read())
            return data.access_token
        except urllib2.URLError as e:
            return 'URLError'
    return redirect(url_for('index'))


@app.route('/feed/<token>/<name>.atom')
def get_feed(token, name="putcast"):
    # TODO: get selected items for user from db
    # TODO: POST /files/list with parent_id
    response = None

    # TODO: iTunes required fields
    feed = AtomFeed('Putio Tunes',
                    feed_url='some url', url='root_url')
    results = json.loads(response)
    for file in results['files']:
        if file['content_type'] == "audio/mpeg":
            feed.add(file['name'], None,
                        content_type=file['content_type'],
                        url='http://someurl.com/%s' % file['id'],
                        updated=file['created_at']
                    )
    return feed.get_response()

if __name__ == '__main__':
    app.run()