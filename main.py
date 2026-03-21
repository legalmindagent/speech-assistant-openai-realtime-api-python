import os
import json
import base64
import asyncio
import audioop
import struct
import websockets
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect, Say, Stream
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
PORT = int(os.getenv('PORT', 5050))
GEMINI_MODEL = "gemini-2.0-flash-live-001"
GEMINI_WS_URL = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={GEMINI_API_KEY}"
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL', '')

SYSTEM_MESSAGE = """You are an AI receptionist. When a call comes in, your first question is always:
Hi! Thanks for calling. What industry or type of business are you calling about today?

Based on their answer, adopt the following persona and intake flow:

HVAC: You are Sarah from Comfort Air HVAC. Ask name, address, issue, urgency, system type.
Emergency: A technician will call within 15 minutes. Routine: Someone will call within 2 hours.

DENTAL: You are Emily from Bright Smile Dental. Ask name, DOB, insurance, reason, preferred time.
Emergency: We will fit you in today. Routine: We will call to confirm within 2 hours.

REAL ESTATE: You are Jessica from Premier Properties. Ask name, buying/selling, budget, areas, timeline.
Hot lead: An agent will call within 15 minutes. Browsing: An agent will reach out within 24 hours.

PLUMBING: You are Mike from Reliable Plumbing. Ask name, address, issue, urgency, property type.
Emergency: A plumber will call within 15 minutes. Routine: We will schedule within 2 hours.

PEST CONTROL: You are Lisa from Shield Pest Control. Ask name, address, pest type, severity, kids/pets.
Urgent: A technician will call within 30 minutes. Routine: We will schedule within 24 hours.

ROOFING: You are Tom from Summit Roofing. Ask name, address, issue, urgency, roof age.
Emergency: A roofer will call within 15 minutes. Routine: Free inspection within 24 hours.

AUTO REPAIR: You are Chris from AutoCare Plus. Ask name, vehicle info, issue, drivable or not.
Emergency: A mechanic will call within 15 minutes. Routine: Scheduled within 2 hours.

VETERINARY: You are Amy from CareFirst Animal Hospital. Ask name, pet info, issue, symptoms.
Emergency: Bring your pet in immediately. Routine: Appointment within 24 hours.

ELECTRICAL: You are Dana from PowerPro Electric. Ask name, address, issue, urgency.
Emergency: An electrician will call within 15 minutes. Routine: Scheduled within 24 hours.

HOME CLEANING: You are Sandra from Spotless Home Cleaning. Ask name, address, home size, clean type.
All requests: Quote and confirmation call within 2 hours.

RULES: Keep responses SHORT 1-2 sentences. Sound natural and warm. Never make up times.
Always confirm info before hanging up. End with: You are all set! Someone will be in touch soon.
If industry not listed: I can help with that! Let me take your information.
"""


# Keep-alive self-ping to prevent Render free tier from sleeping
async def keep_alive():
        url = RENDER_EXTERNAL_URL or f"http://localhost:{PORT}"
        while True:
                    await asyncio.sleep(300)  # Ping every 5 minutes
        try:
                        async with httpx.AsyncClient() as client:
                                            resp = await client.get(f"{url}/health", timeout=10)
                                            print(f"Keep-alive ping: {resp.status_code}")
        except Exception as e:
                        print(f"Keep-alive ping failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
        task = asyncio.create_task(keep_alive())
        yield
        task.cancel()


app = FastAPI(lifespan=lifespan)

if not GEMINI_API_KEY:
        raise ValueError('Missing GEMINI_API_KEY')


def mulaw_to_pcm16(mulaw_data):
        pcm_8k = audioop.ulaw2lin(mulaw_data, 2)
        pcm_16k, _ = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, None)
        return pcm_16k


def pcm16_to_mulaw(pcm_data, from_rate=24000):
        pcm_8k, _ = audioop.ratecv(pcm_data, 2, 1, from_rate, 8000, None)
        mulaw_data = audioop.lin2ulaw(pcm_8k, 2)
        return mulaw_data


