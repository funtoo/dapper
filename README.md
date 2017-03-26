# dapper
Dapper, the digital audio playback platform, is **a hackable replacement for Logitech's Media Server implemented in about 400 
lines of Python code**, with a focus on lossless playback, including FLAC and DSD (via DOP PCM encoding) files. Dapper is designed to be simple, 
clean, hackable by someone with a reasonable grasp of Python and the
concepts used, and easily extensible. It is distributed under the terms of the Mozilla Public License version 2, or (at your option)
the terms of the GNU General Public License version 2 or later, in order to keep the code available to all.

## Compatibility

Dapper currently implements a subset of the SqueezeBox protocol (server side) -- just enough to work very well with squeezelite,
a 'headless' SqueezeBox emulator that can be run on any Linux machine, and that is used for playing back music. **Dapper provides
the other necessary half of squeezelite -- a music server to which squeezelite can connect and stream music data from.** Combined,
they provide a very capable music playback system, free of the constraints of the very capable but very large Logitech Media Server software.

## Requirements

**To use Dapper, you will need to install it on a Linux system where your music files reside.** The following dependencies are
required:

* **Python version 3.3 or later.**
* **Python tornado module**, version 4 or later.
* **For DSD playback, you'll need the `sox` Linux executable** with special DSD patches.
* **squeezelite**, which can run on the same server as dapper, or somewhere else on the same LAN.

### Setup Under Funtoo Linux

[Funtoo Linux](http://www.funtoo.org) comes with sox patched to support .dsf and .dff DSD files and DOP playback. To install dependencies
under Funtoo Linux, type:

```
# emerge sox www-servers/tornado
```
If you are planning to run squeezelite on the same system as dapper, emerge it there too. Otherwise, install it on another system:

```
# emerge squeezelite
```

## Getting Started

To use dapper, you first need to have `squeezelite` up and running on the system that will be playing back music. I use
squeezelite which in turn plays back audio using ALSA via a USB DAC. My USB DAC supports DOP encoding for receiving and playing back
DSD files. I use the following command-line options to start squeezelite:

```
# squeezelite -o iec958 -D -c flac,pcm,mp3 -r 44100,48000,88200,96000,176400,192000 -P 90 -s 127.0.0.1:3483 -b 4096:4096
```

If you are using Funtoo Linux, these options can be added to `SQUEEZELITE_OPTS` in `/etc/conf.d/squeezelite`. The options above
tell squeezelite that it should accept flac, PCM and mp3 data at the specified bitrates. **If you want to playback high-bitrate music, 
it is important to specify the -o option, above, to hit the _raw_ playback device and not the default device, which will down-mix to 48Khz.**
Also note the important `-s` option which specifies where squeezelite will look for dapper. In this case, it will look for dapper
running on the same host (localhost) port 3483, which is the standard control port for the SqueezeBox protocol.

## DSD Support

If you are not planning to play back DSD files, you can safely skip this section. If you *are* planning to play back DSD, you will
want to let dapper know whether your DAC supports DSD64. If it supports DSD64 via DOP, then ensure that MY_DAC_DOES_DOP is set to
True in the code; otherwise False.


Now that squeezelite is running, you can now start dapper:

```
# python3 ./dapper.py
```

Now, to play back music, in another console, use the `musicq.py` command to tell dapper to stream some music. Use it as follows:

```
# python3 ./musicq.py /path/to/myfile.flac /path/to/myfile2.flac

```

# Features

* Playback of FLAC, MP3, and SACD formats (dsf, dff).
* Ability to work with DACs that support DSD64 and those that just do high-res PCM for playback of SACD formats.
* Web API for music control.

## Limitations

Currently, dapper has a bunch of easy-to-fix limitations to encourage GitHub pull requests :)

* It is not tested with real Squeezeboxes, and may or may not work with them.
* No music metadata or browsing is supported. Write separate programs to do this. Dapper is meant to be tiny and functional :)

## The SlimServer/SqueezeBox Protocol

In setting up your dapper playback system, or hacking on the code, it may help to have a basic understanding of the protocol used.

Port 3483 is the 'control' port -- squeezelite (or SqueezeBox) will connect to port 3483 of the server, and communicate with it using
a raw TCP socket. This is the primary communications port for client<->server communications, but **no music data is transmitted
over this port.**

To play back music, dapper will send a command to squeezelite that basically says "connect to this URL (port 9000) and stream the
raw music file from here. Squeezelite will then send out a regular HTTP request (HTTP 1.0) to that URL and start streaming the 
music.

Meanwhile, on port 3483, dapper monitors how full squeezelite's buffers are. Rather than sending ALL the music over port 9000
as fast as possible, dapper doles out the music data in little bits -- just enough to keep squeezelite's buffers full, without
overloading them.

## Testing

Dapper is tested on a Raspberry Pi 3B running Funtoo Linux and squeezelite, streaming to a SMSL M8 DSD DAC via USB.

## Author

Concept and code by Daniel Robbins (drobbins@funtoo.org). Please stop by the #funtoo IRC channel on Freenode and let us know
how you like it! :)
