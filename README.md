<div align="center">
  <h1>Lirana AI Bot 🤖💄</h1>

  <p><b>Intelligent Skincare Consultation & E-Commerce Bot on Bale Messenger</b></p>

  <p>
    An enterprise-grade AI chatbot providing personalized skincare routines, direct product purchases,<br />
    subscription management (VIP), and advanced admin broadcast capabilities.
  </p>

  <p>
    <img src="https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white" alt="Python" />
    <img src="https://img.shields.io/badge/OpenAI-412991?style=flat&logo=openai&logoColor=white" alt="OpenAI GPT-4" />
    <img src="https://img.shields.io/badge/PostgreSQL-316192?style=flat&logo=postgresql&logoColor=white" alt="PostgreSQL" />
    <img src="https://img.shields.io/badge/Redis-DC382D?style=flat&logo=redis&logoColor=white" alt="Redis" />
    <img src="https://img.shields.io/badge/Pydantic-E92063?style=flat&logo=pydantic&logoColor=white" alt="Pydantic" />
    <img src="https://img.shields.io/badge/Asyncio-FFD43B?style=flat&logo=python&logoColor=black" alt="Asyncio" />
  </p>
</div>

---

## 🧭 Overview

**Lirana AI** is a state-of-the-art conversational agent built for the Bale Messenger platform. Designed for a specialized skincare and cosmetics store, the bot leverages **OpenAI's GPT-4o-mini** to act as a virtual dermatologist, diagnosing user needs through interactive Q&A and recommending specific products from the store's inventory.

The platform includes seamless e-commerce synchronization, VIP subscription tiers, and a powerful admin panel for targeted marketing broadcasts.

|                          |                                                                               |
| ------------------------ | ----------------------------------------------------------------------------- |
| 🧠 **AI Consultant**     | Context-aware skincare diagnostics using OpenAI tailored prompts.             |
| 🛍️ **Store Sync**        | Real-time product fetching and purchasing via Bahoosh API integration.        |
| 👑 **VIP Subscriptions** | Monetized premium access to advanced AI consultations and exclusive features. |
| 📢 **Smart Broadcasts**  | Admin tools for mass messaging and user membership verification (via CSV).    |
| ⚡ **High Performance**  | Fully asynchronous architecture (AsyncPG + Redis) for rapid response times.   |

---

## 🧱 Tech Stack & Architecture

| Layer                     | Technologies Used                                       |
| ------------------------- | ------------------------------------------------------- |
| **Core AI Logic**         | `openai` Python SDK, Custom Prompt Engineering          |
| **Database (Relational)** | PostgreSQL with `asyncpg` and SQLAlchemy models         |
| **Caching & State**       | Redis (Session management, rate limiting, and cache)    |
| **Config Management**     | Pydantic v2 (`SettingsConfigDict`, Environment parsing) |
| **Bot API**               | Bale Bot API with async handlers and custom keyboards   |

---

## ✨ Key Modules

### 1. AI Diagnostic Engine (`services/ai_handler.py`)

Analyzes user inputs, skin types, and specific concerns. It maps the diagnosed needs directly to the `products.json` inventory to suggest the most relevant skincare routines.

### 2. Bahoosh E-Commerce Sync (`services/bahoosh_sync.py`)

Phase 2 integration module that syncs local bot inventory with the main website. It handles dynamic price updates, stock availability, and direct cart additions.

### 3. Admin & Broadcast Engine (`bot/handlers/onboarding.py`)

Empowers administrators to:

- Upload lists of phone numbers to cross-reference registered users.
- Send targeted promotional broadcasts and banners.
- Monitor active VIP subscriptions.

---

## 📁 Repository Structure

```text
Lirana_Bot/
├── app/
│   ├── api/                  # REST endpoints for webhook/external triggers
│   ├── assets/               # Banners, product images, and UI assets
│   ├── bot/                  # Bale Messenger handlers
│   │   ├── handlers/         # AI Chat, Shop, VIP, and Onboarding logic
│   │   └── keyboards/        # Inline and Reply markup menus
│   ├── core/                 # Security and Pydantic configuration (config.py)
│   ├── data/                 # Static inventory (products.json)
│   ├── db/                   # PostgreSQL models and CRUD operations
│   ├── services/             # External APIs (OpenAI, Bahoosh) & Redis Cache
│   └── utils/                # Helper functions and formatters
│
├── scripts/                  # Automated backup scripts (Encrypted ZIPs)
├── main.py                   # Application entry point
├── requirements.txt          # Python dependencies
└── .env.example              # Environment variables template
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL Server
- Redis Server
- Bale Bot Token & OpenAI API Key

### 1 — Clone the Repository

```bash
git clone https://github.com/arvinameri/lirana-ai-bot.git
cd lirana-ai-bot
```

### 2 — Environment Setup

```bash
cp .env.example .env
# Open .env and fill in your Bale Token, OpenAI Key, and DB credentials
```

### 3 — Install Dependencies

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 4 — Database Initialization

```bash
python init_db.py
```

### 5 — Run the Bot

```bash
python main.py
```

---

## 🛡️ Security & Privacy

- **Secure Configurations:** Leveraging Pydantic `BaseSettings` with strict environment variable parsing.
- **Encrypted Backups:** Daily database backups are zipped and encrypted using custom script modules.
- **Rate Limiting:** Redis-backed throttling to prevent API abuse and control OpenAI token costs.

---

<div align="center">
  <h3>Built by Arvin Ameri</h3>
  <p>📍 Amsterdam, Netherlands &nbsp;|&nbsp; Full-Stack AI Developer</p>
  <p>
    <a href="https://www.linkedin.com/in/arvinameri">
      <img src="https://img.shields.io/badge/LinkedIn-Connect-0A66C2?style=for-the-badge&logo=linkedin&logoColor=white" alt="LinkedIn" />
    </a>
  </p>
</div>
