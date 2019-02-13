#!/usr/bin/python3

# dapper: the digital audio playback platform.
# Copyright 2017 Daniel Robbins (drobbins@funtoo.org)
#
# This program is free software; you can redistribute and/or modify it under the
# terms of the Mozilla Public License version 2, or alternatively (at your
# option) the GNU General Public License version 2 or later.

import os, socket, sys, random, string

from tornado.tcpserver import TCPServer
from tornado.ioloop import IOLoop
from tornado.process import Subprocess
from tornado.escape import json_decode

import tornado.web
import tornado.websocket
from tornado.gen import coroutine, sleep
import tornado.httpserver
import time

# if your DAC doesn't decode PCM DOP streams back into native DSD, set this to False, and then DSD files will be converted on the fly to native 192KHz/24bit PCM audio:

MY_DAC_DOES_DOP = True

formats = {
	'mp3' : { 'mime' : 'audio/mpeg', 'desc' : 'MP3 (MPEG-1 and/or MPEG-2 Audio Layer III), streamed natively as MP3', 'ext' : [ 'mp3', 'mpeg' ], 'strmbyte' : b'm' },
	'flac' : { 'mime' : 'audio/flac', 'desc' : 'FLAC, streamed natively as FLAC', 'ext' : [ 'flac' ], 'strmbyte' : b'f' },
	'dsd' : { 'mime' : 'audio/flac', 'desc' : 'DSD streams converted to 192KHz/24bit PCM and streamed in FLAC format (high-res PCM for non-DSD DAC(s))', 'ext' : [ 'dsf', 'dff' ], 'soxopts' : [ '-b','24','-r','192k','-C', '0', '-t', 'flac', '-' ], 'strmbyte' : b'f' },
	'aac' : { 'mime' : 'audio/aac', 'desc' : 'AAC and HE-AAC', 'ext' : [ 'm4a' ], 'strmbyte' : b'l', 'soxopts' : [ '-b', '16', '-r', '48k', '-C', '0', '-t', 'flac', '-' ] }
}

if MY_DAC_DOES_DOP:
	# change the sox command to properly encode DSD audio into DOP first, before writing out FLAC:
	formats['dsd']['soxopts'].append('dop')
	formats['dsd']['soxopts'][formats['dsd']['soxopts'].index('192k')] = '176.4k'
	formats['dsd']['desc'] = 'DSD streams encoded as DOP PCM and streamed in FLAC format (bit-perfect for DSD DACs)'

print('The following formats are enabled:\n')
for k in sorted(formats.keys()):
	print('   %s' % formats[k]['desc'])

def handleCommand(data):
	command = data["command"]
	if command == 'queue':
		for track in data["tracks"]:
			if os.path.exists(track):
				for ip, player in slimproto_srv.players.items():
					player.queue_track(track)
					if player.current_track == None:
						player.play()
	elif command == 'flush':
		for ip, player in slimproto_srv.players.items():
			player.flush_queue()
			if player.current_track != None:
				player.do_strm_flush()
				player.current_track = None
	elif command in [ 'next', 'prev', 'restart', 'goto' ]:
		delta_map = { 'next' : 1, 'prev' : -1, 'restart' : 0 }
		for ip, player in slimproto_srv.players.items():
			if command == 'goto':
				if type(data['pos']) != int:
					self.set_status(400)
				else:
					player.play(pos=data['pos'], flush=True)
			else:
				player.play(delta_map[command], flush=True)

class JSONRemoteControlWebSocket(tornado.websocket.WebSocketHandler):
	def on_message(self, message):
		try:
			data = json_decode(message)
			handleCommand(data)
		except Exception:
			pass

class JSONRemoteControlHandler(tornado.web.RequestHandler):

	def post(self):
		try:
			data = json_decode(self.request.body)
		except ValueError:
			self.set_status(400)
			return
		try:
			handleCommand(data)
		except KeyError:
			self.set_status(400)

def getMediaSettingsForFile(fn):
	ext = fn.split(".")[-1].lower()
	for f,d in formats.items():
		if ext in d['ext']:
			return d
	return None

