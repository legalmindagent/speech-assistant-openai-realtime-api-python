import os
import json
import base64
import asyncio
import traceback
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.websockets import WebSocketDisconnect
from twilio.rest import Client as TwilioClient
from twilio.twiml.voice_response import VoiceResponse
from dotenv import load_dotenv
import httpx

try:
    import audioop
except ImportError:
    audioop = None

load_dotenv()

app = FastAPI()

# CORS middleware for dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Environment variables
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "+14235563838")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
DASHBOARD_WEBHOOK_URL = os.getenv("DASHBOARD_WEBHOOK_URL", "https://aria-dashboard-steel.vercel.app")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "aria-voice-2024")
DEFAULT_OWNER_EMAIL = os.getenv("OWNER_EMAIL", "mwmlwalraven@gmail.com")
DEFAULT_OWNER_PHONE = os.getenv("OWNER_PHONE", "")

# Twilio client
twilio_client = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Active calls tracking
active_calls = {}

# Call history (persisted)
CALL_LOG_FILE = Path("/tmp/aria_call_log.json")
BUSINESS_CONFIG_FILE = Path("/tmp/aria_businesses.json")

call_history = []

# Business configs (keyed by Twilio number)
business_configs = {}

def save_businesses():
    try:
        with open(BUSINESS_CONFIG_FILE, "w") as f:
            json.dump(business_configs, f, indent=2)
    except Exception as e:
        print(f"Error saving businesses: {e}")

def load_businesses():
    global business_configs
    try:
        if BUSINESS_CONFIG_FILE.exists():
            with open(BUSINESS_CONFIG_FILE, "r") as f:
                business_configs = json.load(f)
                print(f"Loaded {len(business_configs)} business configs from disk")
    except Exception as e:
        print(f"Error loading businesses: {e}")

def save_call_log():
    try:
        with open(CALL_LOG_FILE, "w") as f:
            json.dump(call_history[-500:], f, indent=2)
    except Exception as e:
        print(f"Error saving call log: {e}")

def load_call_log():
    global call_history
    try:
        if CALL_LOG_FILE.exists():
            with open(CALL_LOG_FILE, "r") as f:
                call_history = json.load(f)
                print(f"Loaded {len(call_history)} call records from disk")
    except Exception as e:
        print(f"Error loading call log: {e}")


# Default industry personas
INDUSTRY_PERSONAS = {
    "hvac": {"name": "Aria", "company": "Comfort Air Pro", "specialty": "heating and cooling"},
    "dental": {"name": "Aria", "company": "Bright Smile Dental", "specialty": "dental care"},
    "real_estate": {"name": "Aria", "company": "Premier Properties", "specialty": "real estate"},
    "plumbing": {"name": "Aria", "company": "FlowRight Plumbing", "specialty": "plumbing"},
    "pest_control": {"name": "Aria", "company": "Shield Pest Solutions", "specialty": "pest control"},
    "roofing": {"name": "Aria", "company": "TopGuard Roofing", "specialty": "roofing"},
    "auto_repair": {"name": "Aria", "company": "AutoCare Express", "specialty": "auto repair"},
    "veterinary": {"name": "Aria", "company": "PawCare Veterinary", "specialty": "veterinary care"},
    "legal": {"name": "Aria", "company": "Summit Legal Group", "specialty": "legal services"},
    "towing": {"name": "Aria", "company": "RapidTow", "specialty": "towing and roadside assistance"},
    "locksmith": {"name": "Aria", "company": "QuickKey Locksmith", "specialty": "locksmith services"},
    "electrical": {"name": "Aria", "company": "BrightWire Electric", "specialty": "electrical services"},
    "general": {"name": "Aria", "company": "Local Business", "specialty": "customer service"},
}


