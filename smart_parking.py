import streamlit as st
import sqlite3
import datetime
import random
import pandas as pd
import numpy as np
from PIL import Image, ImageDraw
import time
import hashlib
import folium
from streamlit_folium import st_folium
from geopy.distance import geodesic
import geocoder
from geopy.geocoders import Nominatim
import os
import json
from cryptography.fernet import Fernet
import humanize

# ======================
# SECURITY CONFIGURATION
# ======================
def generate_encryption_key():
    if not os.path.exists('secret.key'):
        key = Fernet.generate_key()
        with open('secret.key', 'wb') as key_file:
            key_file.write(key)
    else:
        with open('secret.key', 'rb') as key_file:
            key = key_file.read()
    return key

SECRET_KEY = generate_encryption_key()
cipher_suite = Fernet(SECRET_KEY)

def encrypt_data(data):
    return cipher_suite.encrypt(data.encode()).decode()

def decrypt_data(encrypted_data):
    return cipher_suite.decrypt(encrypted_data.encode()).decode()

# ======================
# DATABASE INITIALIZATION
# ======================
def init_db():
    conn = sqlite3.connect('smart_parking.db')
    c = conn.cursor()
    
    # Create Users Table with enhanced fields
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                user_type TEXT CHECK(user_type IN ('user', 'owner', 'admin')) NOT NULL,
                wallet_balance REAL DEFAULT 0.0,
                reward_points INTEGER DEFAULT 0,
                nfc_card_id TEXT UNIQUE,
                fastag_id TEXT UNIQUE,
                phone TEXT,
                vehicle_details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,
                is_active BOOLEAN DEFAULT 1)''')
    
    # Create Parking Spaces Table with revenue tracking
    c.execute('''CREATE TABLE IF NOT EXISTS parking_spaces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                address TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                total_spaces INTEGER NOT NULL,
                available_spaces INTEGER NOT NULL,
                price_per_hour REAL NOT NULL,
                is_public BOOLEAN NOT NULL,
                has_ev_charging BOOLEAN NOT NULL,
                ev_charging_price REAL DEFAULT 0.0,  
                is_verified BOOLEAN DEFAULT FALSE,
                verification_admin_id INTEGER,
                verification_date TEXT,
                verification_notes TEXT,
                features TEXT,
                revenue_share REAL DEFAULT 0.15,
                total_earnings REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(owner_id) REFERENCES users(id))''')
    
    # Reservations Table with enhanced fields
    c.execute('''CREATE TABLE IF NOT EXISTS reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                parking_id INTEGER NOT NULL,
                space_number INTEGER NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                actual_end_time TEXT,
                total_cost REAL,
                ev_charging_cost REAL DEFAULT 0.0,
                payment_method TEXT CHECK(payment_method IN ('wallet', 'fastag', 'nfc', 'credit_card', 'debit_card')),
                payment_status TEXT CHECK(payment_status IN ('pending', 'completed', 'failed', 'refunded', 'cancelled')) DEFAULT 'pending',
                vehicle_type TEXT,
                license_plate TEXT,
                owner_earnings REAL DEFAULT 0.0,
                platform_earnings REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(parking_id) REFERENCES parking_spaces(id))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                is_read BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id))''')
    
    # Sensors Table for IoT integration
    c.execute('''CREATE TABLE IF NOT EXISTS sensors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parking_id INTEGER NOT NULL,
                space_number INTEGER NOT NULL,
                is_occupied BOOLEAN NOT NULL,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                battery_level INTEGER,
                FOREIGN KEY(parking_id) REFERENCES parking_spaces(id))''')
    
    # Payments Table with transaction details
    c.execute('''CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                reservation_id INTEGER,
                amount REAL NOT NULL,
                payment_method TEXT NOT NULL,
                transaction_id TEXT UNIQUE,
                status TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(reservation_id) REFERENCES reservations(id))''')
    
    # Loyalty Programs Table
    c.execute('''CREATE TABLE IF NOT EXISTS loyalty_programs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                points_per_rupee REAL DEFAULT 0.1,
                min_redeem_points INTEGER DEFAULT 100,
                redeem_value REAL DEFAULT 10.0,
                is_active BOOLEAN DEFAULT 1)''')
    
    # User Vehicles Table
    c.execute('''CREATE TABLE IF NOT EXISTS user_vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                vehicle_type TEXT NOT NULL,
                license_plate TEXT NOT NULL,
                is_ev BOOLEAN DEFAULT FALSE,
                fastag_linked BOOLEAN DEFAULT FALSE,
                nfc_linked BOOLEAN DEFAULT FALSE,
                is_default BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id))''')
    
    # Create indexes
    c.execute("CREATE INDEX IF NOT EXISTS idx_parking_location ON parking_spaces(latitude, longitude)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_reservations_user ON reservations(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_reservations_time ON reservations(start_time, end_time)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sensors_parking ON sensors(parking_id, space_number)")
    
    # Create default admin if not exists
    try:
        admin_email = "aakashbala06@gmail.com"
        c.execute("SELECT id FROM users WHERE email=? AND user_type='admin'", (admin_email,))
        if not c.fetchone():
            password = "admin123"
            hashed_password = hashlib.sha256(password.encode()).hexdigest()
            
            c.execute('''INSERT INTO users 
                        (name, email, password, user_type, phone)
                        VALUES (?, ?, ?, ?, ?)''',
                     ("System Admin", admin_email, hashed_password, "admin", "+1234567890"))
    except sqlite3.IntegrityError:
        pass
    
    # Insert sample parking data if empty - Changed to Tuticorin locations
    c.execute("SELECT COUNT(*) FROM parking_spaces")
    if c.fetchone()[0] == 0:
        sample_data = [
            (1, "Tuticorin Port Parking", "Harbor Area, Tuticorin", 8.7679, 78.2218, 200, 85, 40, True, True, 25.0,
             True, 1, datetime.datetime.now().isoformat(), "Verified by admin", 
             json.dumps({"security": True, "roof": True, "disabled_access": True, "cctv": True}), 0.15, 0),
            (1, "Pearl City Mall Parking", "Victoria Extension, Tuticorin", 8.8041, 78.1527, 350, 150, 35, True, False, 0.0,
             True, 1, datetime.datetime.now().isoformat(), "Verified by admin",
             json.dumps({"security": True, "valet": True, "car_wash": True}), 0.15, 0),
            (1, "SPIC Complex Parking", "Industrial Estate, Tuticorin", 8.7943, 78.1342, 120, 45, 50, False, True, 30.0,
             True, 1, datetime.datetime.now().isoformat(), "Verified by admin",
             json.dumps({"security": True, "cctv": True, "guarded": True, "ev_charging": True}), 0.15, 0)
        ]
        c.executemany('''INSERT INTO parking_spaces 
                        (owner_id, name, address, latitude, longitude, 
                         total_spaces, available_spaces, price_per_hour, 
                         is_public, has_ev_charging, ev_charging_price, is_verified,
                         verification_admin_id, verification_date, verification_notes, features, revenue_share, total_earnings)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', sample_data)
        
        # Insert default loyalty program
        c.execute("SELECT COUNT(*) FROM loyalty_programs")
        if c.fetchone()[0] == 0:
            c.execute('''INSERT INTO loyalty_programs 
                        (name, description, points_per_rupee, min_redeem_points, redeem_value)
                        VALUES (?, ?, ?, ?, ?)''',
                     ("Easy Dock Rewards", "Earn points for every rupee spent on parking", 0.1, 100, 10.0))
    
    conn.commit()
    conn.close()

# ======================
# AUTHENTICATION SYSTEM
# ======================
def verify_login(email, password):
    conn = sqlite3.connect('smart_parking.db')
    c = conn.cursor()
    try:
        # Get user's stored password hash
        c.execute("SELECT id, password, user_type FROM users WHERE email=?", (email,))
        user_data = c.fetchone()
        
        if not user_data:
            st.error("Invalid email or password")
            return False
            
        user_id, stored_hash, user_type = user_data
        
        # Hash the provided password
        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        
        # Compare hashes
        if hashed_password == stored_hash:
            # Update last login time
            c.execute("UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?", (user_id,))
            conn.commit()
            
            # Get full user data
            c.execute('''SELECT id, name, email, user_type, wallet_balance, 
                         reward_points, phone, nfc_card_id, fastag_id FROM users WHERE id=?''', (user_id,))
            user = c.fetchone()
            
            # Get user's vehicles
            c.execute("SELECT * FROM user_vehicles WHERE user_id=?", (user_id,))
            vehicles = c.fetchall()
            
            # Store user data in session
            st.session_state.user = {
                'id': user[0],
                'name': user[1],
                'email': user[2],
                'user_type': user[3],
                'wallet_balance': user[4],
                'reward_points': user[5],
                'phone': user[6],
                'nfc_card_id': user[7],
                'fastag_id': user[8],
                'vehicles': vehicles
            }
            return True
        else:
            st.error("Invalid email or password")
            return False
    except Exception as e:
        st.error(f"Login error: {str(e)}")
        return False
    finally:
        conn.close()

def register_user(name, email, password, user_type, phone):
    conn = sqlite3.connect('smart_parking.db')
    c = conn.cursor()
    try:
        # Hash the password
        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        
        c.execute('''INSERT INTO users 
                    (name, email, password, user_type, phone, last_login)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                 (name, email, hashed_password, user_type, phone))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        st.error("Email already registered")
        return False
    except Exception as e:
        st.error(f"Registration failed: {str(e)}")
        return False
    finally:
        conn.close()

# ======================
# LOCATION SERVICES
# ======================
def get_user_location():
    """Get user location with automatic detection and caching"""
    try:
        with st.spinner("Detecting your location..."):
            # Try browser geolocation first
            try:
                g = geocoder.ip('me')
                if g and g.latlng:
                    return g.latlng
            except Exception as e:
                st.warning(f"Browser geolocation failed: {str(e)}")
            
            # Fallback to Nominatim geocoding
            try:
                geolocator = Nominatim(user_agent="smart_parking_app")
                location = geolocator.geocode("")
                if location:
                    return [location.latitude, location.longitude]
            except Exception as e:
                st.warning(f"Geocoding service failed: {str(e)}")
            
            # Final fallback to default location
            return [8.7642, 78.1348]  # Default to Tuticorin coordinates
    except Exception as e:
        st.error(f"Location detection failed: {str(e)}")
        return [8.7642, 78.1348]

# ======================
# PARKING MANAGEMENT
# ======================
def get_all_parking_spaces(filters=None, include_unverified=False):
    """Get parking spaces with optional filters"""
    conn = sqlite3.connect('smart_parking.db')
    c = conn.cursor()
    
    # Base query
    query = '''SELECT * FROM parking_spaces WHERE 1=1'''
    params = []
    
    # Only show verified spaces by default
    if not include_unverified:
        query += " AND is_verified=1"
    
    # Add filters if provided
    if filters:
        if filters.get('verified_only', True) and include_unverified:
            query += " AND is_verified=1"
        if filters.get('ev_charging'):
            query += " AND has_ev_charging=1"
        if filters.get('max_price'):
            query += " AND price_per_hour<=?"
            params.append(filters['max_price'])
        if filters.get('min_spaces'):
            query += " AND available_spaces>=?"
            params.append(filters['min_spaces'])
        if filters.get('public_only'):
            query += " AND is_public=1"
        if filters.get('private_only'):
            query += " AND is_public=0"
    
    c.execute(query, tuple(params))
    all_spaces = c.fetchall()
    conn.close()
    
    # Process spaces
    processed_spaces = []
    for space in all_spaces:
        space_dict = list(space)
        try:
            space_dict[15] = json.loads(space[15]) if space[15] else {}
        except:
            space_dict[15] = {}
        processed_spaces.append(space_dict)
    
    return processed_spaces

def get_nearby_parking(user_location, radius_km=5, filters=None, include_unverified=False):
    """Get parking spaces within specified radius with optional filters"""
    all_spaces = get_all_parking_spaces(filters, include_unverified)
    
    # Filter by distance
    nearby_spaces = []
    for space in all_spaces:
        space_loc = (space[4], space[5])
        distance = geodesic(user_location, space_loc).km
        if distance <= radius_km:
            nearby_spaces.append(space)
    
    return nearby_spaces

def make_reservation(user_id, parking_id, vehicle_info):
    conn = sqlite3.connect('smart_parking.db')
    c = conn.cursor()
    
    try:
        # Validate inputs
        if not user_id or not parking_id or not vehicle_info:
            return {"success": False, "message": "Invalid input parameters"}
        
        # Get parking space info including EV charging price
        c.execute('''SELECT available_spaces, price_per_hour, has_ev_charging, 
                    ev_charging_price, revenue_share FROM parking_spaces WHERE id=?''', 
                 (parking_id,))
        space = c.fetchone()
        
        if not space or len(space) < 5:
            return {"success": False, "message": "Parking space not found or invalid data"}
        
        if space[0] <= 0:  # available_spaces
            return {"success": False, "message": "No available spaces"}
        
        # Validate and calculate costs
        try:
            start_time = datetime.datetime.strptime(vehicle_info['start_time'], "%Y-%m-%d %H:%M")
            end_time = datetime.datetime.strptime(vehicle_info['end_time'], "%Y-%m-%d %H:%M")
            duration = (end_time - start_time).total_seconds() / 3600
            
            if duration <= 0:
                return {"success": False, "message": "Invalid booking duration"}
                
            parking_cost = duration * space[1]
            ev_charging_cost = duration * space[3] if vehicle_info.get('use_ev_charging', False) and space[2] else 0
            total_cost = parking_cost + ev_charging_cost
            
            # Calculate earnings split
            revenue_share = space[4] if len(space) > 4 else 0.15  # Default if not available
            platform_earnings = total_cost * revenue_share
            owner_earnings = total_cost - platform_earnings
            
            # Validate vehicle info
            if not vehicle_info.get('vehicle_type') or not vehicle_info.get('license_plate'):
                return {"success": False, "message": "Vehicle information incomplete"}
            
            # Insert reservation with EV charging cost
            c.execute('''INSERT INTO reservations 
                        (user_id, parking_id, space_number, start_time, end_time,
                         total_cost, ev_charging_cost, payment_method, payment_status,
                         vehicle_type, license_plate, owner_earnings, platform_earnings)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                     (user_id, parking_id, vehicle_info.get('space_number', 1),
                      vehicle_info['start_time'], vehicle_info['end_time'],
                      total_cost, ev_charging_cost, vehicle_info.get('payment_method', 'wallet'),
                      'pending', vehicle_info['vehicle_type'], vehicle_info['license_plate'],
                      owner_earnings, platform_earnings))
            
            # Update available spaces
            c.execute('''UPDATE parking_spaces SET available_spaces = available_spaces - 1 
                         WHERE id=?''', (parking_id,))
            
            conn.commit()
            return {"success": True, "reservation_id": c.lastrowid, "amount": total_cost}
            
        except ValueError as e:
            return {"success": False, "message": f"Invalid date format: {str(e)}"}
        except KeyError as e:
            return {"success": False, "message": f"Missing required field: {str(e)}"}
            
    except sqlite3.Error as e:
        conn.rollback()
        return {"success": False, "message": f"Database error: {str(e)}"}
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": f"Unexpected error: {str(e)}"}
    finally:
        conn.close()