class StreamHandler(tornado.web.RequestHandler):


	@coroutine
	def get(self, path):
		player = None
		for myid, myplayer in slimproto_srv.players.items():
			if myid == path:
				player = myplayer
				break
		if player == None:
			return
		if player.current_track == None:
			return
		fn = player.master_playlist[player.current_track]
		print("Serving",fn)
		self.set_header('Connection', 'close')
		self.request.connection.no_keep_alive = True
		try:
			format_settings = getMediaSettingsForFile(fn)
			if format_settings is None:
				self.set_error(400)
				return
			self.set_header('Content-Type', format_settings['mime'])
			if not 'soxopts' in format_settings:
				player.process = True
				# dummy value that we just use to quick break out if we need to
				# just send the file as-is, without help from sox:
				a = open(fn, 'rb')
				while True:
					if not player.process:
						print("aborting stream")
						break
					else:
						if self.full_percent > 90:
							time.sleep(0.1)
							continue
						else:
							data = a.read(65536)
							if data == b'':
								break
							self._write_buffer.append(data)
							del data
				a.close()
			else:
				# link player to the stream process so that is can kill it if it is flushing the stream
				player.process = Subprocess(['/usr/bin/sox',fn] + format_settings['soxopts'], stdout=Subprocess.STREAM)
				while True:
					if not player.process:
						print("aborting stream")
						break
					data = yield player.process.stdout.read_bytes(32768, partial=True)
					self._write_buffer.append(data)
					ret = yield self.flush()
		except tornado.iostream.StreamClosedError:
			print("Stream unexpectedly closed.")
		self.finish()

class HTTPMediaServer(tornado.web.Application):
	name = "SqueezeBox Server"
	handlers = [
		(r"/control", JSONRemoteControlHandler),
		(r"/controlsocket", JSONRemoteControlWebSocket),
		(r"/stream/(.*)", StreamHandler)
	]

	def __init__(self):
		tornado.web.Application.__init__(self, self.handlers, {})

