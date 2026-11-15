# CareMe 🩺
> **"Care from anywhere. Connected by CareMe."**

CareMe is a production-grade, remote elderly healthcare and family collaboration web application designed for families caring for aging parents across cities and time zones. Built with **FastAPI**, **Jinja2**, **Tailwind CSS**, **SQLAlchemy (PostgreSQL & SQLite)**, **APScheduler (Asia/Kolkata)**, **Google Gemini 2.5 Flash**, **ReportLab**, and a **Progressive Web App (PWA)** architecture.

---

## 📌 Problem

Millions of families live across different cities or countries while their aging parents live independently in their hometowns (for example, Lakshmi living alone in Coimbatore while her son Arun lives in Chennai and daughter Priya in Bengaluru).

- **Medication Non-Adherence**: Seniors frequently forget morning doses or mix up instructions, leading to preventable hospitalizations.
- **Remote Family Anxiety**: Adult children constantly worry whether their parent took their morning pills, leading to invasive, stressful phone calls.
- **Privacy vs. Care Friction**: Elders value their independence and feel disempowered when family members monitor them without consent.
- **Rushed Doctor Visits**: Families struggle to compile a clear adherence history, missed dose logs, and relevant questions ahead of doctor consultations.

---

## 💡 Solution

CareMe bridges distance with compassionate, secure technology:
1. **Dignified Senior UX**: High-contrast typography, large tactile touch targets (72px), 4-digit PIN access, and Web Speech routine reading.
2. **Elder-Controlled Access**: Seniors retain absolute authority over their health data. Family and caregivers can only view or manage what the elder explicitly approves.
3. **Automated Escalation Engine**: APScheduler monitors doses quietly in Indian Standard Time (`Asia/Kolkata`). Alerts escalate gently (30 min check-in, 120 min circle notification).
4. **Remote Care Confidence Engine**: A pure Python 0–100 score synthesizing adherence consistency, streak stability, time patterns, and upcoming appointments into respectful, non-alarming guidance.
5. **AI Clinical Assistant & Prescription Scanner**: Powered by Google Gemini 2.5 Flash to transcribe paper prescriptions, draft weekly family briefings, and prepare structured questions for doctor appointments.
6. **1-Click Doctor Consultation PDF**: Instantly compiles a ReportLab clinical summary for clinic consultations with Dr. Ramesh.
7. **Production Security & PWA**: CSRF token validation on all mutations, rate-limited logins, 30-minute password reset links, full data deletion, installable PWA with offline fallback, and responsive mobile navigation.

---

## 🚀 Modes: Production Mode vs. Demo Mode

CareMe supports a seamless toggle via the `DEMO_MODE` environment variable:

### 1. Production Mode (`DEMO_MODE=false`)
- **Safe Empty Database**: A fresh database starts completely empty. Pre-seeded hackathon accounts (Lakshmi, Arun, Priya, Meena) are **never** seeded.
- **Strict Security Enforced**:
  - The server **refuses to start** if `SECRET_KEY` is missing or default.
  - Session cookies automatically acquire the `Secure` flag on HTTPS connections.
  - Password minimum requirement of 8 characters is strictly enforced.
  - `/demo` simulation endpoint returns `404 Not Found`.
  - Persona switcher bar and "1-Click Demo Login" tabs are completely removed from the UI.
- **Self-Service Real User Onboarding**:
  - **Elder Registration**: Elders register, receive their unique 6-digit Care Passcode, and are guided through a short, skippable onboarding wizard (`/onboarding/elder`) to configure their first medication and emergency contact.
  - **Family & Caregiver Registration**: Enter the elder's 6-digit Care Passcode to join. Their account enters a `pending` state with zero access until approved by the elder.

### 2. Hackathon / Demo Mode (`DEMO_MODE=true`)
- Pre-seeds Lakshmi, Arun, Priya, and Meena with full 7-day adherence history and doctor appointments.
- Enables the top navbar **Persona Switcher** and **1-Click Demo Login** buttons.
- Enables the interactive `/demo` control center to test Gmail alerts and simulate 30m / 120m dose escalations.
- You can manually seed the demo circle at any time by running:
  ```bash
  python seed_demo.py
  ```

---

## 👥 Demo Personas & Pre-configured Accounts

When `DEMO_MODE=true`, use the **1-Click Persona Switcher** in the top navigation bar or on the login page:

