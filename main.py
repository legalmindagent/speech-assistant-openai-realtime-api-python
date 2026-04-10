import os
import json
import base64
import asyncio
import traceback
from datetime import datetime
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.rest import Client as TwilioClient
from twilio.twiml.voice_response import VoiceResponse, Connect
from dotenv import load_dotenv
import httpx

load_dotenv()

app = FastAPI()

# Environment variables
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
DASHBOARD_WEBHOOK_URL = os.getenv("DASHBOARD_WEBHOOK_URL", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "aria-voice-2024")
DEFAULT_OWNER_EMAIL = os.getenv("OWNER_EMAIL", "mwmlwalraven@gmail.com")
DEFAULT_OWNER_PHONE = os.getenv("OWNER_PHONE", "")

# Twilio client
twilio_client = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Active calls tracking
active_calls = {}

# Business configs (keyed by Twilio number)
business_configs = {}

# Default industry personas
INDUSTRY_PERSONAS = {
    "hvac": {"name": "Sarah", "company": "Comfort Air Pro", "specialty": "heating and cooling"},
    "dental": {"name": "Emily", "company": "Bright Smile Dental", "specialty": "dental care"},
    "real_estate": {"name": "Jessica", "company": "Premier Properties", "specialty": "real estate"},
    "plumbing": {"name": "Mike", "company": "FlowRight Plumbing", "specialty": "plumbing"},
    "pest_control": {"name": "Lisa", "company": "Shield Pest Solutions", "specialty": "pest control"},
    "roofing": {"name": "Tom", "company": "TopGuard Roofing", "specialty": "roofing"},
    "auto_repair": {"name": "Chris", "company": "AutoCare Express", "specialty": "auto repair"},
    "veterinary": {"name": "Amy", "company": "Happy Paws Vet", "specialty": "veterinary care"},
    "electrical": {"name": "Dana", "company": "BrightWire Electric", "specialty": "electrical"},
    "home_cleaning": {"name": "Sandra", "company": "Sparkle Clean Co", "specialty": "home cleaning"},
    "towing": {"name": "Jake", "company": "RapidTow Services", "specialty": "towing and roadside assistance"},
    "locksmith": {"name": "Alex", "company": "KeyMaster Locksmith", "specialty": "locksmith and security"},
    "general": {"name": "Aria", "company": "Your Business", "specialty": "customer service"},
}


def get_business_config(called_number):
    config = business_configs.get(called_number, {})
    industry = config.get("industry", "general")
    persona = INDUSTRY_PERSONAS.get(industry, INDUSTRY_PERSONAS["general"])
    return {
        "business_name": config.get("business_name", persona["company"]),
        "agent_name": config.get("agent_name", persona["name"]),
        "industry": industry,
        "specialty": persona["specialty"],
        "owner_email": config.get("owner_email", DEFAULT_OWNER_EMAIL),
        "owner_phone": config.get("owner_phone", DEFAULT_OWNER_PHONE),
        "greeting": config.get("greeting", ""),
        "notify_sms": config.get("notify_sms", True),
        "notify_email": config.get("notify_email", True),
        "voice": config.get("voice", "Kore"),
    }

def build_system_prompt(config):
    greeting_line = ""
    if config.get("greeting"):
        greeting_line = "Use this greeting: " + config["greeting"]
    else:
        greeting_line = "Say: Thank you for calling " + config["business_name"] + "! This is " + config["agent_name"] + ", how can I help you today?"
    return f"""You are {config['agent_name']}, the friendly and professional AI receptionist for {config['business_name']}.
You specialize in {config['specialty']}.

Your job:
1. Greet the caller warmly. {greeting_line}
2. Collect their information naturally through conversation:
   - Full name
   - Phone number (confirm the one they are calling from if possible)
   - What they need help with (be specific to {config['specialty']})
   - Their address or location (if relevant for service dispatch)
   - How urgent it is (emergency, today, this week, just a quote)
3. Be empathetic and helpful. If it is an emergency, reassure them help is on the way.
4. Summarize what you have collected and let them know someone will follow up shortly.
5. Keep the conversation natural. You are a real receptionist, not a robot.

IMPORTANT RULES:
- Never say you are an AI unless directly asked.
- Keep responses concise (1-3 sentences) since this is a phone call.
- If you do not understand something, ask them to repeat it.
- Be warm, professional, and efficient.
- If they ask about pricing, say you will have someone get back to them with a detailed quote.
"""