class PlayerResource(object):

	def __init__(self,tcpserver,stream):
		self.tcpserver = tcpserver
		self._stream = stream
		self.id = ''.join(random.choice(string.ascii_uppercase) for _ in range(10))
		self.master_playlist = []
		self.current_track = None
		self.full_percent = None
		self.codecs = []
		self.process = None

	@property
	def stream(self):
		return self._stream
	
	@property
	def path(self):
		return '/stream/' + self.id

	@coroutine
	def queue_track(self,fn):
		if os.path.exists(fn):
			self.master_playlist.append(fn)
		if self.current_track == None:
			yield self.play_track()

	def flush_queue(self):
		self.master_playlist = []

	@coroutine
	def play_setup(self):
		yield self.do_strm_flush()
		yield self.do_setd(0)
		yield self.do_setd(4)
		yield self.do_enable_audio()
		yield self.do_audg()
		self.play()

	@coroutine
	def play_track(self):
		yield self.do_strm()
		yield self.do_audg()

	def move_track(self, delta=1, pos=None):
		if not len(self.master_playlist):
			return
		last_pos = len(self.master_playlist) - 1
		if pos != None:
			# specify absolute position
			new_pos = pos - 1
		elif delta:
			if self.current_track != None:
				# specify position relative to current track
				new_pos = self.current_track + delta
			else:
				# no current track, so start from beg/end of playlist
				if delta == 1:
					new_pos = 0
				else:
					new_pos = last_pos
		# maybe we wrapped around the beg/end:
		if new_pos < 0:
			new_pos = last_pos
		elif new_pos > last_pos:
			new_pos = 0
		# final sanity check:
		if new_pos >= 0 and new_pos <= last_pos:
			self.current_track = new_pos

	@coroutine
	def play(self,delta=1, pos=None, flush=False):
		if flush:
			self.do_strm_flush()
		if delta != 0:
			self.move_track(delta=delta, pos=pos)
		yield self.play_track()

	@coroutine
	def do_setd(self, num):
		out = 'setd'.encode() + bytes([num])
		data_len = len(out)
		out = bytes([ data_len//256, data_len%256]) + out
		a = yield self.stream.write(out)

	@coroutine
	def do_enable_audio(self):
		out = 'aude'.encode() + bytes([1,1])
		data_len = len(out)
		out = bytes([ data_len//256, data_len%256]) + out
		a = yield self.stream.write(out)

	@coroutine
	def do_strm_flush(self):
		if self.process:
			if self.process != True:
				# True is a dummy value when there's no subprocess generating the bitstream, and we just want
				# to break out of our python http_server streaming loop. If we have a real subprocess, we kill:
				self.process.proc.terminate()
			self.process = None
		out = 'strmq0m????'.encode() + bytes([0,0,0,ord('0'),0,0,0,0,0,0,0,0,0,0,0,0,0])
		data_len = len(out)
		out = bytes([ data_len//256, data_len%256]) + out
		a = yield self.stream.write(out)

	@coroutine
	def do_strm_status(self):
		out = 'strmt0m????'.encode() + bytes([0,0,0,ord('0'),0,0,0,0,0,0,0,0,0,0,0,0,0])
		data_len = len(out)
		out = bytes([ data_len//256, data_len%256]) + out
		a = yield self.stream.write(out)

	@coroutine
	def do_strm(self):
		if self.current_track == None:
			return
		f = self.master_playlist[self.current_track]
		format_settings = getMediaSettingsForFile(f)
		port = 9000
		# "strm" + cmd/autostart/formatbyte/pcmsampsize/pcmrate/channels/endian
		out = b"strms1" + format_settings['strmbyte'] + "????".encode()
		# threshold, spdif_enable, trans_period, trans_type, flags, output thresh, reserved
		out += bytes([255,0,10,ord('0'),0,0,0])
		# replay gain
		out += bytes([0,0,0,0])
		# port
		out += bytes([port//256, port%256])
		# ip
		out += bytes([0,0,0,0])
		out += "GET ".encode() + self.path.encode() + " HTTP/1.0\r\n\r\n".encode()
		data_len = len(out)
		out = bytes([ data_len//256, data_len%256]) + out
		a = yield self.stream.write(out)

	@coroutine
	def do_audg(self):
		out = 'audg'
		out += chr(0) + chr(0) + chr(0) + chr(80)
		out += chr(0) + chr(0) + chr(0) + chr(80)
		out += chr(0)
		out += chr(255)
		out += chr(0) + chr(1) + chr(0) + chr(0)
		out += chr(0) + chr(1) + chr(0) + chr(0)
		out += chr(0) + chr(0) + chr(0) + chr(0)
		out = out.encode()
		data_len = len(out)
		out = bytes([ data_len//256, data_len%256]) + out
		a = yield self.stream.write(out)

	@coroutine
	def cmd_stat(self, data):
		out={}
		out["event_code"] = data[0:4]
		out["buffer_size"] = int.from_bytes(data[7:11], byteorder='big')
		out["fullness"] = int.from_bytes(data[11:15], byteorder='big')
		out["bytes_received"] = int.from_bytes(data[15:23], byteorder='big')
		out["wifi_strength" ] = int.from_bytes(data[23:25], byteorder='big')
		out["jiffies"] = int.from_bytes(data[25:29], byteorder='big')
		out["output_buffer_size"] = int.from_bytes(data[29:33], byteorder='big')
		out["output_buffer_fullness"] = int.from_bytes(data[33:37], byteorder='big')
		out["elapsed_seconds"] = int.from_bytes(data[37:41], byteorder='big')
		self.full_percent = 100 * (out["fullness"] / out["buffer_size"])
		if out["event_code"] in [ b'STMd' ]:
			self.play()

	@coroutine
	def cmd_helo(self, data):
		out = {}
		if len(data) >= 8:
			out['device_id'] = data[0]
			out['revision'] = data[1]
			mac = ""
			for char in data[2:8]:
				mac += "%02x" % char + ":"
			out['mac'] = mac[:-1]
		if len(data) >= 24:
			out['uuid'] = data[8:24]
		if len(data) >= 26:
			out['wlanchannels'] = data[24:26]
		if len(data) >= 32:
			out['bytes'] = data[26:32]
		if len(data) >= 34:
			out['lang'] = data[32:34]
		if len(data) > 36:
			codecs = []
			caps = {}
			for entry in data[36:].decode('ascii').split(','):
				eq_split = entry.split("=")
				if len(eq_split) == 2:
					caps[eq_split[0]] = eq_split[1]
				else:
					self.codecs.append(entry)
			out['codecs'] = codecs
			out['caps'] = caps
		yield self.play_setup()

class SqueezeBoxServer(TCPServer):

	max_players = 3

	def __init__(self, http_server):
		super().__init__()
		self.players = {}
		self.http_server = http_server

	@coroutine
	def handle_stream(self, stream, address):

		if len(self.players) >= self.max_players:
			stream.close()
			return

		player = PlayerResource(self,stream)
		self.players[player.id] = player

		while True:
			try:
				myin = yield stream.read_bytes(8)
				command = myin[0:4]
				length = 0
				shift = 24
				for byte in myin[4:]:
					length = length + byte * (1 << shift)
					shift -= 8
				data = yield stream.read_bytes(length)
				if command == b"HELO":
					yield player.cmd_helo(data)
				elif command == b"STAT":
					yield player.cmd_stat(data)
				else:
					print(command, data)
			except tornado.iostream.StreamClosedError:
				del self.players[player.id]
				break

@coroutine
def reply():
	global slimproto_srv
	while True:
		nxt = sleep(5)
		yield nxt
		# send periodic status packet to let player know we're still there
		for myid, player in slimproto_srv.players.items():
			player.do_strm_status()

application = HTTPMediaServer()
http_server = tornado.httpserver.HTTPServer(application, xheaders=True)
http_server.bind(9000)
http_server.start()
slimproto_srv = SqueezeBoxServer(http_server)
slimproto_srv.listen(3483)
ioloop = IOLoop.instance()
ioloop.spawn_callback(reply)
ioloop.start()

# vim: ts=4 sw=4 noet
