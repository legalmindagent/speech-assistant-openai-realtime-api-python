import os
import json
import base64
import asyncio
import audioop
import struct
import websockets
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect, Say, Stream
from dotenv import load_dotenv

load_dotenv()

# Configuration
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
PORT = int(os.getenv('PORT', 5050))
GEMINI_MODEL = "gemini-2.0-flash-live-001"
GEMINI_WS_URL = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={GEMINI_API_KEY}"

SYSTEM_MESSAGE = """You are an AI receptionist. When a call comes in, your first question is always: 'Hi! Thanks for calling. What industry or type of business are you calling about today?'

Based on their answer, adopt the following persona and intake flow:

HVAC:
- You are Sarah, receptionist for Comfort Air HVAC
- Ask: name, address, issue (no heat/AC/leak/noise), urgency, system type, vulnerable people in home
- Emergency (no heat in winter, gas smell, CO detector): "A technician will call you within 15 minutes"
- Routine: "Someone will call to schedule within 2 hours"

DENTAL:
- You are Emily, receptionist for Bright Smile Dental
- Ask: name, date of birth, insurance provider, reason for visit, preferred appointment time
- Emergency (severe pain, broken tooth, swelling): "We'll fit you in today, someone will call within 30 minutes"
- Routine: "We'll call to confirm your appointment within 2 hours"

REAL ESTATE:
- You are Jessica, receptionist for Premier Properties
- Ask: name, are they buying or selling, budget/price range, preferred areas, timeline, pre-approved for mortgage?
- Hot lead (ready now, pre-approved): "An agent will call you within 15 minutes"
- Browsing: "An agent will reach out within 24 hours"

PLUMBING:
- You are Mike, receptionist for Reliable Plumbing
- Ask: name, address, issue (leak/clog/no water/burst pipe), urgency, property type
- Emergency (burst pipe, flooding, no water): "A plumber will call within 15 minutes"
- Routine: "We'll schedule you within 2 hours"

PEST CONTROL:
- You are Lisa, receptionist for Shield Pest Control
- Ask: name, address, type of pest, severity, interior or exterior, any children or pets
- Urgent (bees/wasps/rodents inside): "A technician will call within 30 minutes"
- Routine: "We'll schedule an inspection within 24 hours"

ROOFING:
- You are Tom, receptionist for Summit Roofing
- Ask: name, address, issue (leak/storm damage/inspection), urgency, roof age if known
- Emergency (active leak, storm damage): "A roofer will call within 15 minutes"
- Routine: "We'll schedule a free inspection within 24 hours"

AUTO REPAIR:
- You are Chris, receptionist for AutoCare Plus
- Ask: name, vehicle make/model/year, issue, warning lights on, drivable or not
- Emergency (not drivable, safety issue): "A mechanic will call within 15 minutes"
- Routine: "We'll get you scheduled within 2 hours"

VETERINARY:
- You are Amy, receptionist for CareFirst Animal Hospital
- Ask: name, pet name, species/breed, age, issue, symptoms, how long
- Emergency (difficulty breathing, seizure, trauma): "Bring your pet in immediately, we'll be ready"
- Routine: "We'll schedule an appointment within 24 hours"

ELECTRICAL:
- You are Dana, receptionist for PowerPro Electric
- Ask: name, address, issue (no power/sparking/breaker/install), urgency
- Emergency (sparking, burning smell, no power): "An electrician will call within 15 minutes"
- Routine: "We'll schedule within 24 hours"

HOME CLEANING:
- You are Sandra, receptionist for Spotless Home Cleaning
- Ask: name, address, home size, type of clean (regular/deep/move-in/move-out), preferred days/times, pets
- All requests: "We'll send you a quote and call to confirm within 2 hours"

RULES FOR ALL INDUSTRIES:
- Keep responses SHORT - 1-2 sentences max
- Sound natural and warm - use contractions
- Never make up appointment times
- Always confirm caller info back to them before hanging up
- End every call: "You're all set! Someone from our team will be in touch very soon. Have a great day!"
- If industry not listed: "I can help with that! Let me take down your information and have the right person call you back."
"""

LOG_EVENT_TYPES = [
            'error', 'setupComplete', 'serverContent',
            'toolCall', 'toolCallCancellation'
]

app = FastAPI()

if not GEMINI_API_KEY:
            raise ValueError('Missing the Gemini API key. Please set GEMINI_API_KEY in the .env file.')

def mulaw_to_pcm16(mulaw_data):
            """Convert mu-law 8kHz audio to PCM 16-bit 16kHz for Gemini."""
            pcm_8k = audioop.ulaw2lin(mulaw_data, 2)
            pcm_16k, _ = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, None)
            return pcm_16k

def pcm16_to_mulaw(pcm_data, from_rate=24000):
            """Convert PCM 16-bit audio from Gemini to mu-law 8kHz for Twilio."""
            pcm_8k, _ = audioop.ratecv(pcm_data, 2, 1, from_rate, 8000, None)
            mulaw_data = audioop.lin2ulaw(pcm_8k, 2)
            return mulaw_data

@app.get("/", response_class=JSONResponse)
async def index_page():
            return {"message": "Multi-Industry AI Voice Agent (Gemini) is running!"}