| Persona | Role | Location | Login Method | Key Focus Experience |
|---|---|---|---|---|
| **Lakshmi** | Elder (Age 75) | Coimbatore | **PIN: `1234`** or `lakshmi@caresync.ai` | Senior high-contrast UI, Web Speech voice reader, 1-tap dose confirm, 72px buttons, SOS |
| **Arun** | Son (Family) | Chennai | `arun@caresync.ai` / `password123` | Remote adherence oversight (~86%), morning miss pattern, GPS home zone |
| **Priya** | Daughter (Family) | Bengaluru | `priya@caresync.ai` / `password123` | Care circle collaboration, doctor accompaniment RSVP |
| **Meena** | Caregiver | Coimbatore | `meena@caresync.ai` / `password123` | Shift checklist, vitals recording (BP, Glucose, Pulse) |

*Care Circle Passcode: **`482915`***

---

## 🛡️ Security, Privacy & Compliance

- **Rate Limiting**: Defends against brute-force attacks by locking an account or IP for 5 minutes after 5 consecutive failed login attempts.
- **CSRF Protection**: All `POST` forms and AJAX mutating requests (`fetch`) are protected by cryptographic CSRF tokens (`X-CSRF-Token` header).
- **Session Cookie Hardening**: `HttpOnly`, `SameSite=Lax`, and conditional `Secure` flag (applied on production HTTPS; keeps local `http://127.0.0.1` development functional).
- **Single-Use Password Reset**: Forgot password flow dispatches a 30-minute expiration token tied to the user's password state—preventing replay attacks.
- **Right to be Forgotten (GDPR / Data Deletion)**: Under `/settings`, users can permanently delete their account and associated health records with cascading cleanup.
- **Mandatory Medical Disclaimer**: Registration requires explicit agreement:
  > *"I understand CareMe is not a medical device, does not give medical advice and does not replace emergency services (112)."*
- **Privacy Notice**: Comprehensive data handling notice available at `/privacy`.

---

## 📱 Mobile, Tablet & PWA Architecture

- **Responsive Viewport**: Verified for 360px (mobile), 768px (tablet), and 1280px+ (desktop) screens with `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`.
- **Elder Bottom Navigation**: Fixed bottom navigation bar on mobile for seniors with direct 1-tap access to *Medicines*, *Doctor*, *Family*, and a red *SOS* trigger.
- **Family Mobile Drawer**: Responsive slide-out hamburger navigation menu for family members and caregivers.
- **Touch-Friendly Targets**: Inputs and interactive elements maintain $\ge 48$px touch heights; elder dashboard buttons are enlarged to 72px (`.elder-btn`).
- **iOS Zoom Prevention**: Mobile form inputs are set to `16px` font size to prevent iOS Safari from automatically zooming the viewport on focus.
- **Progressive Web App (PWA)**:
  - `manifest.json` configured with brand theme `#0F2A4A`, background `#F4F8FB`, and icons (192px, 512px).
  - Background Service Worker (`service-worker.js`) caches static assets for rapid loading.
  - Dedicated offline fallback page (`/offline`) featuring instant 112 emergency calling when connectivity drops.
  - Native "Add to Home Screen" installation banner on mobile devices.
- **Camera Prescription Capture**: Built-in WebRTC camera modal (`getUserMedia`) with automatic fallback to `<input type="file" capture="environment">` on mobile browsers.

---

## ⏰ Timezone & Database Support

- **Explicit `Asia/Kolkata` (IST) Engine**: Production cloud providers (Render, AWS, GCP) operate servers in UTC. CareMe runs all scheduling triggers, escalation windows, dose checks, and UI timestamps explicitly in `Asia/Kolkata` (Indian Standard Time).
- **Database Flexibility**: Reads `DATABASE_URL` from `.env`:
  - **SQLite** (default): `sqlite:///./caresync.db`
  - **PostgreSQL**: `postgresql://user:password@hostname:5432/dbname` (automatically handles cloud connection strings starting with `postgres://`).

---

## 🧠 Core Application Features

### 1. Elder Mode (Lakshmi)
- **Senior-Friendly Large Format UI**: Designed specifically for senior eyes and fingers with large touch buttons.
- **Easy 4-Digit PIN Access**: Log in in seconds with `1234` without typing passwords.
- **Voice Routine Assistant**: Uses HTML5 Web Speech API to read aloud today's doses and doctor appointments in Indian English.
- **Prominent Emergency SOS**: Instant trigger with audio alarm, coordinates capture, and family escalation.

### 2. Family Command Center (Arun & Priya)
- **7-Day Adherence Analytics**: Interactive visual trend chart tracking daily taken vs unconfirmed doses.
- **Health Pattern Intelligence**: Identifies that misses predominantly occur during morning routines (8:00 AM – 10:00 AM Metformin) and suggests scheduling a relaxed morning tea call.
- **Simulated GPS Location Tracking**: Displays residence safety zone, status, and battery levels (respects elder permission).
- **Doctor Consultation Sync**: Real-time consultation details for **Dr. Ramesh, Cardiologist at KG Hospital, Coimbatore** with family accompaniment RSVP.