GEMINI_WS_URL = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent?key={GOOGLE_API_KEY}"


@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <html><head><title>Aria Voice AI</title></head>
    <body style="font-family:sans-serif;max-width:800px;margin:40px auto;padding:20px;">
    <h1>Aria Voice AI - Live</h1>
    <p>AI-powered phone receptionist for service businesses.</p>
    <h3>Status</h3>
    <ul>
        <li>Voice Backend: Online</li>
        <li>Twilio Integration: Active</li>
        <li>Gemini 2.0 Flash: Connected</li>
    </ul>
    <h3>Active Calls</h3>
    <p id="calls">Loading...</p>
    <h3>Registered Businesses</h3>
    <p id="biz">Loading...</p>
    <script>
    fetch('/active-calls').then(r=>r.json()).then(d=>{
        document.getElementById('calls').textContent=d.active_calls+' active calls';
    });
    fetch('/businesses').then(r=>r.json()).then(d=>{
        document.getElementById('biz').textContent=d.count+' businesses registered';
    });
    </script>
    </body></html>
    """


@app.get("/health")
async def health():
    return {"status": "ok", "active_calls": len(active_calls), "businesses": len(business_configs)}


@app.get("/active-calls")
async def get_active_calls():
    return {"active_calls": len(active_calls), "calls": list(active_calls.values())}


@app.get("/businesses")
async def get_businesses():
    return {"count": len(business_configs), "numbers": list(business_configs.keys())}


@app.post("/register-business")
async def register_business(request: Request):
    data = await request.json()
    phone = data.get("twilio_number")
    if not phone:
        return JSONResponse({"error": "twilio_number required"}, status_code=400)
    business_configs[phone] = {
        "business_name": data.get("business_name", "My Business"),
        "agent_name": data.get("agent_name", "Aria"),
        "industry": data.get("industry", "general"),
        "owner_email": data.get("owner_email", DEFAULT_OWNER_EMAIL),
        "owner_phone": data.get("owner_phone", ""),
        "greeting": data.get("greeting", ""),
        "notify_sms": data.get("notify_sms", True),
        "notify_email": data.get("notify_email", True),
        "voice": data.get("voice", "Kore"),
    }
    return {"status": "registered", "twilio_number": phone, "config": business_configs[phone]}

@app.post("/incoming-call")
async def incoming_call(request: Request):
    form = await request.form()
    caller = form.get("From", "Unknown")
    called = form.get("To", "")
    call_sid = form.get("CallSid", "")

    config = get_business_config(called)
    print(f"Incoming call from {caller} to {called} ({config['business_name']}) | SID: {call_sid}")

    active_calls[call_sid] = {
        "call_sid": call_sid,
        "caller": caller,
        "called": called,
        "business": config["business_name"],
        "industry": config["industry"],
        "started_at": datetime.utcnow().isoformat(),
        "status": "ringing",
    }

    response = VoiceResponse()
    host = request.headers.get("host", "localhost")
    connect = Connect()
    stream = connect.stream(url=f"wss://{host}/media-stream")
    stream.parameter(name="caller", value=caller)
    stream.parameter(name="called", value=called)
    stream.parameter(name="callSid", value=call_sid)
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")


@app.websocket("/media-stream")
async def media_stream(ws: WebSocket):
    await ws.accept()
    print("WebSocket connected")

    call_sid = ""
    caller = ""
    called = ""
    config = {}
    stream_sid = ""
    gemini_ws = None
    call_start = datetime.utcnow()

    try:
        import websockets

        async with websockets.connect(GEMINI_WS_URL) as gws:
            gemini_ws = gws

            async def setup_gemini():
                nonlocal config
                setup_msg = {
                    "setup": {
                        "model": "models/gemini-2.0-flash-live-001",
                        "generation_config": {
                            "response_modalities": ["AUDIO"],
                            "speech_config": {
                                "voice_config": {
                                    "prebuilt_voice_config": {"voice_name": config.get("voice", "Kore")}
                                }
                            },
                        },
                        "system_instruction": {
                            "parts": [{"text": build_system_prompt(config)}]
                        },
                    }
                }
                await gws.send(json.dumps(setup_msg))
                raw = await gws.recv()
                setup_response = json.loads(raw)
                print("Gemini setup complete")
                return setup_response

            async def send_to_gemini(audio_data):
                msg = {
                    "realtime_input": {
                        "media_chunks": [
                            {
                                "data": base64.b64encode(audio_data).decode("utf-8"),
                                "mime_type": "audio/pcm;rate=16000",
                            }
                        ]
                    }
                }
                await gws.send(json.dumps(msg))

            async def receive_from_gemini():
                try:
                    async for raw in gws:
                        resp = json.loads(raw)
                        try:
                            parts = (
                                resp.get("serverContent", {})
                                .get("modelTurn", {})
                                .get("parts", [])
                            )
                            for part in parts:
                                if "inlineData" in part:
                                    audio_b64 = part["inlineData"]["data"]
                                    audio_bytes = base64.b64decode(audio_b64)
                                    mulaw = pcm_to_mulaw(audio_bytes, 24000, 8000)
                                    outb64 = base64.b64encode(mulaw).decode("utf-8")
                                    media_msg = {
                                        "event": "media",
                                        "streamSid": stream_sid,
                                        "media": {"payload": outb64},
                                    }
                                    await ws.send_json(media_msg)
                        except Exception as e:
                            print(f"Error processing Gemini response: {e}")
                except websockets.exceptions.ConnectionClosedOK:
                    print("Gemini connection closed normally")
                except Exception as e:
                    print(f"Gemini receive error: {e}")

            initial_setup_done = False

            async def handle_twilio():
                nonlocal stream_sid, call_sid, caller, called, config, initial_setup_done
                try:
                    async for message in ws.iter_text():
                        data = json.loads(message)
                        event = data.get("event")

                        if event == "start":
                            start_data = data.get("start", {})
                            stream_sid = start_data.get("streamSid", "")
                            params = start_data.get("customParameters", {})
                            caller = params.get("caller", "Unknown")
                            called = params.get("called", "")
                            call_sid = params.get("callSid", "")
                            config = get_business_config(called)
                            print(f"Stream started | Caller: {caller} | Business: {config['business_name']}")

                            if call_sid in active_calls:
                                active_calls[call_sid]["status"] = "in-progress"

                            await setup_gemini()
                            initial_setup_done = True

                        elif event == "media" and initial_setup_done:
                            payload = data["media"]["payload"]
                            audio_bytes = base64.b64decode(payload)
                            pcm_audio = mulaw_to_pcm(audio_bytes, 8000, 16000)
                            await send_to_gemini(pcm_audio)

                        elif event == "stop":
                            print(f"Stream stopped for call {call_sid}")
                            break

                except WebSocketDisconnect:
                    print("Twilio WebSocket disconnected")

            await asyncio.gather(handle_twilio(), receive_from_gemini())

    except Exception as e:
        print(f"Error in media stream: {e}")
        traceback.print_exc()
    finally:
        call_end = datetime.utcnow()
        duration = int((call_end - call_start).total_seconds())
        print(f"Call ended | Duration: {duration}s | Caller: {caller} | Business: {config.get('business_name', 'Unknown')}")

        if call_sid in active_calls:
            del active_calls[call_sid]

        if DASHBOARD_WEBHOOK_URL:
            await send_call_webhook(call_sid, caller, called, config, duration)

        if config.get("notify_sms") and config.get("owner_phone"):
            await send_sms_notification(config, caller, duration)

        if config.get("notify_email") and config.get("owner_email"):
            await send_email_notification(config, caller, duration)

def mulaw_to_pcm(mulaw_data, from_rate, to_rate):
    import audioop
    pcm = audioop.ulaw2lin(mulaw_data, 2)
    if from_rate != to_rate:
        pcm, _ = audioop.ratecv(pcm, 2, 1, from_rate, to_rate, None)
    return pcm


def pcm_to_mulaw(pcm_data, from_rate, to_rate):
    import audioop
    if from_rate != to_rate:
        pcm_data, _ = audioop.ratecv(pcm_data, 2, 1, from_rate, to_rate, None)
    return audioop.lin2ulaw(pcm_data, 2)


async def send_call_webhook(call_sid, caller, called, config, duration):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            payload = {
                "secret": WEBHOOK_SECRET,
                "call_sid": call_sid,
                "caller": caller,
                "called": called,
                "business_name": config.get("business_name", "Unknown"),
                "industry": config.get("industry", "general"),
                "duration": duration,
                "timestamp": datetime.utcnow().isoformat(),
            }
            resp = await client.post(f"{DASHBOARD_WEBHOOK_URL}/api/webhook/call-complete", json=payload)
            print(f"Webhook sent: {resp.status_code}")
    except Exception as e:
        print(f"Webhook failed: {e}")


async def send_sms_notification(config, caller, duration):
    try:
        if twilio_client and config.get("owner_phone"):
            msg = twilio_client.messages.create(
                body=f"New call for {config['business_name']}! From: {caller}, Duration: {duration}s. Check your dashboard for details.",
                from_=TWILIO_PHONE_NUMBER or os.getenv("TWILIO_PHONE_NUMBER"),
                to=config["owner_phone"],
            )
            print(f"SMS sent to {config['owner_phone']}: {msg.sid}")
    except Exception as e:
        print(f"SMS notification failed: {e}")


async def send_email_notification(config, caller, duration):
    try:
        if RESEND_API_KEY:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                    json={
                        "from": "Aria Voice AI <aria@resend.dev>",
                        "to": [config["owner_email"]],
                        "subject": f"New Call for {config['business_name']} from {caller}",
                        "html": f"<h2>New Call Received</h2><p><strong>Business:</strong> {config['business_name']}</p><p><strong>Caller:</strong> {caller}</p><p><strong>Duration:</strong> {duration} seconds</p><p><strong>Time:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</p><p>Check your dashboard for full details.</p>",
                    },
                )
                print(f"Email sent to {config['owner_email']}: {resp.status_code}")
    except Exception as e:
        print(f"Email notification failed: {e}")


@app.post("/send-email")
async def send_email_endpoint(request: Request):
    data = await request.json()
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                json={
                    "from": "Aria Voice AI <aria@resend.dev>",
                    "to": [data.get("to", DEFAULT_OWNER_EMAIL)],
                    "subject": data.get("subject", "New Call Log"),
                    "html": data.get("html", data.get("body", "")),
                },
            )
            return {"status": "sent", "code": resp.status_code}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/log-client")
async def log_client(request: Request):
    data = await request.json()
    print(f"Client logged: {json.dumps(data, indent=2)}")
    if DASHBOARD_WEBHOOK_URL:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"{DASHBOARD_WEBHOOK_URL}/api/webhook/client-log", json=data)
        except Exception:
            pass
    return {"status": "logged"}


async def keep_alive():
    while True:
        await asyncio.sleep(300)
        try:
            async with httpx.AsyncClient() as client:
                url = os.getenv("RENDER_EXTERNAL_URL", "https://voice-agent-backend-y0t9.onrender.com")
                await client.get(f"{url}/health")
                print("Keep-alive ping")
        except Exception:
            pass


@app.on_event("startup")
async def startup():
    asyncio.create_task(keep_alive())
    print("Aria Voice AI started!")
    print(f"Twilio configured: {bool(twilio_client)}")
    print(f"Gemini API Key: {'yes' if GOOGLE_API_KEY else 'no'}")
    print(f"Resend API Key: {'yes' if RESEND_API_KEY else 'no'}")
    print(f"Dashboard webhook: {DASHBOARD_WEBHOOK_URL or 'Not configured'}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 5050)))