def get_business_config(phone_number):
    config = business_configs.get(phone_number, {})
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
4. Summarize what you have collected and let them know the team will follow up shortly.
5. Thank them for calling and wish them a good day.

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
    <html><head><title>Aria Voice AI</title>
    <style>body{font-family:system-ui;max-width:600px;margin:60px auto;text-align:center;color:#333}
    h1{color:#4F46E5;font-size:2.5em}p{font-size:1.2em;line-height:1.6}
    .badge{display:inline-block;padding:6px 16px;background:#10B981;color:white;border-radius:20px;font-size:0.9em}
    a{color:#4F46E5}</style></head>
    <body><h1>Aria Voice AI</h1>
    <p class="badge">System Online</p>
    <p>AI-powered phone receptionist for local businesses.</p>
    <p><a href="/health">Health Check</a> | <a href="/businesses">Businesses</a> | <a href="/call-log">Call Log</a></p>
    </body></html>
    """


@app.get("/health")
async def health():
    return {"status": "ok", "active_calls": len(active_calls), "businesses": len(business_configs), "total_calls": len(call_history)}


@app.get("/active-calls")
async def get_active_calls():
    return {"active_calls": len(active_calls), "calls": list(active_calls.values())}


@app.get("/businesses")
async def get_businesses():
    return {"count": len(business_configs), "numbers": list(business_configs.keys()), "configs": {k: {kk: vv for kk, vv in v.items()} for k, v in business_configs.items()}}


@app.get("/call-log")
async def get_call_log():
    return {"total": len(call_history), "calls": call_history[-50:][::-1]}


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
        "voice": data.get("voice", "Kore"),
        "notify_sms": data.get("notify_sms", True),
        "notify_email": data.get("notify_email", True),
    }
    save_businesses()
    return {"status": "registered", "twilio_number": phone, "config": business_configs[phone]}


@app.post("/incoming-call")
async def incoming_call(request: Request):
    try:
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

        host = request.headers.get("host", "localhost")
        from xml.sax.saxutils import escape
        twiml = '<?xml version="1.0" encoding="UTF-8"?>'
        twiml += '<Response><Connect>'
        twiml += '<Stream url="wss://' + escape(host) + '/media-stream">'
        twiml += '<Parameter name="caller" value="' + escape(caller) + '" />'
        twiml += '<Parameter name="called" value="' + escape(called) + '" />'
        twiml += '<Parameter name="callSid" value="' + escape(call_sid) + '" />'
        twiml += '</Stream></Connect></Response>'
        print(f"TwiML response generated for call {call_sid}")
        return HTMLResponse(content=twiml, media_type="application/xml")
    except Exception as e:
        print(f"ERROR in incoming_call: {e}")
        traceback.print_exc()
        fallback = '<?xml version="1.0" encoding="UTF-8"?><Response><Say>We are experiencing technical difficulties. Please try again later.</Say></Response>'
        return HTMLResponse(content=fallback, media_type="application/xml")


# Error log for debugging (in-memory, last 50 errors)
error_log = []

@app.get("/test-twiml")
async def test_twiml():
    """Test endpoint to verify TwiML generation works"""
    try:
        from xml.sax.saxutils import escape
        host = "voice-agent-backend-y0t9.onrender.com"
        caller = "+15551234567"
        called = "+14235563838"
        call_sid = "TEST_CALL"
        twiml = '<?xml version="1.0" encoding="UTF-8"?>'
        twiml += '<Response><Connect>'
        twiml += '<Stream url="wss://' + escape(host) + '/media-stream">'
        twiml += '<Parameter name="caller" value="' + escape(caller) + '" />'
        twiml += '<Parameter name="called" value="' + escape(called) + '" />'
        twiml += '<Parameter name="callSid" value="' + escape(call_sid) + '" />'
        twiml += '</Stream></Connect></Response>'
        return HTMLResponse(content=twiml, media_type="application/xml")
    except Exception as e:
        return JSONResponse({"error": str(e), "traceback": traceback.format_exc()})

@app.get("/errors")
async def get_errors():
    return {"errors": error_log[-50:]}


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
                                "mime_type": "audio/pcm;rate=16000",
                                "data": base64.b64encode(audio_data).decode("utf-8"),
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

        # Save call to history
        call_record = {
            "call_sid": call_sid,
            "caller": caller,
            "called": called,
            "business_name": config.get("business_name", "Unknown"),
            "industry": config.get("industry", "general"),
            "duration": duration,
            "started_at": call_start.isoformat(),
            "ended_at": call_end.isoformat(),
            "status": "completed" if duration > 5 else "missed",
        }
        call_history.append(call_record)
        save_call_log()

        if call_sid in active_calls:
            del active_calls[call_sid]

        if DASHBOARD_WEBHOOK_URL:
            await send_call_webhook(call_sid, caller, called, config, duration)

        if config.get("notify_sms") and config.get("owner_phone"):
            await send_sms_notification(config, caller, duration)

        if config.get("notify_email") and config.get("owner_email"):
            await send_email_notification(config, caller, duration)


def mulaw_to_pcm(mulaw_data, from_rate, to_rate):
    if audioop:
        pcm = audioop.ulaw2lin(mulaw_data, 2)
        if from_rate != to_rate:
            pcm, _ = audioop.ratecv(pcm, 2, 1, from_rate, to_rate, None)
        return pcm
    else:
        import struct
        MULAW_DECODE_TABLE = [
            -32124,-31100,-30076,-29052,-28028,-27004,-25980,-24956,
            -23932,-22908,-21884,-20860,-19836,-18812,-17788,-16764,
            -15996,-15484,-14972,-14460,-13948,-13436,-12924,-12412,
            -11900,-11388,-10876,-10364,-9852,-9340,-8828,-8316,
            -7932,-7676,-7420,-7164,-6908,-6652,-6396,-6140,
            -5884,-5628,-5372,-5116,-4860,-4604,-4348,-4092,
            -3900,-3772,-3644,-3516,-3388,-3260,-3132,-3004,
            -2876,-2748,-2620,-2492,-2364,-2236,-2108,-1980,
            -1884,-1820,-1756,-1692,-1628,-1564,-1500,-1436,
            -1372,-1308,-1244,-1180,-1116,-1052,-988,-924,
            -876,-844,-812,-780,-748,-716,-684,-652,
            -620,-588,-556,-524,-492,-460,-428,-396,
            -372,-356,-340,-324,-308,-292,-276,-260,
            -244,-228,-212,-196,-180,-164,-148,-132,
            -120,-112,-104,-96,-88,-80,-72,-64,
            -56,-48,-40,-32,-24,-16,-8,0,
            32124,31100,30076,29052,28028,27004,25980,24956,
            23932,22908,21884,20860,19836,18812,17788,16764,
            15996,15484,14972,14460,13948,13436,12924,12412,
            11900,11388,10876,10364,9852,9340,8828,8316,
            7932,7676,7420,7164,6908,6652,6396,6140,
            5884,5628,5372,5116,4860,4604,4348,4092,
            3900,3772,3644,3516,3388,3260,3132,3004,
            2876,2748,2620,2492,2364,2236,2108,1980,
            1884,1820,1756,1692,1628,1564,1500,1436,
            1372,1308,1244,1180,1116,1052,988,924,
            876,844,812,780,748,716,684,652,
            620,588,556,524,492,460,428,396,
            372,356,340,324,308,292,276,260,
            244,228,212,196,180,164,148,132,
            120,112,104,96,88,80,72,64,
            56,48,40,32,24,16,8,0,
        ]
        samples = []
        for byte in mulaw_data:
            samples.append(MULAW_DECODE_TABLE[byte])
        pcm = struct.pack(f"<{len(samples)}h", *samples)
        if from_rate != to_rate:
            ratio = to_rate / from_rate
            new_len = int(len(samples) * ratio)
            new_samples = []
            for i in range(new_len):
                src = i / ratio
                idx = int(src)
                if idx >= len(samples) - 1:
                    new_samples.append(samples[-1])
                else:
                    frac = src - idx
                    new_samples.append(int(samples[idx] * (1 - frac) + samples[idx + 1] * frac))
            pcm = struct.pack(f"<{len(new_samples)}h", *new_samples)
        return pcm


def pcm_to_mulaw(pcm_data, from_rate, to_rate):
    if audioop:
        if from_rate != to_rate:
            pcm_data, _ = audioop.ratecv(pcm_data, 2, 1, from_rate, to_rate, None)
        return audioop.lin2ulaw(pcm_data, 2)
    else:
        import struct
        if from_rate != to_rate:
            ratio = to_rate / from_rate
            num_samples = len(pcm_data) // 2
            samples = struct.unpack(f"<{num_samples}h", pcm_data)
            new_len = int(num_samples * ratio)
            new_samples = []
            for i in range(new_len):
                src = i / ratio
                idx = int(src)
                if idx >= num_samples - 1:
                    new_samples.append(samples[-1])
                else:
                    frac = src - idx
                    new_samples.append(int(samples[idx] * (1 - frac) + samples[idx + 1] * frac))
            pcm_data = struct.pack(f"<{len(new_samples)}h", *new_samples)
        MULAW_BIAS = 0x84
        MULAW_MAX = 0x7FFF
        MULAW_CLIP = 32635
        num_samples = len(pcm_data) // 2
        samples = struct.unpack(f"<{num_samples}h", pcm_data)
        result = bytearray(num_samples)
        for i, sample in enumerate(samples):
            sign = 0
            if sample < 0:
                sign = 0x80
                sample = -sample
            if sample > MULAW_CLIP:
                sample = MULAW_CLIP
            sample = sample + MULAW_BIAS
            exponent = 7
            mask = 0x4000
            while exponent > 0 and not (sample & mask):
                exponent -= 1
                mask >>= 1
            mantissa = (sample >> (exponent + 3)) & 0x0F
            result[i] = ~(sign | (exponent << 4) | mantissa) & 0xFF
        return bytes(result)


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
                        "html": f"<h2>New Call Received</h2><p><strong>Business:</strong> {config['business_name']}</p><p><strong>Caller:</strong> {caller}</p><p><strong>Duration:</strong> {duration}s</p><p><strong>Time:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</p><p><a href=\"{DASHBOARD_WEBHOOK_URL}\">View Dashboard</a></p>",
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
    # Load persisted data
    load_businesses()
    load_call_log()

    # Auto-register demo business if none exist
    if not business_configs:
        business_configs["+14235563838"] = {
            "business_name": "RapidTow Atlanta",
            "agent_name": "Aria",
            "industry": "towing",
            "owner_email": DEFAULT_OWNER_EMAIL,
            "owner_phone": "",
            "greeting": "",
            "voice": "Kore",
            "notify_sms": True,
            "notify_email": True,
        }
        save_businesses()
        print("Auto-registered demo business: RapidTow Atlanta")

    asyncio.create_task(keep_alive())
    print("Aria Voice AI started!")
    print(f"Businesses loaded: {len(business_configs)}")
    print(f"Twilio configured: {bool(twilio_client)}")
    print(f"Gemini API Key: {'yes' if GOOGLE_API_KEY else 'no'}")
    print(f"Resend API Key: {'yes' if RESEND_API_KEY else 'no'}")
    print(f"Dashboard webhook: {DASHBOARD_WEBHOOK_URL or 'Not configured'}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 5050)))
