import asyncio
import cv2
import json
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame

pcs = set()

class VideoFileTrack(VideoStreamTrack):
    def __init__(self, path):
        super().__init__()
        self.cap = cv2.VideoCapture(path)

    async def recv(self):
        print("Sending frame")

        pts, time_base = await self.next_timestamp()

        ret, frame = self.cap.read()
        if not ret:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self.cap.read()

        #frame = cv2.resize(frame, (640, 480))
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        video_frame = VideoFrame.from_ndarray(frame, format="rgb24")
        video_frame.pts = pts
        video_frame.time_base = time_base

        return video_frame

async def offer(request):
    print("Received offer request")

    params = await request.json()
    offer = RTCSessionDescription(
        sdp=params["sdp"],
        type=params["type"]
    )

    pc = RTCPeerConnection()
    pcs.add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print("Connection state:", pc.connectionState)

    await pc.setRemoteDescription(offer)

    track = VideoFileTrack("video.mp4")
    pc.addTrack(track)

    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    print("Sending answer back")

    return web.Response(
        content_type="application/json",
        text=json.dumps({
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        })
    )

app = web.Application()
app.router.add_post("/offer", offer)

web.run_app(app, port=8080)
