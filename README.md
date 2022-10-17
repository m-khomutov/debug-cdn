# debug-cdn

Receives RTSP/RTP stream. Logs RTSP protocol, RTP timing. Streams received video content in HTTP/FLV

**Installation**

`pip install debug-cdn-0.0.1-py3-none-any.whl`

**Usage**

`debug-cdn [-h] [-url URL] [-port PORT] [-loglevel LOGLEVEL]`

**positional arguments**

**optional arguments**

* -h, --help          show this help message and exit
* -url URL            rtsp url to watch timeline (streaming is disabled)
* -port PORT          http binding port to stream flv(def. 5566)
* -fps FPS            fps calculation period (sec.) (def. 10)
* -loglevel LOGLEVEL  logging level (critical|error|warning|info|debug def. info)

**restrictions**

* Audio receiving/streaming is not supported.
* Only AVC codec is supported.

**examples**

* `debug-cdn -loglevel debug`
* `debug-cdn -url 'rtsp://admin:12345@172.16.0.37'`

`ffplay 'http://127.0.0.1:5566/rtsp://admin:12345@172.16.0.37'` to get the stream.
