#!/usr/bin/python3

import sys
from tornado.ioloop import IOLoop, PeriodicCallback
from tornado import gen
from tornado.websocket import websocket_connect
from tornado.escape import json_encode


class Client(object):
	def __init__(self, url, timeout):
		self.url = url
		self.timeout = timeout
		self.ioloop = IOLoop.instance()
		self.ws = None
		self.connect()
		PeriodicCallback(self.keep_alive, 20000).start()
		self.ioloop.start()

	@gen.coroutine
	def connect(self):
		try:
			self.ws = yield websocket_connect(self.url)
		except Exception:
			print("connection error")
			raise
		else:
			print("connected to", self.url)
			self.run()

	@gen.coroutine
	def run(self):
		while True:
			usermsg = input("> ")
			usermsg = usermsg.strip()
			if usermsg == "quit":
				break
			elif usermsg in [ "next", "prev", "flush" ]:
				self.ws.write_message(json_encode({ "command" : usermsg }))
			else:
				print("Not understood.")
		self.ws.close()
		sys.exit()

	def keep_alive(self):
		if self.ws is None:
			self.connect()
		else:
			self.ws.write_message("keep alive")

if __name__ == "__main__":
	client = Client("ws://localhost:9000/controlsocket", 5)

# vim: ts=4 sw=4 noet
