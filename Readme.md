# Aria Voice AI

AI-powered phone receptionist for service businesses. Answers calls, collects customer info, and notifies business owners — all powered by Google Gemini 2.0 Flash.

## Features

- **AI Phone Receptionist** — Natural voice conversations powered by Gemini 2.0 Flash Live API
- **13 Industry Personas** — HVAC, Dental, Real Estate, Plumbing, Pest Control, Roofing, Auto Repair, Veterinary, Electrical, Home Cleaning, Towing, Locksmith, General
- **Per-Business Configuration** — Each Twilio number maps to a unique business with custom greetings
- **SMS Notifications** — Instant text alerts to business owners when calls come in
- **Email Notifications** — Call summaries sent via Resend email API
- **Dashboard Webhook** — POST call data to your dashboard for logging and analytics
- **Active Call Tracking** — Real-time monitoring of ongoing calls
- **Keep-Alive** — Automatic ping every 5 minutes to prevent Render free tier sleep

## Architecture

```
Caller --> Twilio --> /incoming-call (TwiML) --> WebSocket /media-stream
                                                    |
                                          Twilio Audio (8kHz mulaw)
                                                    |
                                          PCM conversion (16kHz)
                                                    |
                                          Gemini 2.0 Flash Live API
                                                    |
                                          AI Audio Response (24kHz PCM)
                                                    |
                                          mulaw conversion (8kHz)
                                                    |
                                          Back to Caller via Twilio
```

## Quick Start

1. Clone this repo
2. Copy `.env.example` to `.env` and fill in your API keys
3. Install dependencies: `pip install -r requirements.txt`
4. Run: `python main.py`
5. Configure your Twilio number webhook to point to `https://your-domain/incoming-call`

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Status page |
| `/health` | GET | Health check with active call count |
| `/active-calls` | GET | List active calls |
| `/businesses` | GET | List registered businesses |
| `/register-business` | POST | Register/update a business config |
| `/incoming-call` | POST | Twilio webhook for incoming calls |
| `/media-stream` | WS | WebSocket for Twilio media stream |
| `/send-email` | POST | Send email notification |
| `/log-client` | POST | Log client information |

## Register a Business

```bash
curl -X POST https://your-domain/register-business \
  -H "Content-Type: application/json" \
  -d '{
    "twilio_number": "+14235563838",
    "business_name": "RapidTow Atlanta",
    "agent_name": "Jake",
    "industry": "towing",
    "owner_email": "owner@example.com",
    "owner_phone": "+15551234567",
    "greeting": "Thanks for calling RapidTow! Need a tow or roadside help?",
    "notify_sms": true,
    "notify_email": true
  }'
```

## Deployment

Deployed on **Render** with auto-deploy from GitHub main branch.

Live at: `voice-agent-backend-y0t9.onrender.com`

## Tech Stack

- **Python / FastAPI** — Backend server
- **Google Gemini 2.0 Flash** — Live voice AI (free tier)
- **Twilio** — Phone number and voice routing
- **Resend** — Email notifications
- **Render** — Hosting (free tier)