# ======================
# PAYMENT SYSTEM
# ======================
def process_payment(user_id, reservation_id, payment_method, amount):
    conn = sqlite3.connect('smart_parking.db')
    c = conn.cursor()
    
    try:
        # Validate inputs
        if not user_id or not reservation_id or not payment_method or amount <= 0:
            return {"success": False, "message": "Invalid payment parameters"}
        
        # Get reservation details including parking_id and earnings
        c.execute('''SELECT parking_id, owner_earnings, platform_earnings, payment_status
                     FROM reservations 
                     WHERE id=? AND user_id=?''', 
                 (reservation_id, user_id))
        res = c.fetchone()
        
        if not res:
            return {"success": False, "message": "Reservation not found"}
        
        parking_id, owner_earnings, platform_earnings, current_status = res
        
        # Check if already paid
        if current_status == 'completed':
            return {"success": False, "message": "Payment already completed for this reservation"}
        
        # Generate transaction ID
        transaction_id = f"txn_{int(time.time())}_{random.randint(1000, 9999)}"
        
        # Handle different payment methods
        if payment_method == 'wallet':
            # Verify wallet balance
            c.execute("SELECT wallet_balance FROM users WHERE id=?", (user_id,))
            balance = c.fetchone()[0]
            
            if balance < amount:
                return {"success": False, "message": "Insufficient wallet balance"}
            
            # Deduct from wallet
            c.execute('''UPDATE users 
                         SET wallet_balance = wallet_balance - ? 
                         WHERE id=?''', 
                     (amount, user_id))
            
        elif payment_method in ['fastag', 'nfc']:
            # Verify payment method is linked
            if payment_method == 'fastag':
                c.execute("SELECT fastag_id FROM users WHERE id=?", (user_id,))
                if not c.fetchone()[0]:
                    return {"success": False, "message": "No FASTag linked to your account"}
            else:  # nfc
                c.execute("SELECT nfc_card_id FROM users WHERE id=?", (user_id,))
                if not c.fetchone()[0]:
                    return {"success": False, "message": "No NFC card linked to your account"}
            
        elif payment_method in ['credit_card', 'debit_card']:
            # Simulate payment processing (in real app, integrate with payment gateway)
            # Add 10% chance of failure for demo purposes
            if random.random() < 0.1:
                return {"success": False, "message": "Payment gateway declined transaction"}
        else:
            return {"success": False, "message": "Invalid payment method"}
        
        # Get loyalty program details
        c.execute("SELECT points_per_rupee FROM loyalty_programs WHERE is_active=1 LIMIT 1")
        loyalty_program = c.fetchone()
        points_per_rupee = loyalty_program[0] if loyalty_program else 0.1
        
        # Add reward points
        reward_points = int(amount * points_per_rupee)
        c.execute('''UPDATE users 
                     SET reward_points = reward_points + ? 
                     WHERE id=?''', 
                 (reward_points, user_id))
        
        # Record payment
        c.execute('''INSERT INTO payments 
                    (user_id, reservation_id, amount, payment_method, 
                     transaction_id, status, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                 (user_id, reservation_id, amount, payment_method, 
                  transaction_id, 'completed'))
        
        # Update reservation status
        c.execute('''UPDATE reservations 
                     SET payment_status='completed', 
                         payment_method=?,
                         actual_end_time=CURRENT_TIMESTAMP
                     WHERE id=?''', 
                 (payment_method, reservation_id))
        
        # Update owner's earnings
        if owner_earnings and owner_earnings > 0:
            c.execute('''UPDATE parking_spaces 
                         SET total_earnings = total_earnings + ?
                         WHERE id=?''', 
                     (owner_earnings, parking_id))
        
        conn.commit()
        
        return {
            "success": True, 
            "transaction_id": transaction_id, 
            "reward_points": reward_points
        }
    except sqlite3.Error as e:
        conn.rollback()
        return {"success": False, "message": f"Database error: {str(e)}"}
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": f"Unexpected error: {str(e)}"}
    finally:
        conn.close()
        
def check_payment_status(reservation_id):
    conn = sqlite3.connect('smart_parking.db')
    c = conn.cursor()
    
    try:
        c.execute('''SELECT status FROM payments 
                     WHERE reservation_id=? 
                     ORDER BY timestamp DESC LIMIT 1''',
                 (reservation_id,))
        result = c.fetchone()
        
        if result:
            return result[0]  # 'completed', 'failed', etc.
        return None
    except Exception as e:
        st.error(f"Error checking payment status: {str(e)}")
        return None
    finally:
        conn.close()

# ======================
# VEHICLE MANAGEMENT
# ======================
def add_user_vehicle(user_id, vehicle_type, license_plate, is_ev=False, is_default=False):
    conn = sqlite3.connect('smart_parking.db')
    c = conn.cursor()
    
    try:
        # If setting as default, first unset any existing default
        if is_default:
            c.execute('''UPDATE user_vehicles 
                         SET is_default=0 
                         WHERE user_id=?''', (user_id,))
        
        c.execute('''INSERT INTO user_vehicles 
                    (user_id, vehicle_type, license_plate, is_ev, is_default)
                    VALUES (?, ?, ?, ?, ?)''',
                 (user_id, vehicle_type, license_plate, is_ev, is_default))
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        st.error(f"Failed to add vehicle: {str(e)}")
        return False
    finally:
        conn.close()

def link_payment_method(user_id, method_type, identifier):
    conn = sqlite3.connect('smart_parking.db')
    c = conn.cursor()
    
    try:
        if method_type == 'fastag':
            c.execute('''UPDATE users 
                         SET fastag_id=?
                         WHERE id=?''', (identifier, user_id))
        elif method_type == 'nfc':
            c.execute('''UPDATE users 
                         SET nfc_card_id=?
                         WHERE id=?''', (identifier, user_id))
        
        conn.commit()
        
        # Update session
        if 'user' in st.session_state:
            if method_type == 'fastag':
                st.session_state.user['fastag_id'] = identifier
            else:
                st.session_state.user['nfc_card_id'] = identifier
        
        return True
    except Exception as e:
        conn.rollback()
        st.error(f"Failed to link {method_type}: {str(e)}")
        return False
    finally:
        conn.close()

# ======================
# MAP VISUALIZATION
# ======================
def show_parking_map(parking_spaces, user_location=None, zoom_start=14):
    """Create an interactive folium map with enhanced features"""
    # Create map centered on user location or default location
    map_center = user_location if user_location else [8.7642, 78.1348]
    m = folium.Map(
        location=map_center, 
        zoom_start=zoom_start,
        tiles='cartodbpositron',
        control_scale=True
    )
    
    # Add user location marker if available
    if user_location:
        folium.Marker(
            location=user_location,
            popup="Your Location",
            icon=folium.Icon(color="blue", icon="user")
        ).add_to(m)
    
    # Add parking spaces with enhanced markers
    for space in parking_spaces:
        # Calculate distance if user location provided
        distance = ""
        if user_location:
            space_loc = (space[4], space[5])
            dist_km = geodesic(user_location, space_loc).km
            distance = f"{dist_km:.1f} km away"
        
        # Determine marker color based on availability percentage
        avail_pct = (space[7] / space[6]) * 100 if space[6] > 0 else 0
        if avail_pct > 50:
            color = "green"
            icon = "parking"
        elif avail_pct > 20:
            color = "orange"
            icon = "parking"
        else:
            color = "red"
            icon = "ban"
        
        # Parse features
        features = space[15] if isinstance(space[15], dict) else {}
        
        # Create enhanced popup content
        popup_html = f"""
        <div style="width: 250px">
            <h4>{space[2]}</h4>
            <p><b>Address:</b> {space[3]}</p>
            <p><b>Availability:</b> {space[7]}/{space[6]} spaces</p>
            <p><b>Price:</b> ₹{space[8]}/hr</p>
            {space[10] and f'<p><b>EV Charging:</b> ₹{space[11]}/hr</p>'}
            {distance and f'<p><b>Distance:</b> {distance}</p>'}
            <p><b>Type:</b> {'Public' if space[9] else 'Private'}</p>
            <p><b>Features:</b></p>
            <ul>
                {''.join([f'<li>{feature}</li>' for feature in features.keys() if features[feature]])}
            </ul>
        </div>
        """
        
        # Create marker with custom icon
        folium.Marker(
            location=[space[4], space[5]],
            popup=folium.Popup(popup_html, max_width=300),
            icon=folium.Icon(color=color, icon=icon)
        ).add_to(m)
    
    # Add layer control
    folium.LayerControl().add_to(m)
    
    # Add measure control
    folium.plugins.MeasureControl(
        position='topright',
        primary_length_unit='kilometers',
        secondary_length_unit='miles'
    ).add_to(m)
    
    return m

# ======================
# STREAMLIT UI COMPONENTS
# ======================
def login_page():
    st.title("Login to Easy Dock")
    
    with st.form("login_form"):
        email = st.text_input("Email", placeholder="your@email.com")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")
        
        if submit:
            if not email or not password:
                st.error("Please enter both email and password")
                return
                
            if verify_login(email, password):
                st.success("Login successful! Redirecting...")
                st.session_state.page = "home"
                time.sleep(1)
                st.rerun()

def register_page():
    st.title("Create New Account")
    
    with st.form("register_form"):
        name = st.text_input("Full Name", placeholder="John Doe")
        email = st.text_input("Email", placeholder="your@email.com")
        phone = st.text_input("Phone Number", placeholder="+1234567890")
        password = st.text_input("Password", type="password")
        confirm_password = st.text_input("Confirm Password", type="password")
        user_type = st.selectbox("Account Type", ["user", "owner"])
        
        submitted = st.form_submit_button("Register")
        if submitted:
            if not all([name, email, phone, password, confirm_password]):
                st.error("Please fill all fields")
                return
                
            if password != confirm_password:
                st.error("Passwords don't match!")
                return
                
            if len(password) < 8:
                st.error("Password must be at least 8 characters")
                return
                
            if register_user(name, email, password, user_type, phone):
                st.success("Registration successful! Please login.")
                st.session_state.page = "login"
                time.sleep(2)
                st.rerun()

from PIL import Image, ImageDraw, ImageFont  # Added ImageFont import
import random

def home_page():
    # Main title with big font and vibrant styling
    st.markdown("""
    <h1 style='text-align: center; 
                font-size: 4rem; 
                color: #FF6B6B;
                margin-bottom: 0;
                font-weight: 800;
                text-shadow: 2px 2px 4px rgba(0,0,0,0.1);'>
    EasyDock
    </h1>
    """, unsafe_allow_html=True)
    
    # Tagline with complementary color
    st.markdown("""
    <h3 style='text-align: center; 
               font-style: italic; 
               color: #4ECDC4;
               margin-top: 0;
               font-weight: 400;
               font-size: 1.5rem;
               text-shadow: 1px 1px 2px rgba(0,0,0,0.1);'>
    Anchor your car, and sail through the city!
    </h3>
    """, unsafe_allow_html=True)
    
    st.markdown("---")  # Horizontal line for separation
    
    # Featured parking spaces with improved visuals
    st.subheader("🚗 Featured Parking Locations")
    
    try:
        parking_spaces = get_all_parking_spaces({'verified_only': True})[:3]
        
        if not parking_spaces:
            st.warning("No verified parking spaces available yet.")
        else:
            cols = st.columns(min(3, len(parking_spaces)))
            
            for i, space in enumerate(parking_spaces):
                with cols[i]:
                    with st.container(border=True):
                        # Create modern parking lot visualization
                        img = Image.new('RGB', (400, 250), color=(248, 249, 250))  # Light gray background
                        draw = ImageDraw.Draw(img)
                        
                        # Draw parking lot structure
                        draw.rectangle([20, 20, 380, 230], outline=(200, 200, 200), width=2)
                        
                        # Draw parking lanes
                        for y in [70, 140, 210]:
                            draw.line([20, y, 380, y], fill=(200, 200, 200), width=1)
                        
                        # Draw parking spaces (6 spots in 2 rows)
                        spot_colors = []
                        for row in range(2):
                            for col in range(3):
                                available = random.random() > 0.4
                                spot_colors.append((76, 175, 80) if available else (244, 67, 54))  # Green/Red
                                
                                x1 = 40 + col * 110
                                y1 = 40 + row * 80
                                x2 = x1 + 80
                                y2 = y1 + 50
                                
                                # Parking spot
                                draw.rounded_rectangle([x1, y1, x2, y2], 
                                                     radius=8,
                                                     fill=spot_colors[-1],
                                                     outline=(255, 255, 255),
                                                     width=2)
                                
                                # Parking number
                                spot_num = row * 3 + col + 1
                                draw.text(((x1+x2)/2, (y1+y2)/2), 
                                         f"{spot_num}",
                                         fill=(255, 255, 255),
                                         anchor="mm",
                                         font=ImageFont.load_default(size=14))
                        
                        # Add info overlay
                        available_count = sum(1 for color in spot_colors if color == (76, 175, 80))
                        draw.rectangle([20, 180, 380, 220], fill=(255, 255, 255, 128))
                        draw.text((200, 200),
                                f"{available_count}/6 spots available",
                                fill=(0, 0, 0),
                                anchor="mm",
                                font=ImageFont.load_default(size=12))
                        
                        # Add parking lot name
                        draw.text((200, 20),
                                f"{space[2][:20]}",
                                fill=(33, 33, 33),
                                anchor="mt",
                                font=ImageFont.load_default(size=14))
                        
                        st.image(img, use_container_width=True)
                        
                        # Space information
                        st.subheader(f"📍 {space[2]}", divider="blue")
                        st.caption(f"🚏 {space[3][:30]}...")
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            st.metric("Price", f"₹{space[8]}/hour")
                        with col2:
                            if space[10]:
                                st.metric("EV Charging", f"₹{space[11]}/hour")
                            else:
                                st.metric("EV Charging", "Not available")
                        
                        if st.button("Book Now", key=f"featured_{space[0]}", type="primary"):
                            if 'user' in st.session_state:
                                st.session_state.confirm_space = space
                                st.session_state.show_confirmation = True
                                st.rerun()
                            else:
                                st.session_state.page = "login"
                                st.rerun()

            # Confirmation dialog
            if 'show_confirmation' in st.session_state and st.session_state.show_confirmation:
                space = st.session_state.confirm_space
                st.warning(f"Confirm booking at {space[2]} for ₹{space[8]}/hour?")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Yes, Confirm Booking", type="primary"):
                        st.session_state.booking_space = space
                        st.session_state.page = "booking"
                        st.session_state.show_confirmation = False
                        st.rerun()
                with col2:
                    if st.button("No, Cancel", type="secondary"):
                        st.session_state.show_confirmation = False
                        st.rerun()
    except Exception as e:
        st.error(f"Couldn't load parking data: {str(e)}")

def find_parking_page():
    st.title("Find Parking")
    
    # Initialize filters in session state
    if 'filters' not in st.session_state:
        st.session_state.filters = {
            'verified_only': True,
            'ev_charging': False,
            'max_price': 100,
            'min_spaces': 0,
            'parking_type': "All",
            'use_location': False
        }
    
    # Location detection section
    with st.expander("Location Settings", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Detect My Location", key="detect_location_btn"):
                try:
                    with st.spinner("Detecting your location..."):
                        user_location = get_user_location()
                        if user_location and len(user_location) == 2:
                            st.session_state.user_location = user_location
                            st.success(f"Location detected: {user_location[0]:.4f}, {user_location[1]:.4f}")
                        else:
                            st.warning("Could not detect precise location. Showing all listings.")
                except Exception as e:
                    st.error(f"Location error: {str(e)}")
        
        with col2:
            if st.button("Clear Location", key="clear_location_btn"):
                if 'user_location' in st.session_state:
                    del st.session_state.user_location
                st.success("Location cleared!")
    
    # Filters section
    with st.expander("Filters", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.session_state.filters['ev_charging'] = st.checkbox(
                "EV Charging Only", 
                value=st.session_state.filters['ev_charging'],
                key="ev_charging_checkbox"
            )
            st.session_state.filters['min_spaces'] = st.number_input(
                "Minimum Available Spaces", 
                0, 50, st.session_state.filters['min_spaces'],
                key="min_spaces_input"
            )
            st.session_state.filters['parking_type'] = st.radio(
                "Parking Type",
                ["All", "Public Only", "Private Only"],
                index=["All", "Public Only", "Private Only"].index(
                    st.session_state.filters['parking_type']
                ),
                key="parking_type_radio"
            )
        with col2:
            st.session_state.filters['max_price'] = st.slider(
                "Max Price per Hour (₹)", 
                10, 500, st.session_state.filters['max_price'],
                key="max_price_slider"
            )
            st.session_state.filters['verified_only'] = st.checkbox(
                "Verified Only",
                value=st.session_state.filters['verified_only'],
                key="verified_only_checkbox"
            )
        with col3:
            vehicle_type = st.selectbox(
                "Vehicle Type", 
                ["Car", "Motorcycle", "SUV", "Truck", "EV"],
                key="vehicle_type_select"
            )
            features = st.multiselect(
                "Additional Features",
                ["24/7 Security", "Covered Parking", "Valet Service", "Disabled Access"],
                key="features_multiselect"
            )
    
    # Apply parking type filters
    if st.session_state.filters['parking_type'] == "Public Only":
        st.session_state.filters['public_only'] = True
        st.session_state.filters['private_only'] = False
    elif st.session_state.filters['parking_type'] == "Private Only":
        st.session_state.filters['public_only'] = False
        st.session_state.filters['private_only'] = True
    else:
        st.session_state.filters['public_only'] = False
        st.session_state.filters['private_only'] = False
    
    # Get parking spaces with error handling
    try:
        parking_spaces = get_all_parking_spaces(st.session_state.filters)
        
        if not parking_spaces or len(parking_spaces) == 0:
            st.warning("No verified parking spaces available. Please try different filters.")
            return
        
        if 'user_location' in st.session_state:
            parking_spaces = get_nearby_parking(
                st.session_state.user_location, 
                radius_km=5,
                filters=st.session_state.filters
            )
        
        # Display map and listings
        st.subheader("Parking Map")
        user_location = st.session_state.user_location if 'user_location' in st.session_state else None
        parking_map = show_parking_map(parking_spaces, user_location)
        st_folium(parking_map, width=700, height=500, returned_objects=[])
        
        st.subheader("Available Parking")
        if not parking_spaces:
            st.warning("No parking spaces match your criteria. Try adjusting filters.")
        else:
            for i, space in enumerate(parking_spaces):
                if not space or len(space) < 12:  # Validate space data
                    continue
                
                # Safely parse features JSON
                features = {}
                if len(space) > 15 and space[15]:  # features column
                    try:
                        features = json.loads(space[15]) if isinstance(space[15], str) else space[15]
                    except:
                        features = {}
                
                # Using expander without key parameter
                with st.expander(f"{space[2]} - ₹{space[8]}/hr ({space[7]} available)"):
                    col1, col2 = st.columns([1, 2])
                    with col1:
                        # Create parking spot visualization
                        img = Image.new('RGB', (250, 150), color=(50, 150, 50))
                        draw = ImageDraw.Draw(img)
                        spot_color = (0, 200, 0) if space[7] > 0 else (200, 0, 0)
                        draw.rectangle([50, 50, 200, 100], fill=spot_color, outline=(255, 255, 255))
                        draw.text([75, 65], f"Spot {space[0]}", fill=(0, 0, 0))
                        draw.text([75, 85], f"{space[7]} available", fill=(0, 0, 0))
                        st.image(img, use_container_width=True)
                    
                    with col2:
                        st.write(f"**Address:** {space[3]}")
                        st.write(f"**Spaces:** {space[7]}/{space[6]} available")
                        st.write(f"**Price:** ₹{space[8]}/hour")
                        if len(space) > 10 and space[10]:  # EV charging available
                            st.write(f"**EV Charging:** ₹{space[11]}/hour")
                        st.write(f"**Type:** {'Public' if space[9] else 'Private'}")
                        
                        if 'user_location' in st.session_state:
                            space_loc = (space[4], space[5])
                            dist_km = geodesic(st.session_state.user_location, space_loc).km
                            st.write(f"**Distance:** {dist_km:.1f} km")
                        
                        if features:
                            st.write("**Features:**")
                            cols = st.columns(3)
                            for j, (feature, available) in enumerate(features.items()):
                                if available:
                                    cols[j%3].write(f"✓ {feature}")
                        
                        if st.button("Book Now", key=f"book_{space[0]}_{i}"):
                            if 'user' not in st.session_state:
                                st.session_state.page = "login"
                                st.rerun()
                            else:
                                st.session_state.booking_space = space
                                st.session_state.show_confirmation = True
                                st.rerun()

            # Confirmation dialog
            if 'show_confirmation' in st.session_state and st.session_state.show_confirmation:
                if 'booking_space' not in st.session_state or not st.session_state.booking_space:
                    st.error("Invalid parking space selection")
                    st.session_state.show_confirmation = False
                    st.rerun()
                
                space = st.session_state.booking_space
                st.warning(f"Confirm booking at {space[2]} for ₹{space[8]}/hour?")
                
                duration = st.slider("Duration (hours)", 1, 24, 2)
                total_cost = duration * space[8]
                if len(space) > 10 and space[10]:  # If EV charging available
                    use_ev = st.checkbox("Use EV Charging", value=False)
                    if use_ev:
                        total_cost += duration * space[11]
                
                st.write(f"**Total Estimated Cost:** ₹{total_cost:.2f}")
                
                # Get user's default vehicle if exists
                default_vehicle = None
                if 'user' in st.session_state and st.session_state.user.get('vehicles'):
                    for vehicle in st.session_state.user['vehicles']:
                        if vehicle[7]:  # is_default field
                            default_vehicle = vehicle
                            break
                
                vehicle_type = st.selectbox(
                    "Vehicle Type",
                    ["Car", "Motorcycle", "SUV", "Truck", "EV"],
                    index=["Car", "Motorcycle", "SUV", "Truck", "EV"].index(default_vehicle[2]) if default_vehicle else 0
                )
                
                license_plate = st.text_input(
                    "License Plate",
                    value=default_vehicle[3] if default_vehicle else "KA01AB1234"
                )
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Yes, Confirm Booking"):
                        if not license_plate:
                            st.error("Please enter a license plate number")
                            st.stop()
                            
                        try:
                            booking_data = {
                                "start_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                                "end_time": (datetime.datetime.now() + datetime.timedelta(hours=duration)).strftime("%Y-%m-%d %H:%M"),
                                "space_number": 1,
                                "vehicle_type": vehicle_type,
                                "license_plate": license_plate,
                                "use_ev_charging": use_ev if len(space) > 10 and space[10] else False,
                                "payment_method": "wallet"
                            }
                            
                            with st.spinner("Processing your booking..."):
                                result = make_reservation(
                                    st.session_state.user['id'],
                                    space[0],
                                    booking_data
                                )
                                
                                if result['success']:
                                    st.session_state.reservation_id = result['reservation_id']
                                    st.session_state.payment_amount = total_cost
                                    st.session_state.show_confirmation = False
                                    st.session_state.page = "payment"
                                    st.rerun()
                                else:
                                    st.error(f"Booking failed: {result['message']}")
                        except Exception as e:
                            st.error(f"An error occurred: {str(e)}")
                
                with col2:
                    if st.button("Cancel", key="cancel_booking"):
                        st.session_state.show_confirmation = False
                        st.rerun()

    except Exception as e:
        st.error(f"Error loading parking data: {str(e)}")
def booking_page():
    # Validate booking space exists
    if 'booking_space' not in st.session_state or not st.session_state.booking_space:
        st.error("No valid parking space selected")
        st.session_state.page = "find_parking"
        st.rerun()
    
    space = st.session_state.booking_space
    
    # Validate space data structure
    if not space or len(space) < 12:
        st.error("Invalid parking space data")
        st.session_state.page = "find_parking"
        st.rerun()
    
    # Check if user is logged in
    if 'user' not in st.session_state or not st.session_state.user:
        st.warning("Please login to book parking")
        st.session_state.page = "login"
        st.rerun()
    
    st.title(f"Booking: {space[2]}")
    
    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**Address:** {space[3]}")
            st.write(f"**Price:** ₹{space[8]}/hour")
            if len(space) > 10 and space[10]:  # EV charging
                st.write(f"**EV Charging:** ₹{space[11]}/hour")
            st.write(f"**Type:** {'Public' if space[9] else 'Private'}")
        with col2:
            st.write(f"**Available Spaces:** {space[7]}/{space[6]}")
            if 'user_location' in st.session_state:
                space_loc = (space[4], space[5])
                dist_km = geodesic(st.session_state.user_location, space_loc).km
                st.write(f"**Distance:** {dist_km:.1f} km")
    
    # Booking form with proper submit button
    with st.form("booking_form", clear_on_submit=True):
        st.subheader("Booking Details")
        
        col1, col2 = st.columns(2)
        with col1:
            date = st.date_input("Date", min_value=datetime.date.today())
            start_time = st.time_input("Start Time")
        with col2:
            duration = st.slider("Duration (hours)", 1, 24, 2)
            end_time = (datetime.datetime.combine(date, start_time) + datetime.timedelta(hours=duration)).time()
            st.write(f"**End Time:** {end_time.strftime('%H:%M')}")
        
        st.subheader("Vehicle Information")
        
        # Vehicle selection with proper initialization
        user_vehicles = st.session_state.user.get('vehicles', [])
        vehicle_options = []
        
        if user_vehicles:
            vehicle_options = [f"{v[2]} ({v[3]})" for v in user_vehicles]
            selected_vehicle = st.selectbox("Select Vehicle", vehicle_options)
            vehicle_idx = vehicle_options.index(selected_vehicle)
            vehicle_type = user_vehicles[vehicle_idx][2]
            license_plate = user_vehicles[vehicle_idx][3]
            is_ev = user_vehicles[vehicle_idx][4]
        else:
            vehicle_type = st.selectbox("Vehicle Type", ["Car", "Motorcycle", "SUV", "Truck", "EV"])
            license_plate = st.text_input("License Plate", value="KA01AB1234")
            is_ev = vehicle_type == "EV"
        
        # EV charging option
        use_ev_charging = False
        if len(space) > 10 and space[10] and is_ev:  # Parking has EV charging and vehicle is EV
            use_ev_charging = st.checkbox("Use EV Charging", value=True)
        
        st.subheader("Payment Method")
        
        # Payment method selection with wallet balance check
        wallet_balance = st.session_state.user.get('wallet_balance', 0)
        payment_options = []
        
        if wallet_balance > space[8] * 2:  # At least 2 hours worth in wallet
            payment_options.append("Wallet")
        
        if st.session_state.user.get('fastag_id'):
            payment_options.append("FASTag")
        
        if st.session_state.user.get('nfc_card_id'):
            payment_options.append("NFC")
        
        payment_options.extend(["Credit Card", "Debit Card"])
        
        payment_method = st.radio("Select Payment", payment_options)
        
        # Proper form submit button
        submitted = st.form_submit_button("Confirm Booking")
        
        if submitted:
            # Validate form data
            if not license_plate or not vehicle_type:
                st.error("Please provide complete vehicle information")
                st.stop()
            
            # Prepare booking data
            booking_data = {
                "start_time": f"{date} {start_time}",
                "end_time": f"{date} {end_time}",
                "space_number": 1,  # Simplified for demo
                "vehicle_type": vehicle_type,
                "license_plate": license_plate,
                "use_ev_charging": use_ev_charging,
                "payment_method": payment_method.lower().replace(" ", "_")
            }
            
            # Create reservation
            with st.spinner("Processing your booking..."):
                result = make_reservation(
                    st.session_state.user['id'],
                    space[0],
                    booking_data
                )
                
                if result['success']:
                    st.session_state.reservation_id = result['reservation_id']
                    st.session_state.payment_amount = result['amount']
                    st.session_state.page = "payment"
                    st.rerun()
                else:
                    st.error(f"Booking failed: {result['message']}")
def payment_page():
    if 'reservation_id' not in st.session_state or 'payment_amount' not in st.session_state:
        st.error("Invalid payment request - missing reservation details")
        st.session_state.page = "reservations"
        time.sleep(1)
        st.rerun()
        return
    
    st.title("Complete Payment")
    
    # Get reservation details with error handling
    try:
        conn = sqlite3.connect('smart_parking.db')
        c = conn.cursor()
        c.execute('''SELECT r.id, r.total_cost, p.name, r.start_time, r.end_time, 
                    r.payment_method, r.payment_status, r.vehicle_type, r.license_plate,
                    r.ev_charging_cost, r.user_id
                    FROM reservations r
                    JOIN parking_spaces p ON r.parking_id = p.id
                    WHERE r.id=?''', (st.session_state.reservation_id,))
        res = c.fetchone()
        
        if not res:
            st.error("Reservation not found in database")
            st.session_state.page = "find_parking"
            st.rerun()
    except Exception as e:
        st.error(f"Database error: {str(e)}")
        st.session_state.page = "reservations"
        st.rerun()
    finally:
        conn.close()
    
    reservation_id, total_cost, parking_name, start_time, end_time, payment_method, payment_status, vehicle_type, license_plate, ev_charging_cost, user_id = res
    
    # Check if already paid
    if payment_status == 'completed':
        st.success("Payment already completed for this reservation!")
        if st.button("Return to Reservations"):
            st.session_state.page = "reservations"
            st.rerun()
        return
    
    # Display reservation summary
    with st.container(border=True):
        st.subheader("Reservation Summary")
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**Parking:** {parking_name}")
            st.write(f"**Vehicle:** {vehicle_type} ({license_plate})")
        with col2:
            st.write(f"**Time:** {start_time} to {end_time}")
            st.write(f"**Reservation ID:** #{reservation_id}")
        
        st.metric("Total Amount Due", f"₹{total_cost:.2f}")
        if ev_charging_cost > 0:
            st.write(f"**Includes EV Charging:** ₹{ev_charging_cost:.2f}")

    # Payment method selection
    st.subheader("Select Payment Method")
    
    # Get user's wallet balance
    wallet_balance = st.session_state.user.get('wallet_balance', 0)
    
    # Create payment method tabs
    tab1, tab2, tab3 = st.tabs(["Wallet", "Card", "FASTag/NFC"])
    
    with tab1:
        st.write("**Wallet Balance**")
        st.write(f"Available: ₹{wallet_balance:.2f}")
        
        if wallet_balance >= total_cost:
            if st.button("Pay with Wallet", key="pay_wallet"):
                with st.spinner("Processing payment..."):
                    result = process_payment(
                        user_id,
                        reservation_id,
                        'wallet',
                        total_cost
                    )
                    if result['success']:
                        st.success(f"Payment successful! Transaction ID: {result['transaction_id']}")
                        # Update session state
                        st.session_state.user['wallet_balance'] -= total_cost
                        st.session_state.user['reward_points'] += result.get('reward_points', 0)
                        time.sleep(2)
                        st.session_state.page = "reservations"
                        st.rerun()
                    else:
                        st.error(f"Payment failed: {result['message']}")
                        st.rerun()  # Add this to prevent form resubmission issues
        else:
            st.error("Insufficient wallet balance")
            if st.button("Add Funds to Wallet"):
                st.session_state.page = "rewards"
                st.rerun()

    with tab2:
        with st.form("card_payment_form"):
            st.write("**Credit/Debit Card**")
            st.write("Visa, Mastercard, etc.")
            
            card_number = st.text_input("Card Number", placeholder="1234 5678 9012 3456", key="card_number")
            expiry = st.text_input("Expiry Date", placeholder="MM/YY", key="expiry")
            cvv = st.text_input("CVV", placeholder="123", type="password", key="cvv")
            card_name = st.text_input("Cardholder Name", key="card_name")
            
            submitted = st.form_submit_button("Pay with Card")
            if submitted:
                if not all([card_number.strip(), expiry.strip(), cvv.strip(), card_name.strip()]):
                    st.error("Please fill all card details")
                    st.stop()  # Use stop() instead of return to prevent form resubmission
                
                with st.spinner("Processing card payment..."):
                    result = process_payment(
                        user_id,
                        reservation_id,
                        'credit_card',
                        total_cost
                    )
                    if result['success']:
                        st.success(f"Payment successful! Transaction ID: {result['transaction_id']}")
                        st.session_state.user['reward_points'] += result.get('reward_points', 0)
                        time.sleep(2)
                        st.session_state.page = "reservations"
                        st.rerun()
                    else:
                        st.error(f"Payment failed: {result['message']}")
                        st.rerun()

    with tab3:
        st.write("**FASTag/NFC Payment**")
        st.write("Contactless payment using linked devices")
        
        if st.session_state.user.get('fastag_id'):
            if st.button("Pay with FASTag", key="pay_fastag"):
                with st.spinner("Processing FASTag payment..."):
                    result = process_payment(
                        user_id,
                        reservation_id,
                        'fastag',
                        total_cost
                    )
                    if result['success']:
                        st.success(f"Payment successful! Transaction ID: {result['transaction_id']}")
                        st.session_state.user['reward_points'] += result.get('reward_points', 0)
                        time.sleep(2)
                        st.session_state.page = "reservations"
                        st.rerun()
                    else:
                        st.error(f"Payment failed: {result['message']}")
                        st.rerun()
        else:
            st.warning("No FASTag/NFC device linked to your account")
            if st.button("Link FASTag/NFC"):
                st.session_state.page = "profile"  # Assuming you have a profile page
                st.rerun()
                    
def process_payment_selection(method, amount):
    st.session_state.selected_payment_method = method
    st.session_state.payment_amount = amount
    st.rerun()

def reservations_page():
    if 'user' not in st.session_state:
        st.warning("Please login to view reservations")
        st.session_state.page = "login"
        st.rerun()
    
    st.title("My Reservations & Vehicles")
    
    # Refresh user data from database
    refresh_user_data()
    
    # Tab layout
    tab1, tab2, tab3 = st.tabs(["Active Reservations", "Past Bookings", "My Vehicles"])
    
    with tab1:
        st.subheader("Active Reservations")
        conn = sqlite3.connect('smart_parking.db')
        c = conn.cursor()
    
    try:
        # Get active reservations (future or ongoing)
        query = '''SELECT r.id, p.name, p.address, r.start_time, r.end_time, 
                  r.total_cost, r.payment_status, r.vehicle_type, r.license_plate,
                  r.ev_charging_cost, p.latitude, p.longitude, r.space_number
                  FROM reservations r
                  JOIN parking_spaces p ON r.parking_id = p.id
                  WHERE r.user_id=? AND datetime(r.end_time) > datetime('now') 
                  AND r.payment_status != 'cancelled'
                  ORDER BY r.start_time ASC'''
        
        c.execute(query, (st.session_state.user['id'],))
        active_reservations = c.fetchall()
        
        if not active_reservations:
            st.info("No active reservations found.")
            if st.button("Find Parking", key="find_parking_from_active"):
                st.session_state.page = "find_parking"
                st.rerun()
        else:
            for res in active_reservations:
                with st.expander(f"Reservation #{res[0]} - {res[1]} (Space {res[12]})", expanded=True):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Location:** {res[2]}")
                        st.write(f"**Vehicle:** {res[7]} ({res[8]})")
                        st.write(f"**Space Number:** {res[12]}")
                        st.write(f"**Time:** {res[3]} to {res[4]}")
                        
                        now = datetime.datetime.now()
                        try:
                            # Handle different datetime formats
                            try:
                                start_time = datetime.datetime.strptime(res[3], "%Y-%m-%d %H:%M:%S")
                            except ValueError:
                                start_time = datetime.datetime.strptime(res[3], "%Y-%m-%d %H:%M")
                            
                            try:
                                end_time = datetime.datetime.strptime(res[4], "%Y-%m-%d %H:%M:%S")
                            except ValueError:
                                end_time = datetime.datetime.strptime(res[4], "%Y-%m-%d %H:%M")
                            
                            if now < start_time:
                                st.write(f"**Starts in:** {humanize.naturaltime(start_time - now)}")
                            else:
                                st.write(f"**Ends in:** {humanize.naturaltime(end_time - now)}")
                        except Exception as e:
                            st.warning(f"Could not parse reservation times: {str(e)}")
                        
                    with col2:
                        st.write(f"**Total Cost:** ₹{res[5]:.2f}")
                        if res[9] > 0:
                            st.write(f"**EV Charging Cost:** ₹{res[9]:.2f}")
                        st.write(f"**Status:** {res[6].capitalize()}")
                        
                        # Show parking space on map
                        try:
                            m = folium.Map(location=[res[10], res[11]], zoom_start=15)
                            folium.Marker([res[10], res[11]], popup=res[1]).add_to(m)
                            st_folium(m, width=300, height=200)
                        except:
                            st.warning("Could not display map for this location")
                    
                    # Action buttons
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        if res[6] == 'pending':  # If payment_status is 'pending'
                            if st.button("Complete Payment", key=f"pay_{res[0]}"):
                                st.session_state.reservation_id = res[0]  # Store reservation ID
                                st.session_state.payment_amount = res[5]  # Store amount
                                st.session_state.page = "payment"
                                print(f"🔵 DEBUG: Updated session_state.page = {st.session_state.page}")  # Check value
                                st.rerun()  # Refresh to load the payment page
                    with col2:
                        if st.button("Extend Booking", key=f"extend_{res[0]}"):
                            st.session_state.extend_reservation = res[0]
                            st.session_state.page = "extend_booking"
                            st.rerun()
                    with col3:
                        if st.button("Cancel Booking", key=f"cancel_{res[0]}", type="secondary"):
                            result = handle_cancel_booking(res[0])
                            if result['success']:
                                st.success(result['message'])
                                if 'refund_amount' in result and result['refund_amount'] > 0:
                                    st.success(f"₹{result['refund_amount']:.2f} has been refunded to your wallet")
                                time.sleep(2)
                                st.rerun()
                            else:
                                st.error(result['message'])
    finally:
        conn.close()
    
    with tab2:
        st.subheader("Past Bookings")
        conn = sqlite3.connect('smart_parking.db')
        c = conn.cursor()
        
        try:
            # Get past reservations
            query = '''SELECT r.id, p.name, p.address, r.start_time, r.end_time, 
                      r.total_cost, r.payment_status, r.vehicle_type, r.license_plate,
                      r.ev_charging_cost, p.latitude, p.longitude
                      FROM reservations r
                      JOIN parking_spaces p ON r.parking_id = p.id
                      WHERE r.user_id=? AND (datetime(r.end_time) <= datetime('now') OR r.payment_status = 'cancelled')
                      ORDER BY r.end_time DESC'''
            
            c.execute(query, (st.session_state.user['id'],))
            past_reservations = c.fetchall()
            
            if not past_reservations:
                st.info("No past reservations found.")
            else:
                for res in past_reservations:
                    with st.container(border=True):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.write(f"**Parking:** {res[1]}")
                            st.write(f"**Address:** {res[2]}")
                            st.write(f"**Vehicle:** {res[7]} ({res[8]})")
                        with col2:
                            st.write(f"**Time:** {res[3]} to {res[4]}")
                            st.write(f"**Total Cost:** ₹{res[5]:.2f}")
                            if res[9] > 0:
                                st.write(f"**EV Charging Cost:** ₹{res[9]:.2f}")
                            st.write(f"**Status:** {res[6].capitalize()}")
        finally:
            conn.close()
    
    with tab3:
        st.subheader("My Vehicles")
        
        # Display current vehicles
        if not st.session_state.user.get('vehicles'):
            st.info("No vehicles registered yet.")
        else:
            for i, vehicle in enumerate(st.session_state.user['vehicles']):
                with st.container(border=True):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.write(f"**Type:** {vehicle[2]}")
                        st.write(f"**License Plate:** {vehicle[3]}")
                        st.write(f"**EV:** {'Yes' if vehicle[4] else 'No'}")
                        st.write(f"**Default:** {'Yes' if vehicle[7] else 'No'}")
                    with col2:
                        if st.button("Remove", key=f"remove_{vehicle[0]}"):
                            remove_vehicle(vehicle[0])
                            st.rerun()
        
        # Add new vehicle form
        with st.expander("Add New Vehicle"):
            with st.form("add_vehicle_form"):
                vehicle_type = st.selectbox("Vehicle Type", ["Car", "Motorcycle", "SUV", "Truck", "EV"])
                license_plate = st.text_input("License Plate", placeholder="KA01AB1234")
                is_ev = st.checkbox("Electric Vehicle", value=(vehicle_type == "EV"))
                is_default = st.checkbox("Set as Default Vehicle")
                
                if st.form_submit_button("Add Vehicle"):
                    if add_user_vehicle(st.session_state.user['id'], vehicle_type, license_plate, is_ev, is_default):
                        st.success("Vehicle added successfully!")
                        time.sleep(1)
                        st.rerun()
def refresh_user_data():
    """Refresh user data from database"""
    conn = sqlite3.connect('smart_parking.db')
    c = conn.cursor()
    
    # Refresh user data
    c.execute('''SELECT id, name, email, user_type, wallet_balance, 
                reward_points, phone, nfc_card_id, fastag_id FROM users WHERE id=?''', 
              (st.session_state.user['id'],))
    user = c.fetchone()
    
    # Refresh vehicles
    c.execute("SELECT * FROM user_vehicles WHERE user_id=?", (st.session_state.user['id'],))
    vehicles = c.fetchall()
    
    st.session_state.user = {
        'id': user[0],
        'name': user[1],
        'email': user[2],
        'user_type': user[3],
        'wallet_balance': user[4],
        'reward_points': user[5],
        'phone': user[6],
        'nfc_card_id': user[7],
        'fastag_id': user[8],
        'vehicles': vehicles
    }
    
    conn.close()

def remove_vehicle(vehicle_id):
    conn = sqlite3.connect('smart_parking.db')
    c = conn.cursor()
    try:
        c.execute("DELETE FROM user_vehicles WHERE id=?", (vehicle_id,))
        conn.commit()
        st.success("Vehicle removed successfully!")
        refresh_user_data()
    except Exception as e:
        conn.rollback()
        st.error(f"Failed to remove vehicle: {str(e)}")
    finally:
        conn.close()

def extend_booking_page():
    if 'extend_reservation' not in st.session_state:
        st.warning("No reservation selected for extension")
        st.session_state.page = "reservations"
        st.rerun()
    
    reservation_id = st.session_state.extend_reservation
    
    # Get reservation details with error handling
    try:
        conn = sqlite3.connect('smart_parking.db')
        c = conn.cursor()
        c.execute('''SELECT r.parking_id, r.end_time, p.price_per_hour, 
                    p.has_ev_charging, p.ev_charging_price, r.ev_charging_cost,
                    r.space_number
                    FROM reservations r
                    JOIN parking_spaces p ON r.parking_id = p.id
                    WHERE r.id=?''', (reservation_id,))
        res = c.fetchone()
        
        if not res:
            st.error("Reservation not found")
            st.session_state.page = "reservations"
            st.rerun()
    except Exception as e:
        st.error(f"Database error: {str(e)}")
        st.session_state.page = "reservations"
        st.rerun()
    finally:
        conn.close()
    
    parking_id, current_end, price_per_hour, has_ev, ev_price, current_ev_cost, space_number = res
    
    try:
        current_end = datetime.datetime.strptime(current_end, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            current_end = datetime.datetime.strptime(current_end, "%Y-%m-%d %H:%M")
        except ValueError as e:
            st.error(f"Invalid datetime format: {str(e)}")
            st.session_state.page = "reservations"
            st.rerun()
    
    st.title("Extend Booking")
    st.write(f"Current end time: {current_end.strftime('%Y-%m-%d %H:%M')}")
    
    with st.form("extend_booking_form"):
        duration = st.slider("Additional Hours", 1, 12, 1)
        new_end = current_end + datetime.timedelta(hours=duration)
        st.write(f"New end time: {new_end.strftime('%Y-%m-%d %H:%M')}")
        
        # Calculate additional cost
        additional_parking_cost = duration * price_per_hour
        additional_ev_cost = duration * ev_price if has_ev and current_ev_cost > 0 else 0
        total_additional = additional_parking_cost + additional_ev_cost
        
        st.metric("Additional Cost", f"₹{total_additional:.2f}")
        
        submitted = st.form_submit_button("Confirm Extension")
        if submitted:
            conn = sqlite3.connect('smart_parking.db')
            c = conn.cursor()
            
            try:
                # Check if space is still available
                c.execute('''SELECT available_spaces FROM parking_spaces WHERE id=?''', (parking_id,))
                available = c.fetchone()[0]
                
                if available <= 0:
                    st.error("No available spaces to extend booking")
                    return
                
                # Update reservation
                c.execute('''UPDATE reservations 
                            SET end_time=?, 
                                total_cost=total_cost+?,
                                ev_charging_cost=ev_charging_cost+?
                            WHERE id=?''',
                         (new_end.strftime("%Y-%m-%d %H:%M:%S"), 
                          additional_parking_cost,
                          additional_ev_cost,
                          reservation_id))
                
                # Update sensor status if needed
                c.execute('''UPDATE sensors 
                            SET last_updated=CURRENT_TIMESTAMP
                            WHERE parking_id=? AND space_number=?''',
                         (parking_id, space_number))
                
                conn.commit()
                st.success("Booking extended successfully!")
                
                # Update session state
                st.session_state.page = "reservations"
                time.sleep(1)
                st.rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"Failed to extend booking: {str(e)}")
                st.rerun()
            finally:
                conn.close()

def handle_cancel_booking(reservation_id):
    conn = sqlite3.connect('smart_parking.db')
    c = conn.cursor()
    
    try:
        # Get full reservation details
        c.execute('''SELECT r.parking_id, r.total_cost, r.payment_status, 
                    r.start_time, r.end_time, r.space_number, r.platform_earnings
                    FROM reservations r WHERE r.id=?''', (reservation_id,))
        res = c.fetchone()
        
        if not res:
            return {"success": False, "message": "Reservation not found"}
        
        parking_id, total_cost, payment_status, start_time_str, end_time_str, space_number, platform_earnings = res
        
        # Function to parse datetime with flexible format
        def parse_datetime(dt_str):
            try:
                return datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    return datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                except ValueError as e:
                    raise ValueError(f"Could not parse datetime string: {dt_str}") from e
        
        # Convert string times to datetime objects
        now = datetime.datetime.now()
        start_time = parse_datetime(start_time_str)
        end_time = parse_datetime(end_time_str)
        
        # Calculate refund amount based on time used
        hours_used = (now - start_time).total_seconds() / 3600
        total_hours = (end_time - start_time).total_seconds() / 3600
        refund_amount = total_cost * (1 - (hours_used / total_hours)) if total_hours > 0 else 0
        
        # Update parking space availability
        c.execute('''UPDATE parking_spaces 
                    SET available_spaces = available_spaces + 1 
                    WHERE id=?''', (parking_id,))
        
        # Update reservation status and set actual end time to now
        c.execute('''UPDATE reservations 
                    SET payment_status='cancelled',
                        actual_end_time=CURRENT_TIMESTAMP
                    WHERE id=?''', (reservation_id,))
        
        # Refund payment if already paid
        if payment_status == 'completed':
            # Record refund transaction
            transaction_id = f"refund_{int(time.time())}"
            c.execute('''INSERT INTO payments 
                        (user_id, reservation_id, amount, 
                        payment_method, transaction_id, status)
                        VALUES (?, ?, ?, ?, ?, ?)''',
                     (st.session_state.user['id'], reservation_id, refund_amount,
                      'refund', transaction_id, 'completed'))
            
            # Update user wallet if paid with wallet
            c.execute('''UPDATE users 
                        SET wallet_balance = wallet_balance + ?
                        WHERE id=?''', (refund_amount, st.session_state.user['id']))
            
            # Deduct platform earnings if applicable
            if platform_earnings and platform_earnings > 0:
                c.execute('''UPDATE parking_spaces 
                            SET total_earnings = total_earnings - ?
                            WHERE id=?''',
                         (platform_earnings, parking_id))
        
        # Update sensor status if space was occupied
        c.execute('''UPDATE sensors 
                    SET is_occupied=0 
                    WHERE parking_id=? AND space_number=?''',
                 (parking_id, space_number))
        
        conn.commit()
        return {"success": True, "message": "Reservation cancelled successfully", "refund_amount": refund_amount}
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": f"Failed to cancel reservation: {str(e)}"}
    finally:
        conn.close()
        
def rewards_page():
    if 'user' not in st.session_state:
        st.warning("Please login to view rewards")
        st.session_state.page = "login"
        st.rerun()
    
    st.title("Rewards & Wallet")
    
    # Refresh user data
    conn = sqlite3.connect('smart_parking.db')
    c = conn.cursor()
    c.execute("SELECT wallet_balance, reward_points FROM users WHERE id=?", (st.session_state.user['id'],))
    balance, points = c.fetchone()
    
    # Get loyalty program details
    c.execute("SELECT * FROM loyalty_programs WHERE is_active=1 LIMIT 1")
    loyalty_program = c.fetchone()
    conn.close()
    
    # Update session state
    st.session_state.user['wallet_balance'] = balance
    st.session_state.user['reward_points'] = points
    
    # Wallet section
    st.subheader("Wallet Balance")
    st.metric("Current Balance", f"₹{balance:.2f}")
    
    with st.expander("Add Money to Wallet"):
        amount = st.number_input("Amount to Add (₹)", min_value=100, max_value=10000, step=100)
        if st.button("Add Funds"):
            conn = sqlite3.connect('smart_parking.db')
            c = conn.cursor()
            try:
                c.execute("UPDATE users SET wallet_balance = wallet_balance + ? WHERE id=?", 
                         (amount, st.session_state.user['id']))
                conn.commit()
                st.success(f"₹{amount:.2f} added to your wallet!")
                st.session_state.user['wallet_balance'] += amount
                time.sleep(1)
                st.rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"Error adding funds: {str(e)}")
            finally:
                conn.close()
    
    # Rewards section
    st.subheader("Reward Program")
    
    if loyalty_program:
        st.write(f"**{loyalty_program[1]}**")
        st.write(loyalty_program[2])
        st.metric("Your Points", points)
        st.write(f"Earning rate: {loyalty_program[3]*100}% (1 point per ₹{1/loyalty_program[3]:.0f} spent)")
        
        if points >= loyalty_program[4]:
            vouchers = points // loyalty_program[4]
            st.write(f"You can redeem {vouchers} × ₹{loyalty_program[5]:.0f} vouchers ({loyalty_program[4]} points each)")
            if st.button(f"Redeem ₹{loyalty_program[5]:.0f} Voucher"):
                conn = sqlite3.connect('smart_parking.db')
                c = conn.cursor()
                points_used = vouchers * loyalty_program[4]
                amount = vouchers * loyalty_program[5]
                
                try:
                    c.execute('''UPDATE users 
                                SET wallet_balance = wallet_balance + ?,
                                    reward_points = reward_points - ?
                                WHERE id=?''', 
                            (amount, points_used, st.session_state.user['id']))
                    conn.commit()
                    st.success(f"Redeemed {vouchers} × ₹{loyalty_program[5]:.0f} vouchers! ₹{amount:.2f} added to your wallet.")
                    st.session_state.user['wallet_balance'] += amount
                    st.session_state.user['reward_points'] -= points_used
                    time.sleep(2)
                    st.rerun()
                except Exception as e:
                    conn.rollback()
                    st.error(f"Error redeeming points: {str(e)}")
                finally:
                    conn.close()
        else:
            st.warning(f"You need at least {loyalty_program[4]} points to redeem rewards")
    else:
        st.warning("No active loyalty program")

def admin_page():
    if 'user' not in st.session_state or st.session_state.user['user_type'] != 'admin':
        st.warning("Unauthorized access")
        st.session_state.page = "home"
        st.rerun()

    st.title("Admin Dashboard")
    
    # Set default tab if not specified
    if not st.session_state.admin_tab:
        st.session_state.admin_tab = "Verify Listings"
    
    # Create tabs
    tab_names = ["Verify Listings", "System Stats", "Database Tools", "Loyalty Program"]
    default_tab = tab_names.index(st.session_state.admin_tab)
    tab1, tab2, tab3, tab4 = st.tabs(tab_names)
    
    with tab1:
        st.subheader("Pending Verifications")
        conn = sqlite3.connect('smart_parking.db')
        c = conn.cursor()
        
        # Get pending verifications
        c.execute('''SELECT p.id, p.name, p.address, u.name as owner_name, 
                    p.total_spaces, p.price_per_hour, p.features, p.owner_id,
                    p.latitude, p.longitude, p.created_at
                    FROM parking_spaces p
                    JOIN users u ON p.owner_id = u.id
                    WHERE p.is_verified = 0 
                    AND (p.verification_notes IS NULL OR p.verification_notes NOT LIKE 'REJECTED:%')
                    ORDER BY p.created_at DESC''')
        pending_spaces = c.fetchall()
        
        if not pending_spaces:
            st.success("All caught up! No pending verifications.")
        else:
            st.info(f"Found {len(pending_spaces)} spaces needing verification")
            
            for i, space in enumerate(pending_spaces):
                # Create unique keys using space ID and index
                expander_key = f"expander_{space[0]}_{i}"
                map_key = f"map_{space[0]}_{i}"
                notes_key = f"notes_{space[0]}_{i}"
                approve_key = f"approve_{space[0]}_{i}"
                reject_key = f"reject_{space[0]}_{i}"
                view_key = f"view_{space[0]}_{i}"
                
                with st.expander(f"{space[1]} - Submitted by {space[3]} on {space[10]}", expanded=False):
                    col1, col2 = st.columns([1, 1])
                    with col1:
                        st.write(f"**Address:** {space[2]}")
                        st.write(f"**Total Spaces:** {space[4]}")
                        st.write(f"**Price per Hour:** ₹{space[5]}")
                        
                        # Parse features
                        try:
                            features = json.loads(space[6]) if isinstance(space[6], str) else space[6]
                            if features:
                                st.write("**Features:**")
                                for feature, available in features.items():
                                    if available:
                                        st.write(f"- {feature}")
                        except:
                            st.write("**Features:** Not specified")
                        
                        # Map with unique key
                        m = folium.Map(location=[space[8], space[9]], zoom_start=15)
                        folium.Marker([space[8], space[9]], popup=space[1]).add_to(m)
                        st_folium(m, width=400, height=300, key=map_key)
                    
                    with col2:
                        verification_notes = st.text_area(
                            "Verification Notes", 
                            key=notes_key,
                            placeholder="Enter approval notes or rejection reason..."
                        )
                        
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            if st.button("✅ Approve", key=approve_key):
                                try:
                                    c.execute('''UPDATE parking_spaces 
                                                SET is_verified=1, 
                                                    verification_admin_id=?,
                                                    verification_date=CURRENT_TIMESTAMP,
                                                    verification_notes=?
                                                WHERE id=?''',
                                             (st.session_state.user['id'], 
                                              verification_notes, 
                                              space[0]))
                                    
                                    # Notify owner
                                    c.execute('''INSERT INTO notifications
                                                (user_id, title, message, is_read)
                                                VALUES (?, ?, ?, 0)''',
                                             (space[7],  # owner_id
                                              "Parking Space Approved",
                                              f"Your parking space '{space[1]}' has been approved. {verification_notes}"))
                                    
                                    conn.commit()
                                    st.success(f"Approved: {space[1]}")
                                    time.sleep(1)
                                    st.rerun()
                                except Exception as e:
                                    conn.rollback()
                                    st.error(f"Approval failed: {str(e)}")
                        
                        with col2:
                            if st.button("❌ Reject", key=reject_key):
                                try:
                                    c.execute('''UPDATE parking_spaces 
                                                SET is_verified=0, 
                                                    verification_admin_id=?,
                                                    verification_date=CURRENT_TIMESTAMP,
                                                    verification_notes=?
                                                WHERE id=?''',
                                             (st.session_state.user['id'], 
                                              f"REJECTED: {verification_notes}", 
                                              space[0]))
                                    
                                    # Notify owner
                                    c.execute('''INSERT INTO notifications
                                                (user_id, title, message, is_read)
                                                VALUES (?, ?, ?, 0)''',
                                             (space[7],  # owner_id
                                              "Parking Space Rejected",
                                              f"Your parking space '{space[1]}' was rejected. Reason: {verification_notes}"))
                                    
                                    conn.commit()
                                    st.success(f"Rejected: {space[1]}")
                                    time.sleep(1)
                                    st.rerun()
                                except Exception as e:
                                    conn.rollback()
                                    st.error(f"Rejection failed: {str(e)}")
                        
                        with col3:
                            if st.button("🗂️ View Details", key=view_key):
                                st.session_state.view_space_id = space[0]
                                st.session_state.page = "view_parking_details"
                                st.rerun()
        
        # Show recently processed verifications
        st.subheader("Recently Processed")
        c.execute('''SELECT p.id, p.name, u.name as owner_name, 
                    p.is_verified, p.verification_notes, p.verification_date,
                    a.name as admin_name
                    FROM parking_spaces p
                    JOIN users u ON p.owner_id = u.id
                    JOIN users a ON p.verification_admin_id = a.id
                    WHERE p.verification_date IS NOT NULL
                    ORDER BY p.verification_date DESC LIMIT 5''')
        processed = c.fetchall()
        
        if processed:
            for i, item in enumerate(processed):
                status = "Approved" if item[3] else "Rejected"
                color = "green" if item[3] else "red"
                
                with st.container(border=True):
                    cols = st.columns([3, 1])
                    with cols[0]:
                        st.markdown(f"**{item[1]}** (Owner: {item[2]})")
                        st.markdown(f"**Status:** :{color}[{status}] by {item[6]} on {item[5]}")
                        if item[4]:
                            st.markdown(f"**Notes:** {item[4]}")
                    with cols[1]:
                        if st.button("View", key=f"view_processed_{item[0]}_{i}"):
                            st.session_state.view_space_id = item[0]
                            st.session_state.page = "view_parking_details"
                            st.rerun()
        conn.close()
    
    with tab2:
        st.subheader("System Statistics")
        conn = sqlite3.connect('smart_parking.db')
        c = conn.cursor()
        
        # User statistics
        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM users WHERE user_type='user'")
        regular_users = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM users WHERE user_type='owner'")
        owners = c.fetchone()[0]
        
        # Parking space statistics
        c.execute("SELECT COUNT(*) FROM parking_spaces")
        total_spaces = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM parking_spaces WHERE is_verified=1")
        verified_spaces = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM parking_spaces WHERE is_verified=0")
        pending_spaces = c.fetchone()[0]
        
        # Financial statistics
        c.execute("SELECT SUM(platform_earnings) FROM reservations WHERE payment_status='completed'")
        total_revenue = c.fetchone()[0] or 0
        
        c.execute("SELECT SUM(total_cost) FROM reservations WHERE payment_status='completed'")
        total_transactions = c.fetchone()[0] or 0
        
        conn.close()
        
        # Display metrics
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Users", total_users)
            st.metric("Regular Users", regular_users)
            st.metric("Owners", owners)
        
        with col2:
            st.metric("Total Parking Spaces", total_spaces)
            st.metric("Verified Spaces", verified_spaces)
            st.metric("Pending Verification", pending_spaces)
        
        with col3:
            st.metric("Platform Revenue", f"₹{total_revenue:,.2f}")
            st.metric("Total Transactions", f"₹{total_transactions:,.2f}")
    
    with tab3:
        st.subheader("Database Tools")
        
        if st.button("Backup Database", key="backup_db"):
            with open('smart_parking.db', 'rb') as f:
                st.download_button(
                    label="Download Backup",
                    data=f,
                    file_name=f"smart_parking_backup_{datetime.date.today()}.db",
                    mime='application/octet-stream',
                    key="download_backup"
                )
        
        if st.button("Update Database Schema", key="update_schema"):
            update_database_schema()
            st.success("Database schema updated successfully!")
            time.sleep(1)
            st.rerun()
        
        if st.button("Reset Database", key="reset_db", type="secondary"):
            if st.checkbox("I understand this will delete ALL data", key="reset_confirm"):
                reset_database()
                st.success("Database reset complete!")
                time.sleep(1)
                st.rerun()
    
    with tab4:
        st.subheader("Loyalty Program Management")
        conn = sqlite3.connect('smart_parking.db')
        c = conn.cursor()
        
        c.execute("SELECT * FROM loyalty_programs WHERE is_active=1 LIMIT 1")
        program = c.fetchone()
        
        if program:
            with st.form("update_loyalty_program"):
                st.write("Current Loyalty Program Settings")
                
                name = st.text_input("Program Name", value=program[1], key="loyalty_name")
                description = st.text_area("Description", value=program[2], key="loyalty_desc")
                
                col1, col2 = st.columns(2)
                with col1:
                    points_per_rupee = st.number_input(
                        "Points per ₹1 spent", 
                        min_value=0.01, 
                        max_value=1.0, 
                        value=float(program[3]),
                        step=0.01,
                        format="%.2f",
                        key="points_per_rupee"
                    )
                with col2:
                    min_redeem_points = st.number_input(
                        "Minimum points to redeem", 
                        min_value=10, 
                        value=int(program[4]),
                        step=10,
                        key="min_redeem_points"
                    )
                
                redeem_value = st.number_input(
                    "Redeem value (₹)", 
                    min_value=1.0, 
                    value=float(program[5]),
                    step=1.0,
                    key="redeem_value"
                )
                
                is_active = st.checkbox("Program Active", value=bool(program[6]), key="is_active")
                
                if st.form_submit_button("Update Program"):
                    try:
                        c.execute('''UPDATE loyalty_programs 
                                    SET name=?, description=?, points_per_rupee=?,
                                        min_redeem_points=?, redeem_value=?, is_active=?
                                    WHERE id=?''',
                                 (name, description, points_per_rupee,
                                  min_redeem_points, redeem_value, int(is_active),
                                  program[0]))
                        conn.commit()
                        st.success("Loyalty program updated!")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        conn.rollback()
                        st.error(f"Error updating program: {str(e)}")
        else:
            with st.form("create_loyalty_program"):
                st.write("Create New Loyalty Program")
                
                name = st.text_input("Program Name", value="EasyDock Rewards", key="new_loyalty_name")
                description = st.text_area("Description", value="Earn points for parking with us!", key="new_loyalty_desc")
                
                col1, col2 = st.columns(2)
                with col1:
                    points_per_rupee = st.number_input(
                        "Points per ₹1 spent", 
                        min_value=0.01, 
                        max_value=1.0, 
                        value=0.1,
                        step=0.01,
                        format="%.2f",
                        key="new_points_per_rupee"
                    )
                with col2:
                    min_redeem_points = st.number_input(
                        "Minimum points to redeem", 
                        min_value=10, 
                        value=100,
                        step=10,
                        key="new_min_redeem_points"
                    )
                
                redeem_value = st.number_input(
                    "Redeem value (₹)", 
                    min_value=1.0, 
                    value=10.0,
                    step=1.0,
                    key="new_redeem_value"
                )
                
                if st.form_submit_button("Create Program"):
                    try:
                        c.execute('''INSERT INTO loyalty_programs 
                                    (name, description, points_per_rupee, 
                                     min_redeem_points, redeem_value, is_active)
                                    VALUES (?, ?, ?, ?, ?, 1)''',
                                 (name, description, points_per_rupee,
                                  min_redeem_points, redeem_value))
                        conn.commit()
                        st.success("Loyalty program created!")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        conn.rollback()
                        st.error(f"Error creating program: {str(e)}")
        
        conn.close()
def owner_page():
    if 'user' not in st.session_state or st.session_state.user['user_type'] not in ['owner', 'admin']:
        st.warning("Unauthorized access")
        st.session_state.page = "home"
        st.rerun()

    st.title("Owner Dashboard")
    
    # Display verification notes if any
    conn = sqlite3.connect('smart_parking.db')
    c = conn.cursor()
    c.execute('''SELECT verification_notes FROM parking_spaces 
                 WHERE owner_id=? AND verification_notes IS NOT NULL
                 ORDER BY verification_date DESC LIMIT 1''', 
              (st.session_state.user['id'],))
    last_note = c.fetchone()
    
    if last_note and last_note[0]:
        with st.expander("Latest Verification Note", expanded=True):
            st.info(last_note[0])
    
    conn.close()
    
    tab1, tab2, tab3 = st.tabs(["My Listings", "Add New Space", "Performance"])
    
    with tab1:
        st.subheader("My Parking Spaces")
        conn = sqlite3.connect('smart_parking.db')
        c = conn.cursor()
        c.execute('''SELECT id, owner_id, name, address, latitude, longitude,
                    total_spaces, available_spaces, price_per_hour, is_public,
                    has_ev_charging, ev_charging_price, is_verified,
                    verification_admin_id, verification_date, verification_notes,
                    features, revenue_share, total_earnings,
                    CASE 
                        WHEN is_verified = 1 THEN 'Approved'
                        WHEN verification_notes LIKE 'REJECTED:%' THEN 'Rejected'
                        ELSE 'Pending Review' 
                    END as status
                    FROM parking_spaces 
                    WHERE owner_id=?''', (st.session_state.user['id'],))
        spaces = c.fetchall()
        conn.close()
        
        if not spaces:
            st.info("You haven't listed any parking spaces yet.")
        else:
            for i, space in enumerate(spaces):
                try:
                    # Safely parse features JSON
                    features = {}
                    if space[16]:  # features column
                        try:
                            features = json.loads(space[16]) if isinstance(space[16], str) else space[16]
                        except:
                            features = {}
                    
                    # Safely get revenue_share with default value
                    revenue_share = float(space[17]) if space[17] is not None else 0.15
                    total_earnings = float(space[18]) if space[18] is not None else 0.0
                    
                    with st.expander(f"{space[2]} ({space[19]})", expanded=True):
                        col1, col2 = st.columns([1, 2])
                        with col1:
                            m = folium.Map(location=[space[4], space[5]], zoom_start=15)
                            folium.Marker([space[4], space[5]], popup=space[2]).add_to(m)
                            st_folium(m, width=300, height=200, key=f"map_{space[0]}_{i}")
                        
                        with col2:
                            st.write(f"**Address:** {space[3]}")
                            st.write(f"**Spaces:** {space[7]}/{space[6]} available")
                            st.write(f"**Price:** ₹{space[8]}/hour")
                            st.write(f"**EV Charging:** {'Yes' if space[10] else 'No'}")
                            if space[10]:
                                st.write(f"**EV Charging Price:** ₹{space[11]}/hour")
                            st.write(f"**Public:** {'Yes' if space[9] else 'No'}")
                            st.write(f"**Revenue Share:** {revenue_share*100:.1f}%")
                            st.write(f"**Total Earnings:** ₹{total_earnings:,.2f}")
                            st.write(f"**Status:** {space[19]}")
                            
                            if space[15]:
                                st.write(f"**Verification Notes:** {space[15]}")
                            
                            if features:
                                st.write("**Features:**")
                                cols = st.columns(3)
                                features_list = [f for f, v in features.items() if v]
                                for j, feature in enumerate(features_list):
                                    cols[j%3].write(f"✓ {feature}")
                            
                            # Only show sensor management if space is approved
                            if space[12]:  # is_verified = 1
                                st.subheader("Sensor Management")
                                space_number = st.number_input(
                                    "Space Number", 
                                    1, space[6], 1, 
                                    key=f"sensor_num_{space[0]}_{i}"
                                )
                                
                                col1, col2 = st.columns(2)
                                with col1:
                                    if st.button(
                                        "Mark as Occupied", 
                                        key=f"occupy_{space[0]}_{i}_{space_number}"
                                    ):
                                        update_sensor_status(space[0], space_number, True)
                                        st.success("Status updated!")
                                        time.sleep(1)
                                        st.rerun()
                                with col2:
                                    if st.button(
                                        "Mark as Available", 
                                        key=f"free_{space[0]}_{i}_{space_number}"
                                    ):
                                        update_sensor_status(space[0], space_number, False)
                                        st.success("Status updated!")
                                        time.sleep(1)
                                        st.rerun()
                            else:
                                st.warning("Sensor management available after approval")
                except Exception as e:
                    st.error(f"Error displaying parking space: {str(e)}")
                    continue
    
    with tab2:
        st.subheader("Add New Parking Space")
        with st.form("add_parking_form"):
            name = st.text_input("Parking Name", max_chars=100, key="parking_name")
            address = st.text_area("Full Address", key="parking_address")
            
            col1, col2 = st.columns(2)
            with col1:
                latitude = st.number_input(
                    "Latitude", 
                    min_value=-90.0, 
                    max_value=90.0, 
                    value=8.7642,
                    format="%.6f",
                    key="parking_lat"
                )
            with col2:
                longitude = st.number_input(
                    "Longitude", 
                    min_value=-180.0, 
                    max_value=180.0, 
                    value=78.1348,
                    format="%.6f",
                    key="parking_lon"
                )
            
            total_spaces = st.number_input(
                "Total Parking Spaces", 
                min_value=1, 
                max_value=1000, 
                value=10,
                key="total_spaces"
            )
            
            price_per_hour = st.number_input(
                "Price per Hour (₹)", 
                min_value=10, 
                max_value=1000, 
                value=50,
                key="price_per_hour"
            )
            
            col1, col2 = st.columns(2)
            with col1:
                is_public = st.checkbox("Public Parking", value=True, key="is_public")
            with col2:
                has_ev_charging = st.checkbox(
                    "Has EV Charging Stations", 
                    key="has_ev_charging"
                )
            
            ev_charging_price = 0
            if has_ev_charging:
                ev_charging_price = st.number_input(
                    "EV Charging Price per Hour (₹)", 
                    min_value=0, 
                    max_value=500, 
                    value=25,
                    key="ev_charging_price"
                )
            
            features = st.multiselect(
                "Available Features", 
                [
                    "24/7 Security", 
                    "Covered Parking", 
                    "Valet Service", 
                    "Disabled Access", 
                    "Car Wash", 
                    "CCTV Surveillance",
                    "Lighting",
                    "Restrooms"
                ],
                key="parking_features"
            )
            
            revenue_share = st.slider(
                "Platform Revenue Share (%)", 
                min_value=5, 
                max_value=30, 
                value=15,
                help="Percentage of earnings that goes to the platform",
                key="revenue_share"
            )
            
            if st.form_submit_button("Submit Parking Space"):
                if not name or not address:
                    st.error("Name and address are required")
                    st.stop()
                
                features_dict = {feature: True for feature in features}
                
                conn = sqlite3.connect('smart_parking.db')
                c = conn.cursor()
                try:
                    c.execute('''INSERT INTO parking_spaces 
                                (owner_id, name, address, latitude, longitude,
                                 total_spaces, available_spaces, price_per_hour,
                                 is_public, has_ev_charging, ev_charging_price,
                                 features, revenue_share, total_earnings,
                                 is_verified)  
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)''',
                             (st.session_state.user['id'], 
                              name.strip(), 
                              address.strip(),
                              latitude,
                              longitude,
                              total_spaces,
                              total_spaces,
                              price_per_hour,
                              int(is_public),
                              int(has_ev_charging),
                              ev_charging_price,
                              json.dumps(features_dict),
                              revenue_share/100,
                              0.0))
                    
                    conn.commit()
                    st.success("Parking space submitted for admin approval!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    conn.rollback()
                    st.error(f"Failed to add parking space: {str(e)}")
                finally:
                    conn.close()
    
    with tab3:
        st.subheader("Performance Metrics")
        conn = sqlite3.connect('smart_parking.db')
        c = conn.cursor()
        
        # Only show metrics for verified spaces
        c.execute('''SELECT COALESCE(SUM(total_earnings), 0) 
                     FROM parking_spaces 
                     WHERE owner_id=? AND is_verified=1''', 
                 (st.session_state.user['id'],))
        total_earnings = float(c.fetchone()[0])
        
        # Get recent reservations only for verified spaces
        c.execute('''SELECT r.id, p.name, r.start_time, r.end_time, r.total_cost,
                     r.owner_earnings, r.platform_earnings
                     FROM reservations r
                     JOIN parking_spaces p ON r.parking_id = p.id
                     WHERE p.owner_id=? AND r.payment_status='completed' AND p.is_verified=1
                     ORDER BY r.end_time DESC LIMIT 5''',
                 (st.session_state.user['id'],))
        recent_reservations = c.fetchall()
        
        # Get occupancy rates only for verified spaces
        c.execute('''SELECT name, 
                     (total_spaces - available_spaces) * 100.0 / total_spaces as occupancy_rate
                     FROM parking_spaces
                     WHERE owner_id=? AND total_spaces > 0 AND is_verified=1''', 
                 (st.session_state.user['id'],))
        occupancy_rates = c.fetchall()
        
        conn.close()
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Earnings", f"₹{total_earnings:,.2f}")
        with col2:
            st.metric("Verified Listings", len([s for s in spaces if s[12]]))
        
        st.subheader("Recent Reservations")
        if not recent_reservations:
            st.info("No completed reservations yet")
        else:
            for i, res in enumerate(recent_reservations):
                with st.container(border=True, key=f"reservation_{res[0]}_{i}"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Parking:** {res[1]}")
                        st.write(f"**Time:** {res[2]} to {res[3]}")
                    with col2:
                        st.write(f"**Total:** ₹{res[4]:,.2f}")
                        st.write(f"**Your Earnings:** ₹{res[5]:,.2f}")
                        st.write(f"**Platform Fee:** ₹{res[6]:,.2f}")
        
        st.subheader("Occupancy Rates")
        if not occupancy_rates:
            st.info("No occupancy data available")
        else:
            for i, space in enumerate(occupancy_rates):
                st.progress(min(int(space[1]), 100))
                st.write(f"{space[0]}: {space[1]:.1f}% occupancy")
# ======================
# HELPER FUNCTIONS
# ======================
def update_sensor_status(parking_id, space_number, is_occupied):
    conn = sqlite3.connect('smart_parking.db')
    c = conn.cursor()
    
    try:
        # Update or create sensor record
        c.execute('''INSERT OR REPLACE INTO sensors 
                     (parking_id, space_number, is_occupied)
                     VALUES (?, ?, ?)''', 
                 (parking_id, space_number, is_occupied))
        
        # Update available spaces count
        c.execute('''UPDATE parking_spaces 
                     SET available_spaces = (
                         SELECT COUNT(*) FROM sensors 
                         WHERE parking_id=? AND is_occupied=0
                     )
                     WHERE id=?''', 
                 (parking_id, parking_id))
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        st.error(f"Error updating sensor: {str(e)}")
        return False
    finally:
        conn.close()

def update_database_schema():
    conn = sqlite3.connect('smart_parking.db')
    c = conn.cursor()
    
    try:
        # Check and update parking_spaces table
        c.execute("PRAGMA table_info(parking_spaces)")
        parking_columns = [column[1] for column in c.fetchall()]
        
        # List of columns that should exist in parking_spaces
        parking_required_columns = {
            'verification_notes': 'TEXT',
            'owner_earnings': 'REAL DEFAULT 0.0',
            'platform_earnings': 'REAL DEFAULT 0.0',
            'ev_charging_price': 'REAL DEFAULT 0.0',
            'revenue_share': 'REAL DEFAULT 0.15',
            'total_earnings': 'REAL DEFAULT 0.0'
        }
        
        for col_name, col_type in parking_required_columns.items():
            if col_name not in parking_columns:
                c.execute(f"ALTER TABLE parking_spaces ADD COLUMN {col_name} {col_type}")
                st.write(f"Added {col_name} column to parking_spaces table")
        
        # Check and update reservations table
        c.execute("PRAGMA table_info(reservations)")
        res_columns = [column[1] for column in c.fetchall()]
        
        # List of columns that should exist in reservations
        res_required_columns = {
            'ev_charging_cost': 'REAL DEFAULT 0.0',
            'owner_earnings': 'REAL DEFAULT 0.0',
            'platform_earnings': 'REAL DEFAULT 0.0',
            'actual_end_time': 'TEXT',
            'payment_method': 'TEXT CHECK(payment_method IN ("wallet", "fastag", "nfc", "credit_card", "debit_card"))'
        }
        
        for col_name, col_type in res_required_columns.items():
            if col_name not in res_columns:
                c.execute(f"ALTER TABLE reservations ADD COLUMN {col_name} {col_type}")
                st.write(f"Added {col_name} column to reservations table")
        
        # Check and update users table
        c.execute("PRAGMA table_info(users)")
        user_columns = [column[1] for column in c.fetchall()]
        
        # List of columns that should exist in users
        user_required_columns = {
            'wallet_balance': 'REAL DEFAULT 0.0',
            'reward_points': 'INTEGER DEFAULT 0',
            'nfc_card_id': 'TEXT UNIQUE',
            'fastag_id': 'TEXT UNIQUE',
            'last_login': 'TIMESTAMP'
        }
        
        for col_name, col_type in user_required_columns.items():
            if col_name not in user_columns:
                c.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
                st.write(f"Added {col_name} column to users table")
        
        # Check if loyalty_programs table exists (added in newer versions)
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='loyalty_programs'")
        if not c.fetchone():
            c.execute('''CREATE TABLE loyalty_programs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        description TEXT,
                        points_per_rupee REAL DEFAULT 0.1,
                        min_redeem_points INTEGER DEFAULT 100,
                        redeem_value REAL DEFAULT 10.0,
                        is_active BOOLEAN DEFAULT 1)''')
            st.write("Created loyalty_programs table")
        
        conn.commit()
        st.success("Database schema updated successfully!")
    except Exception as e:
        conn.rollback()
        st.error(f"Error updating database schema: {str(e)}")
    finally:
        conn.close()

def notifications_page():
    if 'user' not in st.session_state:
        st.warning("Please login to view notifications")
        st.session_state.page = "login"
        st.rerun()
    
    st.title("Notifications")
    
    conn = sqlite3.connect('smart_parking.db')
    c = conn.cursor()
    
    # Mark all as read when page loads
    c.execute('''UPDATE notifications 
                SET is_read=1 
                WHERE user_id=?''',
             (st.session_state.user['id'],))
    conn.commit()
    
    # Get notifications
    c.execute('''SELECT id, title, message, created_at 
                FROM notifications 
                WHERE user_id=?
                ORDER BY created_at DESC''',
             (st.session_state.user['id'],))
    notifications = c.fetchall()
    conn.close()
    
    if not notifications:
        st.info("No notifications yet")
    else:
        for note in notifications:
            with st.container(border=True):
                st.subheader(note[1])
                st.write(note[2])
                st.caption(f"Received on {note[3]}")
    
    if st.button("Clear All Notifications"):
        conn = sqlite3.connect('smart_parking.db')
        c = conn.cursor()
        c.execute('''DELETE FROM notifications 
                    WHERE user_id=?''',
                 (st.session_state.user['id'],))
        conn.commit()
        conn.close()
        st.success("Notifications cleared!")
        time.sleep(1)
        st.rerun()
        
def reset_database():
    if os.path.exists('smart_parking.db'):
        os.remove('smart_parking.db')
    init_db()
    st.success("Database reset complete!")
    
# ======================
# MAIN APPLICATION
# ======================
def main():
    # Configure page
    st.set_page_config(
        page_title="Easy Dock",
        page_icon=":car:",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Custom CSS styling
    st.markdown("""
    <style>
        div.stButton > button {
            width: 100%;
        }
        .notification-badge {
            background-color: #ff4b4b;
            color: white;
            border-radius: 50%;
            padding: 0.2em 0.5em;
            font-size: 0.8em;
            margin-left: 0.5em;
        }
        .sidebar .sidebar-content {
            background-color: #f0f2f6;
        }
    </style>
    """, unsafe_allow_html=True)

    # Initialize database
    init_db()
    update_database_schema()

    # Initialize session state
    if 'user' not in st.session_state:
        st.session_state.user = None
    if 'page' not in st.session_state:
        st.session_state.page = "home"
    if 'show_confirmation' not in st.session_state:
        st.session_state.show_confirmation = False
    if 'confirm_space' not in st.session_state:
        st.session_state.confirm_space = None
    if 'filters' not in st.session_state:
        st.session_state.filters = {
            'verified_only': True,
            'ev_charging': False,
            'max_price': 100,
            'min_spaces': 0,
            'parking_type': "All",
            'use_location': False
        }
    if 'view_space_id' not in st.session_state:
        st.session_state.view_space_id = None
    if 'owner_tab' not in st.session_state:
        st.session_state.owner_tab = None
    if 'admin_tab' not in st.session_state:
        st.session_state.admin_tab = None

    # Sidebar navigation
    with st.sidebar:
        st.title("Easy Dock")
        st.markdown("---")
        
        if st.session_state.user:
            # Check for unread notifications
            try:
                conn = sqlite3.connect('smart_parking.db')
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", 
                         (st.session_state.user['id'],))
                unread_count = c.fetchone()[0]
            except Exception as e:
                st.error(f"Error checking notifications: {str(e)}")
                unread_count = 0
            finally:
                conn.close()
            
            # Display user info
            notification_badge = f"<span class='notification-badge'>{unread_count}</span>" if unread_count > 0 else ""
            st.markdown(f"<div style='display: flex; align-items: center;'>"
                        f"<span style='font-weight: bold; color: green;'>Welcome, {st.session_state.user['name']}!</span>"
                        f"{notification_badge}"
                        f"</div>", 
                        unsafe_allow_html=True)
            
            st.markdown(f"**Account Type:** {st.session_state.user['user_type'].capitalize()}")
            
            if st.button("Logout"):
                st.session_state.user = None
                st.session_state.page = "home"
                st.rerun()
            
            st.markdown("---")
            
            # Role-based navigation
            nav_options = ["Home", "Find Parking", "My Reservations", "Rewards", "Notifications"]
            
            if st.session_state.user['user_type'] == 'admin':
                nav_options.append("Admin Dashboard")
            if st.session_state.user['user_type'] in ['owner', 'admin']:
                nav_options.insert(3, "Owner Dashboard")
            
            selected = st.selectbox("Navigation", nav_options)
            
            # Page routing
            if selected == "Home":
                st.session_state.page = "home"
            elif selected == "Find Parking":
                st.session_state.page = "find_parking"
            elif selected == "My Reservations":
                st.session_state.page = "reservations"
            elif selected == "Owner Dashboard":
                st.session_state.page = "owner"
                st.session_state.owner_tab = "My Listings"
            elif selected == "Rewards":
                st.session_state.page = "rewards"
            elif selected == "Notifications":
                st.session_state.page = "notifications"
            elif selected == "Admin Dashboard":
                st.session_state.page = "admin"
                st.session_state.admin_tab = "Verify Listings"
            
            st.markdown("---")
            
            # Quick actions
            if st.session_state.user['user_type'] == 'owner':
                if st.button("Add New Parking Space"):
                    st.session_state.page = "owner"
                    st.session_state.owner_tab = "Add New Space"
                    st.rerun()
            
            if st.session_state.user['user_type'] == 'admin':
                try:
                    conn = sqlite3.connect('smart_parking.db')
                    c = conn.cursor()
                    c.execute("SELECT COUNT(*) FROM parking_spaces WHERE is_verified=0 AND (verification_notes IS NULL OR verification_notes NOT LIKE 'REJECTED:%')")
                    pending_count = c.fetchone()[0]
                    
                    if pending_count > 0:
                        st.warning(f"⚠️ {pending_count} spaces pending verification")
                        if st.button(f"Review {pending_count} Pending →", 
                                   key="unique_review_button"):  # Added unique key
                            st.session_state.page = "admin"
                            st.session_state.admin_tab = "Verify Listings"
                            st.rerun()
                except Exception as e:
                    st.error(f"Error checking pending verifications: {str(e)}")
                finally:
                    conn.close()
        else:
            # Guest navigation
            if st.button("Login"):
                st.session_state.page = "login"
            if st.button("Register"):
                st.session_state.page = "register"
            if st.button("Find Parking"):
                st.session_state.page = "find_parking"
            
            st.markdown("---")
            st.info("Admin Test Credentials:")
            st.code("Email: aakashbala06@gmail.com\nPassword: admin123")
    
    # Page routing
    if st.session_state.page == "home":
        home_page()
    elif st.session_state.page == "login":
        login_page()
    elif st.session_state.page == "register":
        register_page()
    elif st.session_state.page == "find_parking":
        find_parking_page()
    elif st.session_state.page == "booking":
        booking_page()
    elif st.session_state.page == "payment":
        if 'reservation_id' in st.session_state and 'payment_amount' in st.session_state:
            payment_page()
        else:
            st.error("Invalid payment request - missing reservation details")
            st.session_state.page = "reservations"
            st.rerun()
    elif st.session_state.page == "reservations":
        reservations_page()
    elif st.session_state.page == "rewards":
        rewards_page()
    elif st.session_state.page == "admin":
        admin_page()
    elif st.session_state.page == "owner":
        owner_page()
    elif st.session_state.page == "extend_booking":
        extend_booking_page()
    elif st.session_state.page == "notifications":
        notifications_page()
    elif st.session_state.page == "view_parking_details":
        view_parking_details_page()
    else:
        st.error("Invalid page state")
        st.session_state.page = "home"
        st.rerun()

if __name__ == "__main__":
    main() 