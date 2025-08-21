Smart Parking Platform (Streamlit + SQLite)

A prototype demo of a smart parking web application built with Streamlit and SQLite. It supports multiple roles (users, owners, and admins), location-aware discovery, reservations, payments, loyalty points, EV charging, and interactive maps for real-time parking management. This is only a demo prototype and not fully production-ready.

- Accounts and Security
  - Roles: User, Owner, Admin
  - Passwords stored as SHA-256 hashes
  - Encrypted secrets via Fernet
  - Session-based state management

- Parking Supply
  - Owners can add/manage spaces with verification workflow
  - Public/private lots with available space tracking
  - EV charging flag and per-hour EV price
  - Revenue share tracking for owners

- Discovery and Maps
  - Auto location detection (IP with fallback; Tuticorin default)
  - Filters: radius, EV, price range, minimum spaces, type
  - Interactive Folium map with color-coded markers
    - Green: >50% spaces free
    - Orange: 20–50% free
    - Red: <20% free
  - Distance badges and popups with lot details

- Reservations and Payments
  - Hourly pricing with EV charging cost when selected
  - Payment methods: Wallet, FASTag, NFC, Credit/Debit (simulated)
  - Reward points credited for successful payments
  - Payment records with transaction IDs and status
  - Reservations update availability and revenue share

- Vehicles and Methods
  - Multiple vehicles per account
  - Mark EV and set default
  - Link FASTag/NFC identifiers

- Data Model (SQLite)
  - users: accounts, wallet, reward points, identifiers
  - parking_spaces: owner, location, availability, EV flag, verification
  - reservations: booking details, costs, earnings split
  - payments: transaction records
  - user_vehicles: per-user linked vehicles
  - sensors: reserved for future IoT expansion

- Project Structure
  - v16.py — main Streamlit app
  - smart_parking.db — SQLite database
  - secret.key — Fernet key (auto-generated)
  - requirements.txt — dependencies
  - assets/ — optional icons/images

- Quick Start
  - Create venv and activate
  - pip install -r requirements.txt
  - streamlit run v16.py
  - On first run: secret.key and DB created, sample locations seeded, default admin added (email: aakashbala06@gmail.com, password: admin123)

- Usage Guide
  - Register as User/Owner or login as Admin
  - Auto location detection, filters, and map search
  - Book by selecting time, vehicle, space, EV option
  - Pay using chosen method; wallet/FASTag/NFC need setup
  - Successful payment updates reservation, rewards, and owner revenue

- Configuration
  - STREAMLIT_SERVER_PORT (default 8501)
  - MAP_ZOOM_START (default 14)
  - DEFAULT_LOCATION (fallback coordinates)

- Development Notes
  - Location via IP → Nominatim → fallback
  - Distance with geopy.geodesic
  - Maps with Folium + streamlit-folium
  - Security: SHA-256 + Fernet
  - Errors handled with try/except and DB transactions

- Testing
  - Run in wide mode for debugging
  - Inspect DB with sqlite3 smart_parking.db
