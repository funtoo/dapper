#!/usr/bin/python3

import tornado.httpclient
from tornado.escape import json_encode
import os
import sys

tracks = []
for track in sys.argv[1:]:
    if os.path.exists(track):
        tracks.append(os.path.normpath(os.path.abspath(track)))

c = tornado.httpclient.HTTPClient()
url = 'http://localhost:9000/control'
h = { "Content-Type": "application/json", "Accept": "application/json" }
data = { "command" : "queue", "tracks" : tracks }
r = tornado.httpclient.HTTPRequest(method="POST", headers=h, url=url, body=json_encode(data))
try:
    response = c.fetch(r)
except tornado.httpclient.HTTPError as e:
    print("Error: " + str(e))
except Exception as e:
    print("Error: " + str(e))
c.close()