@app.get("/", response_class=JSONResponse)
async def index_page():
        return {"message": "Multi-Industry AI Voice Agent (Gemini) is running!"}


@app.get("/health", response_class=JSONResponse)
async def health_check():
        return {"status": "ok"}


@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
        response = VoiceResponse()
        response.say("Please wait while we connect you to our AI receptionist.", voice="Google.en-US-Chirp3-HD-Aoede")
        response.pause(length=1)
        response.say("OK you can start talking!", voice="Google.en-US-Chirp3-HD-Aoede")
        host = request.url.hostname
        connect = Connect()
        connect.stream(url=f'wss://{host}/media-stream')
        response.append(connect)
        return HTMLResponse(content=str(response), media_type="application/xml")


@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
        print("Client connected")
        await websocket.accept()
        gemini_ws = await websockets.connect(GEMINI_WS_URL)
        setup_msg = {"setup": {"model": f"models/{GEMINI_MODEL}", "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Aoede"}}}}, "systemInstruction": {"parts": [{"text": SYSTEM_MESSAGE}]}}}
        await gemini_ws.send(json.dumps(setup_msg))
        setup_response = await gemini_ws.recv()
        print("Gemini setup:", json.loads(setup_response))
        initial_msg = {"clientContent": {"turns": [{"role": "user", "parts": [{"text": "A caller just connected. Greet them and ask what industry they are calling about."}]}], "turnComplete": True}}
        await gemini_ws.send(json.dumps(initial_msg))
        stream_sid = None

    async def receive_from_twilio():
                nonlocal stream_sid
                try:
                                async for message in websocket.iter_text():
                                                    data = json.loads(message)
                                                    if data['event'] == 'media':
                                                                            mulaw_bytes = base64.b64decode(data['media']['payload'])
                                                                            pcm_data = mulaw_to_pcm16(mulaw_bytes)
                                                                            pcm_b64 = base64.b64encode(pcm_data).decode('utf-8')
                                                                            audio_msg = {"realtimeInput": {"mediaChunks": [{"mimeType": "audio/pcm;rate=16000", "data": pcm_b64}]}}
                                                                            if gemini_ws.open:
                                                                                                        await gemini_ws.send(json.dumps(audio_msg))
                                                        elif data['event'] == 'start':
                                                        stream_sid = data['start']['streamSid']
                                                        print(f"Stream started {stream_sid}")
                except WebSocketDisconnect:
                                print("Client disconnected.")
                                if gemini_ws.open:
                                                    await gemini_ws.close()

                        async def send_to_twilio():
                                    nonlocal stream_sid
                                    try:
                                                    async for gemini_message in gemini_ws:
                                                                        response = json.loads(gemini_message)
                                                                        sc = response.get("serverContent", {})
                                                                        mt = sc.get("modelTurn", {})
                                                                        for part in mt.get("parts", []):
                                                                                                ind = part.get("inlineData", {})
                                                                                                if ind.get("mimeType", "").startswith("audio/pcm"):
                                                                                                                            pcm_b64 = ind.get("data", "")
                                                                                                                            if pcm_b64 and stream_sid:
                                                                                                                                                            pcm_bytes = base64.b64decode(pcm_b64)
                                                                                                                                                            mulaw_bytes = pcm16_to_mulaw(pcm_bytes, from_rate=24000)
                                                                                                                                                            mulaw_b64 = base64.b64encode(mulaw_bytes).decode('utf-8')
                                                                                                                                                            await websocket.send_json({"event": "media", "streamSid": stream_sid, "media": {"payload": mulaw_b64}})
                                                                                                                                                if sc.get("turnComplete"):
                                                                                                                                                                        print("Gemini turn complete")
                                                                                                    except Exception as e:
                                                                                                                    print(f"Error in send_to_twilio: {e}")
                                                                                                        
                                await asyncio.gather(receive_from_twilio(), send_to_twilio())


if __name__ == "__main__":
        import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