@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
            """Handle incoming call and return TwiML response to connect to Media Stream."""
            response = VoiceResponse()
            response.say(
                "Please wait while we connect you to our AI receptionist.",
                voice="Google.en-US-Chirp3-HD-Aoede"
            )
            response.pause(length=1)
            response.say(
                "O.K. you can start talking!",
                voice="Google.en-US-Chirp3-HD-Aoede"
            )
            host = request.url.hostname
            connect = Connect()
            connect.stream(url=f'wss://{host}/media-stream')
            response.append(connect)
            return HTMLResponse(content=str(response), media_type="application/xml")

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
            """Handle WebSocket connections between Twilio and Gemini Live API."""
            print("Client connected")
            await websocket.accept()

    async with websockets.connect(GEMINI_WS_URL) as gemini_ws:
                    # Send setup message to Gemini
                    setup_msg = {
                                        "setup": {
                                                                "model": f"models/{GEMINI_MODEL}",
                                                                "generationConfig": {
                                                                                            "responseModalities": ["AUDIO"],
                                                                                            "speechConfig": {
                                                                                                                            "voiceConfig": {
                                                                                                                                                                "prebuiltVoiceConfig": {
                                                                                                                                                                                                        "voiceName": "Aoede"
                                                                                                                                                                        }
                                                                                                                                    }
                                                                                                    }
                                                                },
                                                                "systemInstruction": {
                                                                                            "parts": [{"text": SYSTEM_MESSAGE}]
                                                                }
                                        }
                    }
                    await gemini_ws.send(json.dumps(setup_msg))

        # Wait for setup complete
                    setup_response = await gemini_ws.recv()
        setup_data = json.loads(setup_response)
        print("Gemini setup response:", setup_data)

        # Send initial greeting prompt
        initial_msg = {
                            "clientContent": {
                                                    "turns": [
                                                                                {
                                                                                                                "role": "user",
                                                                                                                "parts": [{"text": "A caller just connected. Greet them warmly and ask what industry they are calling about."}]
                                                                                        }
                                                    ],
                                                    "turnComplete": True
                            }
        }
        await gemini_ws.send(json.dumps(initial_msg))

        # Connection specific state
        stream_sid = None

        async def receive_from_twilio():
                            """Receive audio data from Twilio and send it to Gemini."""
                            nonlocal stream_sid
                            try:
                                                    async for message in websocket.iter_text():
                                                                                data = json.loads(message)
                                                                                if data['event'] == 'media':
                                                                                                                # Decode mulaw audio from Twilio
                                                                                                                mulaw_bytes = base64.b64decode(data['media']['payload'])
                                                                                                                # Convert to PCM 16-bit 16kHz for Gemini
                                                                                                                pcm_data = mulaw_to_pcm16(mulaw_bytes)
                                                                                                                pcm_b64 = base64.b64encode(pcm_data).decode('utf-8')

                                                                                    # Send to Gemini Live API
                                                                                                                audio_msg = {
                                                                                                                    "realtimeInput": {
                                                                                                                        "mediaChunks": [
                                                                                                                            {
                                                                                                                                "mimeType": "audio/pcm;rate=16000",
                                                                                                                                "data": pcm_b64
                                                                                                                                    }
                                                                                                                                ]
                                                                                                                            }
                                                                                                                        }
                                                                                                                if gemini_ws.open:
                                                                                                                                                    await gemini_ws.send(json.dumps(audio_msg))
                                                                                        elif data['event'] == 'start':
                                                                                    stream_sid = data['start']['streamSid']
                                                                                    print(f"Incoming stream has started {stream_sid}")
                            except WebSocketDisconnect:
                                                    print("Client disconnected.")
                                                    if gemini_ws.open:
                                                                                await gemini_ws.close()

                                            async def send_to_twilio():
                                                                """Receive audio from Gemini and send it back to Twilio."""
                                                                nonlocal stream_sid
                                                                try:
                                                                                        async for gemini_message in gemini_ws:
                                                                                                                    response = json.loads(gemini_message)

                                                                                            # Check for audio data in server content
                                                                                                                    server_content = response.get("serverContent", {})
                                                                                                                    model_turn = server_content.get("modelTurn", {})
                                                                                                                    parts = model_turn.get("parts", [])

                                                                                            for part in parts:
                                                                                                                            inline_data = part.get("inlineData", {})
                                                                                                                            if inline_data.get("mimeType", "").startswith("audio/pcm"):
                                                                                                                                                                # Decode PCM audio from Gemini
                                                                                                                                                                pcm_b64 = inline_data.get("data", "")
                                                                                                                                                                if pcm_b64 and stream_sid:
                                                                                                                                                                                                        pcm_bytes = base64.b64decode(pcm_b64)
                                                                                                                                                                                                        # Convert PCM 24kHz to mulaw 8kHz for Twilio
                                                                                                                                                                                                        mulaw_bytes = pcm16_to_mulaw(pcm_bytes, from_rate=24000)
                                                                                                                                                                                                        mulaw_b64 = base64.b64encode(mulaw_bytes).decode('utf-8')
                                                                                                                                                                        
                                                                                                                                                                    audio_delta = {
                                                                                                                                                                        "event": "media",
                                                                                                                                                                        "streamSid": stream_sid,
                                                                                                                                                                        "media": {
                                                                                                                                                                            "payload": mulaw_b64
                                                                                                                                                                                }
                                                                                                                                                                        }
                                                                                                                                                                    await websocket.send_json(audio_delta)
                                                                                                                                    
                                                                                                                        # Log turn complete
                                                                                                                        if server_content.get("turnComplete"):
                                                                                                                                                        print("Gemini turn complete")
                                                                                                                                
except Exception as e:
                print(f"Error in send_to_twilio: {e}")

        await asyncio.gather(receive_from_twilio(), send_to_twilio())

if __name__ == "__main__":
            import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