### 3. Caregiver Workspace (Meena)
- **Shift Checklist**: Step-by-step task flow for morning vitals, breakfast tablets, and clinic preparation.
- **Vitals Logger**: Quick recording for Blood Pressure, Blood Sugar, and Pulse.

### 4. Background Escalation Engine (APScheduler)
- **At Dose Time**: Friendly reminder sent to the elder only.
- **30-Minute Check-in**: If still unconfirmed after 30 minutes (`ESCALATE_1_MIN`), notifies members with `can_receive_alerts` using gentle wording: *"Medication was not confirmed at 8:00 AM. This doesn't always mean it was missed. Please check in."*
- **120-Minute Circle Escalation**: If unconfirmed after 2 hours (`ESCALATE_2_MIN`), marks status as `not_confirmed` and alerts the whole circle.
- **24-Hour & 2-Hour Appointment Reminders**: Alerts family ahead of clinic appointments.
- **Real Email Delivery**: HTML email via Gmail SMTP (STARTTLS) with console fallback when credentials are not configured.

### 5. Elder-Controlled Access & Privacy Matrix
- **Zero-Access Pending State**: Joining with the 6-digit Care Passcode creates a pending membership with all permissions revoked (`False`).
- **Elder Approval Card**: Elder dashboard features a prominent pending request card with tactile **Approve** and **Decline** buttons.
- **Live AJAX Permission Matrix**: On `/circle`, the elder can toggle 6 granular permissions (*View health records*, *Edit medicines*, *Edit appointments*, *Receive alerts*, *View location*, *Manage access*).
- **Strict Server-Side Enforcement**: All routes (`/dashboard`, `/medicines`, `/appointments`, `/location`, `/assistant`) check permissions on the backend. Unauthorized members receive a friendly *"Lakshmi has not shared this with you"* notice.

### 6. Gemini Prescription Scanner (`gemini-2.5-flash`)
- **Camera & File Dropzone**: Accepts photos from smartphone cameras (`capture="environment"`) or JPG/PNG files on `/medicines/add`.
- **Strict Clinical Transcription**: Parses medicine names, dosages, durations, and instructions into strict JSON. Unreadable text is marked `"unclear"`.
- **Interactive Review Table**: **Nothing is saved until the user clicks "Confirm & Save All to Schedule"**. Displays the clinical notice: *"Please verify with your doctor's prescription"*. Automatically maps `morning` $\rightarrow$ `08:00`, `afternoon` $\rightarrow$ `14:00`, `evening` $\rightarrow$ `18:00`, `night` $\rightarrow$ `21:00`, generates dose logs, and logs to `activity_log`.

### 7. Remote Care Confidence Engine (`services/confidence.py`)
- **Algorithmic 0–100 Score**: Computed in pure Python (no AI) from 5 clinical factors:
  1. 7-day confirmation rate (up to 40 pts)
  2. Consecutive unconfirmed doses (up to 25 pts)
  3. Time-of-day pattern (up to 15 pts)
  4. Hours since last circle activity (up to 10 pts)
  5. Upcoming appointments (up to 10 pts)
- **Respectful, Non-Alarming Labels**: Categorized as **"All good"** ($\ge 85$), **"Worth a check-in"** ($65-84$), or **"Please reach out"** ($<65$).

### 8. Gemini Family Communication & Weekly Summaries (`services/gemini_service.py`)
- **Facts-Only Prompting**: Sends ONLY objective numbers to `gemini-2.5-flash` to write a warm 2–3 paragraph weekly summary.
- **Clinical Guardrails**: Strictly forbids prescribing, changing dosages, suggesting stopping medications, or diagnosing illnesses. Always directs medical questions to the doctor.
- **Zero-Crash Resilience**: Seamlessly falls back to rule-based clinical text if the API key is not configured or network is offline.

### 9. "Ask CareMe" Schedule Assistant (`/assistant`)
- **Interactive Schedule Chat Box**: Answers questions based strictly on the elder's recorded logs (e.g. *"How was my mother's week?"*).
- **Doctor Consultation Prep**: Formulates structured questions to ask Dr. Ramesh during clinic appointments.
- **Server-Side Security**: Verifies `can_view_health` on both page render and chat POST endpoints.

### 10. Clinical Doctor Report PDF (`reportlab`)
- **1-Click PDF Export**: Generates a clinical consultation document using ReportLab.
- **Comprehensive Summary**: Patient metadata, adherence gauges, prescription regimen table, pattern notes, and doctor discussion points.
- **Direct Download**: Prominent **"Download Doctor Report (PDF)"** buttons on both the Family Dashboard and Assistant page.

