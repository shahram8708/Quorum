# 🌍 Quorum

### *The civic action platform where real projects get built by real teams — powered by AI, grounded in community.*

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.x-000000?style=flat-square&logo=flask&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-ORM-red?style=flat-square)
![Gemini AI](https://img.shields.io/badge/Google_Gemini-2.5_Flash-4285F4?style=flat-square&logo=google&logoColor=white)
![Razorpay](https://img.shields.io/badge/Razorpay-Payments-02042B?style=flat-square)
![License](https://img.shields.io/badge/License-Not_specified-lightgrey?style=flat-square)
![Last Commit](https://img.shields.io/badge/Last_Commit-April_2026-brightgreen?style=flat-square)

---

## 📋 Table of Contents

- [About the Project](#-about-the-project)
- [Key Features](#-key-features)
- [Tech Stack](#-tech-stack)
- [Project Structure](#-project-structure)
- [Getting Started](#-getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Environment Variables](#environment-variables)
  - [Running the Project](#running-the-project)
- [Usage](#-usage)
- [API / Route Documentation](#-route-documentation)
- [Configuration](#-configuration)
- [Testing](#-testing)
- [Deployment](#-deployment)
- [Contributing](#-contributing)
- [Roadmap](#-roadmap)
- [License](#-license)
- [Acknowledgements](#-acknowledgements)
- [Contact / Author](#-contact--author)

---

## 🧭 About the Project

Most civic passion dies on social media — people share problems, get 200 likes, and nothing changes. Quorum exists to close that gap. It's a platform where individuals and organisations turn civic intent into structured, team-based action: real projects with defined roles, milestones, tasks, and measurable outcomes.

Quorum is built for independent changemakers who want to do more than rant online, for nonprofits and NGOs looking to source skilled volunteers without the overhead, and for community builders who need infrastructure to coordinate people across a shared goal. Projects span domains from environment and education to healthcare and urban infrastructure.

What sets Quorum apart is its AI backbone — powered by Google Gemini 2.5 Flash — which helps creators write better project descriptions, suggests team roles automatically, validates whether a project's scope is realistic, and surfaces a live "civic pulse" personalised to each user's city and interests. It's not a social network with a project tab bolted on; it was designed from the ground up as a project-execution platform that happens to have community features.

---

## ✨ Key Features

- **6-step project creation wizard** that walks creators from problem statement through to role definition and skill tagging, with session-persisted drafts so nothing is lost mid-way.
- **AI-assisted project scoping** using Gemini 2.5 Flash: enhances project descriptions, detects over/under-scoped success definitions, and auto-suggests team roles based on the project domain and problem.
- **Skill-based contributor matching** that scores available users against open roles using skill overlap, reputation, project history, and geographic proximity (Haversine distance).
- **Minimum Viable Team (MVT) detection** that automatically transitions a project from `assembling` → `launch_ready` status and fires off email + in-app notifications the moment the minimum team threshold is met.
- **Kanban task board** with drag-and-drop status transitions (`todo` → `in_progress` → `review` → `done`), per-task priority levels, assignees, and due dates.
- **Civic Challenges marketplace** where organisations post grant-backed civic challenges (with INR grant amounts, eligibility, evaluation criteria) and community members submit project proposals individually or as teams.
- **Organisation dashboard** with a separate account type, challenge credit system, and ability to offer support to existing community projects.
- **Reputation engine** with time-decayed, weighted peer ratings across three axes: follow-through, collaboration, and quality — requiring a minimum of three ratings before a score is displayed.
- **Personalised civic pulse** — a daily-refreshed AI digest (cached per user) summarising civic news and active stories relevant to the user's city and domain interests.
- **Action templates library** that automatically converts completed successful projects into reusable templates, preserving roles, milestones, tasks, and lessons learned for others to clone.
- **Weekly email digest** sent every Monday to all active project team members summarising tasks due, tasks completed, overdue items, and upcoming milestones.
- **Admin panel** with analytics dashboards, blog CMS (with categories, tags, rich-text editor, SEO metadata, and publish workflow), user management, organisation verification, and flagged project review.
- **Razorpay billing** with four subscription tiers (Free, Creator Pro, Org Starter, Org Team) including webhook handling and payment verification.
- **AWS S3 file storage** with presigned URLs for secure file delivery, with a local filesystem fallback for development.
- **Rate limiting and CSRF protection** baked in via Flask-Limiter and Flask-WTF, with secure session configuration out of the box.
- **Auto-bootstrap on startup**: database tables, admin user, and seed data (skills taxonomy + sample projects) are created automatically on first run.

---

## 🛠 Tech Stack

### Backend
| Technology | Role |
|---|---|
| Python 3.10+ | Core language |
| Flask | Web framework |
| Flask-SQLAlchemy | ORM / database layer |
| Flask-Migrate | Database migrations (Alembic) |
| Flask-Login | Session-based authentication |
| Flask-WTF | Form validation and CSRF protection |
| Flask-Mail | Transactional email delivery |
| Flask-Limiter | Route-level rate limiting |
| APScheduler | Background job scheduling (weekly digest, daily civic pulse) |
| Gunicorn | WSGI production server |
| bcrypt | Password hashing (12 rounds) |
| itsdangerous | Token signing for email verification and password reset |
| bleach | HTML sanitisation |
| python-magic | MIME type detection for uploads |
| Pillow | Image processing |

### AI / External Services
| Technology | Role |
|---|---|
| Google Gemini 2.5 Flash (`google-genai`) | AI features: description enhancement, scope validation, role suggestion, recommendations, outcome drafting, civic pulse, challenge discovery |
| Razorpay | Payment processing (INR, order creation, webhook verification) |
| AWS S3 / boto3 | File storage with presigned URL delivery |
| Google Maps API | Optional geolocation enrichment |
| Sentry | Optional error tracking (DSN configurable) |

### Frontend
| Technology | Role |
|---|---|
| Jinja2 | Server-side templating |
| Vanilla JavaScript | Kanban drag-and-drop, AI feature calls, wizard step logic |
| CSS (custom) | Component and layout styles across multiple stylesheets |

### Database
| Technology | Role |
|---|---|
| SQLite | Development default |
| PostgreSQL | Production (via psycopg2-binary) |

### DevOps / Tooling
| Technology | Role |
|---|---|
| python-dotenv | Environment variable loading |
| Mailtrap | Recommended dev SMTP sandbox |

---

## 📁 Project Structure

```
Quorum-main/
│
├── run.py                        # App entry point — creates and runs the Flask app
├── requirements.txt              # All Python dependencies
├── .env.example                  # Template for all required environment variables
├── .gitignore                    # Standard Python/Flask ignores
│
├── seed_commands.py              # Flask CLI seed commands + startup auto-seeding logic
│
├── seed_data/
│   ├── skills_taxonomy.json      # Full skills taxonomy loaded on startup
│   └── seed_projects.json        # Sample civic projects for demo environment
│
└── app/
    ├── __init__.py               # App factory: blueprints, extensions, scheduler, context processors
    ├── config.py                 # DevelopmentConfig / TestingConfig / ProductionConfig
    ├── extensions.py             # Flask extension instances (db, login_manager, mail, etc.)
    ├── bootstrap.py              # Startup bootstrap: create DB, create admin, seed data
    ├── utils.py                  # Shared utilities: utcnow, strip_html, slugify, sanitize_rich_html
    │
    ├── models/
    │   ├── __init__.py           # Centralised model re-exports
    │   ├── user.py               # User, Notification, AICivicPulseCache
    │   ├── project.py            # Project, ProjectRole, RoleApplication
    │   ├── task.py               # Task
    │   ├── milestone.py          # ProjectMilestone
    │   ├── outcome.py            # ProjectOutcome, PeerRating
    │   ├── organization.py       # OrganizationAccount, CivicChallenge
    │   ├── challenge_submission.py # ChallengeSubmission
    │   ├── feed.py               # FeedPost
    │   ├── skill.py              # Skill, UserSkill (association table)
    │   ├── template.py           # ActionTemplate
    │   ├── blog.py               # BlogPost (with categories, tags, SEO fields)
    │   └── analytics.py          # AIUsageLog, RazorpayPayment
    │
    ├── forms/
    │   ├── auth_forms.py         # SignupForm, LoginForm, ForgotPasswordForm, ResetPasswordForm
    │   ├── project_forms.py      # WizardStep1Form – WizardStep6Form
    │   ├── challenge_forms.py    # ChallengeSubmitForm
    │   ├── outcome_forms.py      # ProjectOutcomeForm
    │   ├── profile_forms.py      # EditProfileForm
    │   ├── feed_forms.py         # FeedPostForm
    │   └── task_forms.py         # TaskForm
    │
    ├── routes/
    │   ├── __init__.py           # Shared helpers: admin_required, create_notification, validate_ajax_csrf
    │   ├── main.py               # Landing page, blog frontend, about, contact, verify email
    │   ├── auth.py               # Signup, login, logout, email verification, password reset
    │   ├── onboarding.py         # Post-signup onboarding flow (enforced before any other route)
    │   ├── dashboard.py          # User dashboard, notifications
    │   ├── projects_create.py    # 6-step project creation wizard + AI endpoints
    │   ├── projects_public.py    # Public project board, project detail, apply for role, peer ratings
    │   ├── projects_manage.py    # Creator-only: manage project, team, applicants
    │   ├── tasks.py              # Task CRUD, status transitions, board view
    │   ├── feed.py               # Project activity feed (posts, file uploads)
    │   ├── outcomes.py           # Project outcome submission and AI draft generation
    │   ├── discover.py           # Discover/explore projects with filters
    │   ├── challenges.py         # Civic challenge board, detail, submit, manage submissions
    │   ├── org.py                # Organisation dashboard, challenge posting, support offers
    │   ├── templates_bp.py       # Action templates library
    │   ├── profile.py            # Public and edit profile views
    │   ├── settings.py           # Account settings, notification prefs, billing/subscriptions
    │   └── admin.py              # Full admin panel: analytics, blog CMS, users, orgs, projects, outcomes
    │
    ├── services/
    │   ├── ai_service.py         # AIService class — all Gemini 2.5 Flash integrations
    │   ├── email_service.py      # Transactional email functions (verification, digest, alerts)
    │   ├── file_handler.py       # S3 upload/download/delete + local filesystem fallback
    │   ├── geo_matcher.py        # Haversine distance, proximity filtering, nearby projects
    │   ├── mvt_notifier.py       # MVT threshold check + status transition + notification dispatch
    │   ├── reputation_engine.py  # Time-decayed weighted reputation score computation
    │   ├── skill_matcher.py      # Contributor matching scored by skills + reputation + location
    │   ├── scoping_validator.py  # Rule-based over/under-scope signal detection
    │   ├── template_generator.py # Convert completed projects into reusable ActionTemplates
    │   ├── weekly_digest.py      # Weekly digest email logic for all active projects
    │   └── razorpay_service.py   # Razorpay order creation, payment verification, webhook handling
    │
    ├── static/
    │   ├── css/
    │   │   ├── main.css           # Global styles and layout
    │   │   ├── components.css     # Reusable UI components
    │   │   ├── tasks.css          # Kanban board styles
    │   │   ├── wizard.css         # Project creation wizard styles
    │   │   ├── admin_analytics.css # Admin analytics dashboard styles
    │   │   └── admin_blog.css     # Admin blog editor styles
    │   ├── js/
    │   │   ├── main.js            # Global JS (flash dismiss, general UI)
    │   │   ├── wizard.js          # Multi-step wizard navigation
    │   │   ├── ai_features.js     # AI endpoint calls (enhance, suggest roles, civic pulse)
    │   │   ├── task_board.js      # Kanban drag-and-drop board logic
    │   │   ├── role_builder.js    # Dynamic role creation UI in wizard step 4
    │   │   ├── geo_filter.js      # Geographic filter UI
    │   │   ├── admin_analytics.js # Admin analytics charts and date range controls
    │   │   └── admin_blog.js      # Blog editor with rich text, tag management, image upload
    │   └── img/
    │       ├── logo.svg
    │       ├── community.svg
    │       ├── education.svg
    │       └── environment.svg
    │
    └── templates/
        ├── base.html              # Public-facing base layout
        ├── app_base.html          # Authenticated app base layout (with nav, notification bell)
        ├── admin/                 # Admin panel templates
        ├── auth/                  # Login, signup, forgot/reset password, verify pending
        ├── challenges/            # Challenge board, detail, submission, my submissions
        ├── components/            # Reusable partials (project card, challenge card, pagination, etc.)
        ├── dashboard/             # User dashboard and notifications
        ├── discover/              # Project discovery with filters
        ├── errors/                # 403, 404, 500 error pages
        ├── feed/                  # Project activity feed
        ├── main/                  # Landing page, blog, about, how it works, pricing, legal
        ├── manage/                # Creator project management (dashboard, team)
        ├── onboarding/            # Onboarding flow
        ├── org/                   # Organisation views
        ├── outcomes/              # Outcome submission form
        ├── profile/               # Public and edit profile
        ├── projects/              # Project detail, public board, apply, peer ratings
        ├── settings/              # Account, billing, notifications, organization settings
        ├── tasks/                 # Kanban board
        ├── templates_lib/         # Action templates index and detail
        └── wizard/                # 6-step project creation wizard (steps 1–6 + progress + preview)
```

---

## 🚀 Getting Started

### Prerequisites

Make sure you have the following installed before you begin:

- **Python 3.10+** — [python.org/downloads](https://www.python.org/downloads/)
- **pip** — comes with Python
- **Git** — [git-scm.com](https://git-scm.com/)
- **PostgreSQL** *(production only)* — [postgresql.org/download](https://www.postgresql.org/download/)

For development, Quorum defaults to SQLite — no database server needed.

---

### Installation

**1. Clone the repository**

```bash
git clone https://github.com/shahram8708/quorum.git
cd quorum
```

**2. Create and activate a virtual environment**

```bash
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

**3. Install dependencies**

```bash
pip install -r requirements.txt
```

**4. Copy the environment file and fill in your values**

```bash
cp .env.example .env
```

Edit `.env` with your actual credentials (see [Environment Variables](#environment-variables) below).

**5. Run the app — database and admin user are created automatically**

```bash
python run.py
```

On first startup, Quorum will:
- Create all database tables (`AUTO_CREATE_DB=True`)
- Create an admin user from your `ADMIN_EMAIL` / `ADMIN_PASSWORD` env vars (`AUTO_CREATE_ADMIN_ON_STARTUP=True`)
- Seed the skills taxonomy and sample projects (`AUTO_SEED_DATA_ON_STARTUP=True`)

Open your browser at `http://localhost:5000` and you're in.

---

### Environment Variables

Copy `.env.example` to `.env` and configure the following:

| Variable | Description | Example |
|---|---|---|
| `FLASK_ENV` | Selects config class (`development`, `production`, `testing`) | `development` |
| `FLASK_DEBUG` | Enables Flask debug mode | `1` |
| `SECRET_KEY` | Cryptographic key for sessions and token signing — must be 32+ chars | `a-very-long-random-secret-key` |
| `DEV_DATABASE_URL` | SQLite or Postgres URI for development | `sqlite:///quorum_dev.db` |
| `DATABASE_URL` | PostgreSQL URI for production | `postgresql://user:pass@localhost/quorum_prod` |
| `MAIL_SERVER` | SMTP server hostname | `smtp.mailtrap.io` |
| `MAIL_PORT` | SMTP port | `587` |
| `MAIL_USE_TLS` | Whether to use TLS | `True` |
| `MAIL_USERNAME` | SMTP username | `your_mailtrap_username` |
| `MAIL_PASSWORD` | SMTP password | `your_mailtrap_password` |
| `MAIL_DEFAULT_SENDER` | From address for all outbound email | `noreply@quorum.org` |
| `AWS_ACCESS_KEY_ID` | AWS access key for S3 file storage | `AKIAIOSFODNN7EXAMPLE` |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key | `wJalrXUtnFEMI/...` |
| `AWS_S3_BUCKET` | S3 bucket name for uploaded files | `quorum-feed-files-dev` |
| `AWS_S3_REGION` | AWS region for S3 | `ap-south-1` |
| `USE_S3` | `True` to use S3; `False` uses local filesystem | `False` |
| `LOCAL_STORAGE_PATH` | Local directory for file uploads when S3 is disabled | `local_storage` |
| `GOOGLE_API_KEY` | Google AI Studio API key for Gemini 2.5 Flash | `AIzaSy...` |
| `RAZORPAY_KEY_ID` | Razorpay public key | `rzp_test_xxxxxxxx` |
| `RAZORPAY_KEY_SECRET` | Razorpay secret key | `your_razorpay_secret` |
| `RAZORPAY_WEBHOOK_SECRET` | Webhook signature verification secret | `your_webhook_secret` |
| `RAZORPAY_CREATOR_PRO_AMOUNT` | Creator Pro plan amount in paise (1 INR = 100 paise) | `74900` |
| `RAZORPAY_ORG_STARTER_AMOUNT` | Org Starter plan amount in paise | `499900` |
| `RAZORPAY_ORG_TEAM_AMOUNT` | Org Team plan amount in paise | `1499900` |
| `BASE_URL` | Full public URL of the app (used in email links) | `http://localhost:5000` |
| `FREE_TIER_MAX_ACTIVE_PROJECTS` | Max concurrent active projects for free users | `2` |
| `FREE_TIER_MAX_TEAM_SIZE` | Max team size for free-tier projects | `8` |
| `FREE_TIER_MAX_TIMELINE_DAYS` | Max project duration (days) for free tier | `60` |
| `DIGEST_EMAIL_DAY` | Day of week for weekly digest (0=Mon, 6=Sun) | `1` |
| `MAX_FILE_SIZE_MB` | Maximum file upload size in MB | `10` |
| `AUTO_CREATE_DB` | Auto-create DB tables on startup | `True` |
| `AUTO_CREATE_ADMIN_ON_STARTUP` | Auto-create admin user on startup | `True` |
| `AUTO_SEED_DATA_ON_STARTUP` | Auto-seed skills and projects on startup | `True` |
| `ADMIN_EMAIL` | Email address for the auto-created admin account | `admin@quorum.local` |
| `ADMIN_PASSWORD` | Password for the auto-created admin account | `Admin@12345678` |
| `ADMIN_USERNAME` | Username for the auto-created admin account | `quorum_admin` |
| `ADMIN_FIRST_NAME` | Admin user first name | `Quorum` |
| `ADMIN_LAST_NAME` | Admin user last name | `Admin` |
| `GOOGLE_MAPS_API_KEY` | *(Optional)* Google Maps key for location features | `AIzaSy...` |
| `SENTRY_DSN` | *(Optional)* Sentry DSN for error monitoring | `https://...@sentry.io/...` |

> **Development tip:** For email, sign up for a free [Mailtrap](https://mailtrap.io) account and paste the SMTP credentials into `.env`. You'll see all sent emails in the Mailtrap inbox without any real messages going out.

> **AI tip:** Get a free Google AI Studio API key at [aistudio.google.com](https://aistudio.google.com). Without it, all AI features return graceful fallback responses — the rest of the platform still works.

---

### Running the Project

**Development mode**

```bash
python run.py
```

The app starts on `http://localhost:5000` with `debug=True` and auto-reloader disabled (to prevent APScheduler from double-starting).

**Using Gunicorn (production-style)**

```bash
gunicorn -w 4 -b 0.0.0.0:8000 "run:app"
```

**Flask CLI seed commands** (run these manually if `AUTO_SEED_DATA_ON_STARTUP=False`)

```bash
# Seed skills taxonomy from seed_data/skills_taxonomy.json
flask seed-skills

# Seed sample projects from seed_data/seed_projects.json
flask seed-projects
```

**Setting `FLASK_ENV` for production**

```bash
export FLASK_ENV=production
export DATABASE_URL=postgresql://quorum_user:password@localhost/quorum_prod
gunicorn -w 4 -b 0.0.0.0:8000 "run:app"
```

---

## 💡 Usage

### First-time setup flow

1. Navigate to `http://localhost:5000` — the landing page explains the platform.
2. Click **Sign Up** and create an account. An email verification link is sent.
3. After verification, complete the **onboarding** flow: set your city, country, availability hours, domain interests, and skills. This is enforced — every route redirects to onboarding until it's complete.
4. You're now on your **dashboard** which shows your civic pulse, created projects, joined projects, and open challenges.

### Creating a project

Use the 6-step wizard at `/projects/new`:

- **Step 1:** Project title and problem statement
- **Step 2:** Project type, domain, and success definition (the AI scope validator runs here)
- **Step 3:** Geographic scope, city/country, timeline, and budget
- **Step 4:** Define team roles with skill tags and hours-per-week (AI role suggester available)
- **Step 5:** Milestones
- **Step 6:** Resources needed + publish

The wizard auto-saves a draft to the database at each step. Navigating away and returning picks up where you left off.

### Using the AI features

From the wizard or project detail page, the AI buttons call these endpoints:

```
POST /projects/new/ai/enhance-description       → Enhance the project description text
POST /projects/new/ai/validate-scope            → Validate success definition scope  
POST /projects/new/ai/suggest-roles             → Suggest team roles for the project
GET  /dashboard/civic-pulse                     → Fetch personalised civic pulse digest
POST /my-projects/<id>/outcome/ai-draft         → Draft an outcome report from project data
```

Each call is logged in `ai_usage_log` with timestamp, feature name, response time, and estimated token count.

### Managing a project

After publishing, the creator accesses `/my-projects/<id>/manage` to:
- Review role applications and accept/decline them
- View the task board at `/my-projects/<id>/tasks`
- Post updates to the project feed
- Submit an outcome report when the project completes

Once the team hits the `min_viable_team_size` threshold, the project automatically moves to `launch_ready` status and all relevant parties are notified.

### Admin access

Log in with the `ADMIN_EMAIL` / `ADMIN_PASSWORD` credentials set in your `.env`. The admin panel lives at `/admin` and covers:

- Platform analytics (user growth, project stats, AI usage, revenue) with 7d / 30d / 90d / 12m / all-time ranges
- Blog CMS with rich text editor, category/tag management, featured flags, and SEO fields
- User management (disable, verify, grant admin)
- Organisation verification
- Flagged project review
- Outcome approval queue

---

## 🗺 Route Documentation

Quorum uses Flask blueprints. Here is a summary of every URL namespace and its purpose:

| Blueprint | Prefix | Description |
|---|---|---|
| `main` | `/` | Landing page, blog frontend, about, how it works, pricing, contact, terms, privacy, email verification |
| `auth` | `/` | `/signup`, `/login`, `/logout`, `/forgot-password`, `/reset/<token>`, `/verify/<token>` |
| `onboarding` | `/onboarding` | Onboarding form — enforced for all new users before any other route |
| `dashboard` | `/dashboard` | User dashboard, notifications list, civic pulse endpoint |
| `projects_public` | `/projects` | Public project board, project detail, apply for role, peer rating submission, ratings overview |
| `create` | `/projects/new` | 6-step wizard steps 1–6, preview, publish, AI feature endpoints |
| `manage` | `/my-projects` | Creator dashboard, team management, applicant review |
| `tasks` | `/my-projects/<id>/tasks` | Task board view, task CRUD, drag-and-drop status updates |
| `feed` | `/my-projects/<id>/feed` | Activity feed: post creation, file upload |
| `outcomes` | `/my-projects/<id>/outcome` | Outcome form submission, AI draft generation, peer rating |
| `discover` | `/discover` | Explore projects with domain, scope, and status filters; AI-powered recommendations |
| `challenges` | `/challenges` | Challenge board, challenge detail, submission flow, my submissions |
| `org` | `/org` | Organisation dashboard, post challenge, challenge detail management, support offers |
| `templates` | `/templates` | Action templates library index and detail |
| `profile` | `/profile` | Edit own profile, view public profile |
| `settings` | `/settings` | Account settings, notification preferences, billing/subscription, organisation setup |
| `admin` | `/admin` | Full admin panel (analytics, blog, users, orgs, challenges, projects, outcomes, email logs) |

---

## ⚙️ Configuration

All configuration lives in `app/config.py`. Three classes cover the three environments:

| Class | `FLASK_ENV` value | Database | S3 | Notes |
|---|---|---|---|---|
| `DevelopmentConfig` | `development` | SQLite (default) or `DEV_DATABASE_URL` | Off by default | `DEBUG=True`, no secure cookies |
| `TestingConfig` | `testing` | In-memory SQLite | Off | CSRF disabled, bootstrap disabled |
| `ProductionConfig` | `production` | `DATABASE_URL` (Postgres) | On by default | `DEBUG=False`, secure cookies enforced |

**Session security settings** (all environments):
- `SESSION_COOKIE_HTTPONLY = True`
- `SESSION_COOKIE_SAMESITE = "Lax"`
- `REMEMBER_COOKIE_DURATION = 14 days`
- `PERMANENT_SESSION_LIFETIME = 4 hours`

**Free-tier limits** (adjustable via env vars):
- Max 2 active projects per user
- Max 8 team members per project
- Max 60-day project timeline

**Subscription tiers** (amounts in paise, 100 paise = 1 INR):
- `free` — default, no cost
- `creator_pro` — ₹749/month (74,900 paise)
- `org_starter` — ₹4,999/month (499,900 paise)
- `org_team` — ₹14,999/month (1,499,900 paise)
- `enterprise` — custom pricing, contact sales

---

## 🧪 Testing

The codebase includes a `TestingConfig` in `app/config.py` that uses an in-memory SQLite database, disables CSRF, and skips the startup bootstrap:

```python
class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    AUTO_CREATE_ADMIN_ON_STARTUP = False
    AUTO_SEED_DATA_ON_STARTUP = False
```

To run tests with this config:

```bash
export FLASK_ENV=testing
pytest
```

**Honest status:** There are no test files in the current repository. The `TestingConfig` is ready and waiting, but the test suite hasn't been written yet. If you want to contribute, this is a great place to start — see [Contributing](#-contributing).

---

## 🚢 Deployment

### Deploying with Gunicorn (any Linux server)

**1. Set production environment variables**

```bash
export FLASK_ENV=production
export SECRET_KEY=your-long-random-secret
export DATABASE_URL=postgresql://quorum_user:password@localhost/quorum_prod
export GOOGLE_API_KEY=your_key
export RAZORPAY_KEY_ID=rzp_live_xxxxx
export RAZORPAY_KEY_SECRET=your_secret
export USE_S3=True
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret
export AWS_S3_BUCKET=quorum-prod
export BASE_URL=https://yourdomain.com
```

**2. Install dependencies and run**

```bash
pip install -r requirements.txt
gunicorn -w 4 -b 0.0.0.0:8000 "run:app"
```

The `AUTO_CREATE_DB=True` default means tables are created on first startup — no need to run `flask db upgrade` manually unless you are running migrations for schema changes.

### Deploying to Render / Railway / Fly.io

These platforms read environment variables from their dashboard. Set all variables from your `.env.example`, then use the following start command:

```
gunicorn -w 4 -b 0.0.0.0:$PORT "run:app"
```

Set `FLASK_ENV=production` and `DATABASE_URL` to the Postgres connection string your platform provides.

### Deploying to Heroku

```bash
heroku create your-app-name
heroku addons:create heroku-postgresql:mini
heroku config:set FLASK_ENV=production SECRET_KEY=... GOOGLE_API_KEY=... # etc.
git push heroku main
```

Heroku automatically sets `DATABASE_URL` as `postgres://...` — the `_normalize_database_uri()` function in `config.py` automatically rewrites this to `postgresql://` to satisfy SQLAlchemy.

### Background Jobs

APScheduler runs two background jobs in-process:

| Job | Schedule | Function |
|---|---|---|
| `weekly_digest` | Every Monday at 08:00 | Sends weekly task/milestone summary emails to all active project teams |
| `daily_civic_pulse` | Every day at 06:30 | Refreshes the AI civic pulse cache for all users |

These run in-process alongside the web server. For high-traffic deployments, consider extracting them to a dedicated Celery worker or a separate `python` process.

### Nginx reverse proxy (recommended for production)

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 🤝 Contributing

Contributions are welcome. Here's how to get involved:

**1. Fork the repository and clone your fork**

```bash
git clone https://github.com/your-username/quorum.git
cd quorum
```

**2. Create a feature branch**

```bash
git checkout -b feature/your-feature-name
```

**3. Make your changes**

Follow these conventions:
- Keep route logic in `routes/`, business logic in `services/`, and data access in `models/`.
- Use `strip_html()` from `app/utils.py` to sanitise any user-supplied text before storing.
- Use `sanitize_rich_html()` for rich text editor content.
- All new database models should import `utcnow` from `app/utils.py` for timezone-aware timestamps.
- If adding a new AI feature, add it to `AIService` in `ai_service.py` and register it in `AI_FEATURE_NAME_MAP`.

**4. Commit with a clear message**

```bash
git commit -m "feat: add geographic filter to challenge board"
```

**5. Push and open a pull request**

```bash
git push origin feature/your-feature-name
```

Open a PR against the `main` branch. Describe what your change does and why.

**Reporting bugs**

Open a GitHub Issue with:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Your Python version and OS
- Any relevant error output

**Requesting features**

Open a GitHub Issue labelled `enhancement` describing the use case and the proposed behaviour.

---

## 🗺 Roadmap

Based on the current codebase, here's what's done and what could come next:

**Done ✅**
- Full project creation wizard with AI assistance
- Contributor skill matching with geo-proximity scoring
- MVT detection and launch-ready transitions
- Kanban task board with drag-and-drop
- Civic challenges marketplace with grant support
- Reputation engine with time-decayed peer ratings
- Action templates auto-generated from completed projects
- Weekly digest emails via APScheduler
- Daily civic pulse via Gemini with user-level caching
- Razorpay subscription billing
- Admin panel with analytics, blog CMS, and moderation tools
- S3 file storage with local fallback

**Planned / Possible next steps 🔭**
- Write a test suite — the `TestingConfig` is ready, the tests are not
- Add Flask-Migrate migration files to the repo so schema changes can be versioned (the `.gitignore` currently excludes the `migrations/` folder)
- Real-time notifications via WebSockets or Server-Sent Events instead of page-refresh polling
- Team messaging / threaded discussion within projects
- Mobile-responsive design improvements and a PWA manifest
- OAuth login (Google, GitHub) as an alternative to email/password
- Public API with token-based authentication for third-party integrations
- Celery + Redis for extracting background jobs out of the web process
- Full-text search across projects and challenges (currently basic SQL `LIKE`)
- Docker and `docker-compose.yml` for one-command local setup

---

## 📄 License

No `LICENSE` file was found in the repository at the time of this README being generated. All rights are implicitly reserved by the author. If you intend to use, fork, or redistribute this code, contact the project owner to clarify licensing terms before doing so.

---

## 🙏 Acknowledgements

This project is built on the shoulders of some excellent open-source work:

- [Flask](https://flask.palletsprojects.com/) and the entire Pallets ecosystem — the backbone of the whole application
- [Flask-SQLAlchemy](https://flask-sqlalchemy.palletsprojects.com/) and [SQLAlchemy](https://www.sqlalchemy.org/) — making relational data pleasant to work with in Python
- [Google Gemini API](https://ai.google.dev/) (`google-genai`) — the AI layer powering description enhancement, scope validation, role suggestion, civic pulse, and more
- [Razorpay](https://razorpay.com/) — the payment gateway built for the Indian market
- [APScheduler](https://apscheduler.readthedocs.io/) — reliable in-process job scheduling without the Celery overhead
- [bcrypt](https://pypi.org/project/bcrypt/) — proper password hashing, the way it should be done
- [boto3](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html) — AWS S3 integration for scalable file storage
- [itsdangerous](https://itsdangerous.palletsprojects.com/) — token signing for email verification and password reset flows
- [bleach](https://bleach.readthedocs.io/) — HTML sanitisation so user content stays safe

---

## 👋 Contact / Author

Author information was not found in `package.json` or project config files (this is a Python project). If you're the person who built this — add your name here. You made something genuinely useful.

If you're using Quorum and have questions, ideas, or want to collaborate:

- Open a [GitHub Issue](https://github.com/shahram8708/quorum/issues) — it's the fastest way to get a response
- For enterprise or partnership inquiries, the pricing page references a sales contact