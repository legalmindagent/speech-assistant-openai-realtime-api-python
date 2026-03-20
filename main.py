import os
import json
import base64
import asyncio
import websockets
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect, Say, Stream
from dotenv import load_dotenv

load_dotenv()

# Configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
PORT = int(os.getenv('PORT', 5050))
TEMPERATURE = float(os.getenv('TEMPERATURE', 0.8))
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
VOICE = 'alloy'
LOG_EVENT_TYPES = [
        'error', 'response.content.done', 'rate_limits.updated',
        'response.done', 'input_audio_buffer.committed',
        'input_audio_buffer.speech_stopped', 'input_audio_buffer.speech_started',
        'session.created', 'session.updated'
]
SHOW_TIMING_MATH = False

app = FastAPI()

if not OPENAI_API_KEY:
        raise ValueError('Missing the OpenAI API key. Please set it in the .env file.')

@app.get("/", response_class=JSONResponse)
async def index_page():
        return {"message": "Multi-Industry AI Voice Agent is running!"}

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
        """Handle WebSocket connections between Twilio and OpenAI."""
        print("Client connected")
        await websocket.accept()

    async with websockets.connect(
                f"wss://api.openai.com/v1/realtime?model=gpt-realtime&temperature={TEMPERATURE}",
                additional_headers={
                                "Authorization": f"Bearer {OPENAI_API_KEY}"
                }
    ) as openai_ws:
                await initialize_session(openai_ws)

        # Connection specific state
                stream_sid = None
        latest_media_timestamp = 0
        last_assistant_item = None
        mark_queue = []
        response_start_timestamp_twilio = None

        async def receive_from_twilio():
                        """Receive audio data from Twilio and send it to the OpenAI Realtime API."""
                        nonlocal stream_sid, latest_media_timestamp
                        try:
                                            async for message in websocket.iter_text():
                                                                    data = json.loads(message)
                                                                    if data['event'] == 'media' and openai_ws.state.name == 'OPEN':
                                                                                                latest_media_timestamp = int(data['media']['timestamp'])
                                                                                                audio_append = {
                                                                                                    "type": "input_audio_buffer.append",
                                                                                                    "audio": data['media']['payload']
                                                                                                }
                                                                                                await openai_ws.send(json.dumps(audio_append))
elif data['event'] == 'start':
                        stream_sid = data['start']['streamSid']
                        print(f"Incoming stream has started {stream_sid}")
                        response_start_timestamp_twilio = None
                        latest_media_timestamp = 0
                        last_assistant_item = None
elif data['event'] == 'mark':
                        if mark_queue:
                            mark_queue.pop(0)
except WebSocketDisconnect:
                print("Client disconnected.")
                if openai_ws.state.name == 'OPEN':
                                        await openai_ws.close()

        async def send_to_twilio():
                        """Receive events from the OpenAI Realtime API, send audio back to Twilio."""
                        nonlocal stream_sid, last_assistant_item, response_start_timestamp_twilio
                        try:
                                            async for openai_message in openai_ws:
                                                                    response = json.loads(openai_message)
                                                                    if response['type'] in LOG_EVENT_TYPES:
                                                                                                print(f"Received event: {response['type']}", response)

                                                                    if response.get('type') == 'response.output_audio.delta' and 'delta' in response:
                                                                                                audio_payload = base64.b64encode(base64.b64decode(response['delta'])).decode('utf-8')
                                                                                                audio_delta = {
                                                                                                    "event": "media",
                                                                                                    "streamSid": stream_sid,
                                                                                                    "media": {
                                                                                                        "payload": audio_payload
                                                                                                        }
                                                                                                }
                                                                                                await websocket.send_json(audio_delta)


                                                if response.get("item_id") and response["item_id"] != last_assistant_item:
                                                                            response_start_timestamp_twilio = latest_media_timestamp
                                                                            last_assistant_item = response["item_id"]
                                                                            if SHOW_TIMING_MATH:
                                                                                                            print(f"Setting start timestamp for new response: {response_start_timestamp_twilio}ms")

                                                                        await send_mark(websocket, stream_sid)

                                # Trigger an interruption
                                                if response.get('type') == 'input_audio_buffer.speech_started':
                                                                            print("Speech started detected.")
                                                                            if last_assistant_item:
                                                                                                            print(f"Interrupting response with id: {last_assistant_item}")
                                                                                                            await handle_speech_started_event()
                        except Exception as e:
                                            print(f"Error in send_to_twilio: {e}")

                    async def handle_speech_started_event():
                                    """Handle interruption when the caller's speech starts."""
                                    nonlocal response_start_timestamp_twilio, last_assistant_item
                                    print("Handling speech started event.")
                                    if mark_queue and response_start_timestamp_twilio is not None:
                                                        elapsed_time = latest_media_timestamp - response_start_timestamp_twilio
                                                        if SHOW_TIMING_MATH:
                                                                                print(f"Calculating elapsed time for truncation: {latest_media_timestamp} - {response_start_timestamp_twilio} = {elapsed_time}ms")

                                                        if last_assistant_item:
                                                                                if SHOW_TIMING_MATH:
                                                                                                            print(f"Truncating item with ID: {last_assistant_item}, Truncated at: {elapsed_time}ms")

                                                                                truncate_event = {
                                                                                    "type": "conversation.item.truncate",
                                                                                    "item_id": last_assistant_item,
                                                                                    "content_index": 0,
                                                                                    "audio_end_ms": elapsed_time
                                                                                }
                                                                                await openai_ws.send(json.dumps(truncate_event))

                                                        await websocket.send_json({
                                                            "event": "clear",
                                                            "streamSid": stream_sid
                                                        })

                                        mark_queue.clear()
                last_assistant_item = None
                response_start_timestamp_twilio = None

        async def send_mark(connection, stream_sid):
                        if stream_sid:
                                            mark_event = {
                                                                    "event": "mark",
                                                                    "streamSid": stream_sid,
                                                                    "mark": {"name": "responsePart"}
                                            }
                                            await connection.send_json(mark_event)
                                            mark_queue.append('responsePart')

        await asyncio.gather(receive_from_twilio(), send_to_twilio())

async def send_initial_conversation_item(openai_ws):
        """Send initial conversation item if AI talks first."""
    initial_conversation_item = {
                "type": "conversation.item.create",
                "item": {
                                "type": "message",
                                "role": "user",
                                "content": [
                                                    {
                                                                            "type": "input_text",
                                                                            "text": "Greet the caller with: 'Hi! Thanks for calling. What industry or type of business are you calling about today?'"
                                                    }
                                ]
                }
    }
    await openai_ws.send(json.dumps(initial_conversation_item))
    await openai_ws.send(json.dumps({"type": "response.create"}))


async def initialize_session(openai_ws):
        """Control initial session with OpenAI."""
    session_update = {
                "type": "session.update",
                "session": {
                                "type": "realtime",
                                "model": "gpt-realtime",
                                "output_modalities": ["audio"],
                                "audio": {
                                                    "input": {
                                                                            "format": {"type": "audio/pcmu"},
                                                                            "turn_detection": {"type": "server_vad"}
                                                    },
                                                    "output": {
                                                                            "format": {"type": "audio/pcmu"},
                                                                            "voice": VOICE
                                                    }
                                },
                                "instructions": SYSTEM_MESSAGE,
                }
    }
    print('Sending session update:', json.dumps(session_update))
    await openai_ws.send(json.dumps(session_update))

    # Have the AI speak first with the greeting
    await send_initial_conversation_item(openai_ws)

if __name__ == "__main__":
        import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
