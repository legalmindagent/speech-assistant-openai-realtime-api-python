# Multi-Industry AI Voice Agent

> A voice AI receptionist that answers phone calls 24/7 for small businesses across 10+ industries. Powered by Google Gemini Live API, Twilio, and FastAPI.

## Live URLs

| Service | URL |
|---------|-----|
| **Voice Backend (Render)** | https://voice-agent-backend-y0t9.onrender.com |
| **Dashboard (Vercel)** | https://nextjs-postgres-nextauth-tailwindcs-taupe.vercel.app |
| **Phone Number** | +1 (423) 556-3838 |

## How It Works

1. Caller dials the Twilio phone number
2. Twilio sends TwiML response connecting to a WebSocket stream
3. Backend receives audio from Twilio (mulaw 8kHz), converts to PCM 16kHz
4. Audio is streamed to Google Gemini Live API for real-time conversation
5. Gemini responds with audio (PCM 24kHz), which is converted back to mulaw 8kHz
6. Converted audio is streamed back to the caller via Twilio

## Supported Industries

| Industry | AI Persona | Specialty |
|----------|-----------|-----------|
| HVAC | Sarah from Comfort Air | Emergency/routine scheduling |
| Dental | Emily from Bright Smile | Appointments, insurance intake |
| Real Estate | Jessica from Premier Properties | Lead qualification |
| Plumbing | Mike from Reliable Plumbing | Emergency dispatch |
| Pest Control | Lisa from Shield Pest Control | Severity assessment |
| Roofing | Tom from Summit Roofing | Damage/inspection scheduling |
| Auto Repair | Chris from AutoCare Plus | Vehicle diagnostics intake |
| Veterinary | Amy from CareFirst Animal | Pet emergency triage |
| Electrical | Dana from PowerPro Electric | Safety-first dispatch |
| Home Cleaning | Sandra from Spotless Home | Quote and scheduling |

## Tech Stack

- **Voice AI**: Google Gemini 2.0 Flash Live API (free tier)
- **Telephony**: Twilio Voice + Media Streams (WebSocket)
- **Backend**: FastAPI + Uvicorn (Python)
- **Audio**: mulaw/PCM conversion via audioop-lts
- **Hosting**: Render (free tier)
- **Dashboard**: Next.js + Vercel + Neon Postgres

## Environment Variables

| Variable | Description | Where to Set |
|----------|-------------|-------------|
| GEMINI_API_KEY | Google AI Studio API key | Render Dashboard > Environment |
| TWILIO_ACCOUNT_SID | Twilio Account SID | Future: for outbound features |
| TWILIO_AUTH_TOKEN | Twilio Auth Token | Future: for outbound features |

## Setup Instructions

### 1. Clone and Configure
```bash
git clone https://github.com/legalmindagent/speech-assistant-openai-realtime-api-python.git
cd speech-assistant-openai-realtime-api-python
cp .env.example .env
# Add your GEMINI_API_KEY to .env
```

### 2. Run Locally
```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 5050
```

### 3. Deploy to Render
- Connect GitHub repo to Render
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Add GEMINI_API_KEY environment variable

### 4. Configure Twilio
- Go to Twilio Console > Phone Numbers > Active Numbers
- Set Voice webhook to: `https://your-render-url.onrender.com/incoming-call`
- Method: HTTP POST

## Sharing the Dashboard

The dashboard is publicly accessible at:
**https://nextjs-postgres-nextauth-tailwindcs-taupe.vercel.app**

To add a custom domain:
1. Go to Vercel > Project Settings > Domains
2. Add your domain (e.g., dashboard.yourbusiness.com)
3. Update DNS records as instructed by Vercel

---

## ROADMAP: Making This Best-in-Market

### Phase 1: Core Polish (Week 1-2)
- [ ] **Custom dashboard**: Replace generic template with voice-agent-specific dashboard showing call logs, industry breakdown, caller analytics
- [ ] **Call logging**: Store every call in database (caller number, industry, duration, transcript, timestamp)
- [ ] **Voicemail/fallback**: If Gemini fails, play a fallback message and record voicemail
- [ ] **Warm transfer**: Option to transfer caller to a live human after AI intake
- [ ] **SMS follow-up**: Send caller a text summary after the call via Twilio SMS
- [ ] **Better TTS voice**: Upgrade to ElevenLabs or Cartesia for more natural voice output

### Phase 2: Multi-Tenant & Business Features (Week 3-4)
- [ ] **Multi-tenant system**: Each business gets their own phone number, custom greeting, custom persona
- [ ] **Business onboarding wizard**: Web form where a new business signs up, picks industry, customizes AI persona
- [ ] **Custom prompts per business**: Store per-business system prompts in database
- [ ] **Appointment booking**: Integrate with Google Calendar, Calendly, or custom booking system
- [ ] **CRM integration**: Push lead data to HubSpot, Salesforce, or GoHighLevel
- [ ] **Webhook notifications**: Real-time alerts to business owner (email, SMS, Slack) when a call comes in

### Phase 3: Intelligence & Analytics (Week 5-6)
- [ ] **Call transcription**: Full call transcripts stored and searchable
- [ ] **Sentiment analysis**: Detect caller mood and urgency
- [ ] **Lead scoring**: AI rates each caller as hot/warm/cold lead
- [ ] **Analytics dashboard**: Charts showing calls per day, industry breakdown, average call duration, conversion rates
- [ ] **A/B testing prompts**: Test different AI personas and measure which converts better
- [ ] **Call recording**: Record calls for quality review (with consent)

### Phase 4: Scale & Monetization (Week 7-8)
- [ ] **Stripe billing**: Monthly subscription per business ($49-299/mo based on call volume)
- [ ] **Usage metering**: Track minutes used per business for tiered pricing
- [ ] **White-label option**: Businesses can brand the AI as their own
- [ ] **API access**: Let businesses integrate via REST API
- [ ] **Multiple languages**: Spanish, French, etc. via Gemini multilingual support
- [ ] **Outbound calling**: AI makes follow-up calls to leads
- [ ] **IVR menu**: Press 1 for HVAC, Press 2 for Plumbing, etc.

### Phase 5: Enterprise & Differentiation (Month 3+)
- [ ] **Fine-tuned models**: Train on real call data for each industry
- [ ] **Knowledge base per business**: Upload FAQs, pricing sheets, service areas
- [ ] **Smart routing**: Route calls to different AI agents based on time of day, caller history
- [ ] **Compliance**: HIPAA mode for dental/veterinary, call recording consent
- [ ] **Mobile app**: Business owner app showing real-time call dashboard
- [ ] **Competitor analysis**: Benchmark against Smith.ai, Ruby, Dialpad AI

### What Makes This Best-in-Market
1. **10 industries on day one** - most competitors focus on one vertical
2. **Free tier possible** - Gemini Live API is free, Render free tier, Twilio pay-per-use
3. **Real-time voice** - not robotic IVR, actual conversational AI
4. **Instant setup** - business can be live in under 5 minutes
5. **Open source core** - businesses trust what they can inspect
6. **Per-industry personas** - not generic, each industry gets specialized intake

## File Structure

```
speech-assistant-openai-realtime-api-python/
  main.py              # FastAPI server + Gemini Live API integration
  requirements.txt     # Python dependencies
  .env.example         # Environment variable template
  Readme.md            # This file
```

## Related Repos

- **Dashboard**: https://github.com/legalmindagent/nextjs-postgres-nextauth-tailwindcss-template
- **Vercel Dashboard**: https://nextjs-postgres-nextauth-tailwindcs-taupe.vercel.app

## License

MIT