---

## 🛠️ Tech Stack

- **Backend**: Python 3.10+, FastAPI, Starlette, Uvicorn
- **Database & ORM**: PostgreSQL (`psycopg2-binary`) or SQLite (`caresync.db`), SQLAlchemy
- **Scheduling & Escalations**: APScheduler (configured to `Asia/Kolkata` timezone)
- **AI & Vision**: Google Gemini Python SDK (`google-genai`), model `gemini-2.5-flash`
- **PDF Generation**: ReportLab
- **Security**: Passlib (Bcrypt), HMAC CSRF tokens, in-memory rate limiting
- **Templating & UI**: Jinja2, Tailwind CSS (via CDN), FontAwesome 6.5
- **Mobile & PWA**: Web App Manifest, Service Worker, WebRTC MediaDevices, HTML5 Web Speech API

---

## 🚀 Setup & Local Quick Start

### 1. Clone & Install
```bash
git clone https://github.com/your-username/careme.git
cd careme
pip install -r requirements.txt
```

### 2. Configure Environment
```bash
cp .env.example .env
```
*(Optionally populate `GEMINI_API_KEY` for live prescription scanning and `SMTP_USER`/`SMTP_PASS` for live Gmail dispatch).*

### 3. Run Application
```bash
uvicorn main:app --reload
```
Open **`http://127.0.0.1:8000`** in your browser.

> **Database Seeding**:
> - When `DEMO_MODE=true`: An empty database auto-seeds the demo circle on startup. You can re-seed at any time with `python seed_demo.py`.
> - When `DEMO_MODE=false`: The database starts empty for real user registrations.

---

## ☁️ Deployment on Render

CareMe is pre-configured for seamless Render deployment:

1. **Repository**: Push this repository to GitHub/GitLab.
2. **New Web Service**: Create a new Web Service on [Render](https://render.com).
3. **Build Command**: `pip install -r requirements.txt`
4. **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. **Environment Variables**:

| Variable | Description | Default / Example | Production Required |
|---|---|---|---|
| `DEMO_MODE` | Toggle Demo Mode vs Production Mode | `true` | Set to `false` in production |
| `SECRET_KEY` | Flask/Session secret key | Auto / Random | **YES** (server refuses to start if missing when `DEMO_MODE=false`) |
| `DATABASE_URL` | SQLAlchemy database URL | `sqlite:///./caresync.db` | Use PostgreSQL for production (`postgresql://...`) |
| `TIMEZONE` | Operational timezone | `Asia/Kolkata` | `Asia/Kolkata` |
| `ESCALATE_1_MIN` | Unconfirmed dose check-in threshold (minutes) | `30` | Optional |
| `ESCALATE_2_MIN` | Critical care circle escalation threshold (minutes) | `120` | Optional |
| `SMTP_USER` | Gmail address for dispatching notifications | `""` | Optional (logs to console if omitted) |
| `SMTP_PASS` | 16-character Gmail App Password | `""` | Optional |
| `SMTP_HOST` | SMTP server host | `smtp.gmail.com` | Optional |
| `SMTP_PORT` | SMTP STARTTLS port | `587` | Optional |
| `TEST_EMAIL` | Target email for `/demo` simulations | `""` | Optional |
| `GEMINI_API_KEY` | Google Gemini API key | `""` | Optional (rule-based fallback active if omitted) |
| `GEMINI_MODEL` | Google Gemini model name | `gemini-2.5-flash` | Optional |
| `PORT` | Web server listening port | `8000` | Render sets `$PORT` automatically |
| `DEBUG` | Enable debug logs | `True` | Set `False` in production |

---

## 🔒 Safety, Medical Notice & Privacy

- **Elder Sovereignty**: Elders maintain full control over Care Circle memberships. Any member joining with the 6-digit passcode begins in a locked `pending` state with zero access until the elder taps **Approve**.
- **Server-Side Enforcement**: Route protection is enforced in FastAPI backend dependencies. Restricted members receive friendly explanations (`"<Elder> has not shared this with you"`).
- **Non-Alarming Language**: Confidence scoring, email notifications, and AI summaries avoid panicky or emergency jargon. Check-in reminders use warm, caring phrasing (e.g. *"Metformin was not confirmed at 8:00 AM. This doesn't always mean it was missed. Please check in."*).
- **Doctor Consultation Guardrails**: Gemini system prompts strictly prevent prescribing, diagnosing, or altering medication doses. Observational data is meant to facilitate clinical conversations with licensed physicians.
- **Emergency Services Notice**: **CareMe does not provide medical advice and does not replace emergency services (112).** In acute health emergencies, users are instructed to dial emergency services immediately.
