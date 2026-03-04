import streamlit as st
import requests
import sqlite3
import pandas as pd
from datetime import date
from dateutil import parser

# ---------------- DB Setup ----------------
conn = sqlite3.connect('skystake.db', check_same_thread=False)
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS users 
             (username TEXT PRIMARY KEY, password TEXT, skycoins INTEGER DEFAULT 500)''')
c.execute('''CREATE TABLE IF NOT EXISTS bets 
             (username TEXT, flight_id TEXT, bet_type TEXT, delay_range TEXT, bet_date TEXT, 
              outcome TEXT DEFAULT 'pending', PRIMARY KEY(username, flight_id))''')
conn.commit()

# ---------------- Route Ratings ----------------
ROUTE_RATINGS = {
    'AMS': {'otp': 82, 'avg_delay_min': 14, 'risk': 'Low'},
    'DUB': {'otp': 84, 'avg_delay_min': 12, 'risk': 'Low'},
    'LHR': {'otp': 72, 'avg_delay_min': 22, 'risk': 'Medium'},
    'CDG': {'otp': 75, 'avg_delay_min': 18, 'risk': 'Medium'},
    'DEFAULT': {'otp': 74, 'avg_delay_min': 20, 'risk': 'Medium'}
}

# ---------------- Fetch Departures (free tier real-time mode) ----------------
@st.cache_data(ttl=1800, show_spinner="Fetching current Manchester departures...")
def fetch_departures(api_key):
    url = "https://api.aviationstack.com/v1/flights"
    # If you get https_access_restricted again → change to: "http://api.aviationstack.com/v1/flights"

    params = {
        'access_key': api_key,
        'dep_iata': 'MAN',
        'limit': 50
        # IMPORTANT: flight_date is OMITTED → keeps us in real-time mode (free tier allowed)
    }
    
    try:
        r = requests.get(url, params=params, timeout=10)
        
        # Debug output
        st.write("**API Debug Info**")
        st.write("API Status Code:", r.status_code)
        
        if r.status_code != 200:
            error_text = r.text[:500] + "..." if len(r.text) > 500 else r.text
            st.error(f"API Error {r.status_code}: {error_text}")
            return pd.DataFrame()
        
        data = r.json()
        st.write("API Response Keys:", list(data.keys()))
        
        if 'data' in data:
            flight_count = len(data['data'])
            st.write("Number of flights returned:", flight_count)
            if flight_count == 0:
                st.info("API success (200) but zero current flights from MAN right now.")
        else:
            st.warning("No 'data' key in response. Full response preview:")
            st.json(data)
        
        # Parse flights
        flights = []
        for f in data.get('data', []):
            dep = f.get('departure', {})
            status = f.get('flight_status', 'unknown').capitalize()
            dest_iata = f['arrival'].get('iata', 'UNK')
            rating = ROUTE_RATINGS.get(dest_iata, ROUTE_RATINGS['DEFAULT'])
            
            flights.append({
                'flight_id': f['flight'].get('iata', 'N/A'),
                'airline': f['airline'].get('name', 'N/A'),
                'destination': f['arrival'].get('airport', 'Unknown'),
                'dest_iata': dest_iata,
                'scheduled': dep.get('scheduled'),
                'estimated': dep.get('estimated'),
                'actual': dep.get('actual'),
                'delay_min': dep.get('delay'),
                'status': status,
                'status_emoji': {'Scheduled': '🛫', 'Active': '✈️', 'Landed': '🛬', 'Cancelled': '❌'}.get(status, '❓'),
                'otp_rating': f"{rating['otp']}% • Avg {rating['avg_delay_min']} min • {rating['risk']}"
            })
        
        df = pd.DataFrame(flights)
        if not df.empty:
            st.success(f"Successfully loaded {len(df)} current flights!")
        return df
    
    except Exception as e:
        st.error(f"Request failed: {str(e)}")
        return pd.DataFrame([])

# ---------------- Resolve Bets ----------------
def resolve_bets(api_key, target_date):
    flights_df = fetch_departures(api_key)  # Using real-time fetch
    if flights_df.empty:
        return 0
    
    flight_map = {row['flight_id']: row for _, row in flights_df.iterrows()}
    updated = 0
    
    c.execute("SELECT username, flight_id, bet_type, delay_range FROM bets WHERE bet_date = ? AND outcome = 'pending'", (target_date,))
    for user, flight_id, bet_type, delay_range in c.fetchall():
        if flight_id not in flight_map:
            continue
        f = flight_map[flight_id]
        status = f['status']
        delay_min = f['delay_min'] if f['delay_min'] is not None else 0
        
        if delay_min == 0 and f['actual'] and f['scheduled']:
            try:
                sched = parser.parse(f['scheduled'])
                act = parser.parse(f['actual'])
                delay_min = max(0, (act - sched).total_seconds() / 60)
            except:
                pass
        
        is_cancelled = status == 'Cancelled'
        is_on_time = not is_cancelled and delay_min <= 15
        is_delayed = not is_cancelled and delay_min > 15
        
        correct = False
        coins = 0
        
        if bet_type == "On Time" and is_on_time:
            correct = True
            coins = 20
        elif bet_type == "Delayed" and is_delayed:
            correct = True
            coins = 30
            if delay_range:
                if "Under 20" in delay_range and 15 < delay_min <= 20: coins += 10
                elif "20–60" in delay_range and 20 < delay_min <= 60: coins += 10
                elif ">60" in delay_range and delay_min > 60: coins += 10
        elif bet_type == "Cancelled" and is_cancelled:
            correct = True
            coins = 60
        
        if not correct:
            coins = -10
        
        c.execute("UPDATE users SET skycoins = skycoins + ? WHERE username = ?", (coins, user))
        c.execute("UPDATE bets SET outcome = ? WHERE username = ? AND flight_id = ?",
                  ('correct' if correct else 'wrong', user, flight_id))
        updated += 1
    
    conn.commit()
    return updated

# ---------------- Level Calculation ----------------
def get_user_level(username):
    c.execute("SELECT COUNT(*) FROM bets WHERE username = ? AND outcome != 'pending'", (username,))
    total = c.fetchone()[0]
    if total == 0:
        return "Cloud Hopper", 0.0
    
    c.execute("SELECT COUNT(*) FROM bets WHERE username = ? AND outcome = 'correct'", (username,))
    correct = c.fetchone()[0]
    success_rate = (correct / total) * 100
    
    if success_rate >= 85:
        level = "AVGeek"
    elif success_rate >= 70:
        level = "Senior Captain"
    elif success_rate >= 50:
        level = "First Officer"
    elif success_rate >= 30:
        level = "Wing Cadet"
    else:
        level = "Cloud Hopper"
    
    return level, success_rate

# ---------------- UI ----------------
st.set_page_config(page_title="SkyStake", layout="wide")

st.markdown("""
    <style>
    .stApp { background: linear-gradient(135deg, #0a001f, #1e0038, #2a004f); color: #e8e8ff; }
    .card { background: rgba(40,40,80,0.85); border-radius: 16px; padding: 20px; margin: 16px 0; border: 1px solid #6666cc; box-shadow: 0 8px 20px rgba(0,0,0,0.6); }
    h1, h2 { color: #00ffff; text-shadow: 0 2px 8px #000; }
    .stButton>button { background: #00d4ff; color: #000; font-weight: bold; border: none; border-radius: 12px; padding: 12px 24px; }
    .badge { font-size: 1.1em; font-weight: bold; color: #ffd700; }
    </style>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
""", unsafe_allow_html=True)

st.title("✈️ SkyStake – Stake SkyCoins on Real Flights ✈️")

# API key status
try:
    api_key = st.secrets["AVIATIONSTACK_API_KEY"]
    st.sidebar.success(f"API key loaded from secrets (length: {len(api_key)})")
except Exception as e:
    st.sidebar.error(f"Secrets error: {str(e)}")
    api_key = None

if 'user' not in st.session_state:
    st.session_state.user = None

with st.sidebar:
    st.header("Pilot Profile")
    username = st.text_input("Callsign")
    password = st.text_input("Password", type="password")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Login"):
            c.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password))
            if c.fetchone():
                st.session_state.user = username
                st.success("Welcome back!")
            else:
                st.error("Invalid.")
    with col2:
        if st.button("Register"):
            try:
                c.execute("INSERT INTO users (username, password, skycoins) VALUES (?, ?, 500)", (username, password))
                conn.commit()
                st.session_state.user = username
                st.success("New pilot registered!")
            except:
                st.error("Callsign taken.")

if st.session_state.user:
    user = st.session_state.user
    today_str = date.today().isoformat()

    c.execute("SELECT skycoins FROM users WHERE username=?", (user,))
    skycoins = c.fetchone()[0] or 500

    level, success_pct = get_user_level(user)

    st.sidebar.markdown(f"**Callsign:** {user}")
    st.sidebar.markdown(f"**SkyCoins:** **{skycoins}**")
    st.sidebar.markdown(f"**Level:** <span class='badge'>{level}</span> ({success_pct:.1f}% success)", unsafe_allow_html=True)
    if st.sidebar.button("Logout"):
        st.session_state.user = None
        st.rerun()

    st.subheader(f"Current Manchester Departures – {today_str}")

    if st.button("🔄 Refresh Live Flights"):
        if api_key:
            st.session_state.flights = fetch_departures(api_key)
        else:
            st.error("No API key available.")

    flights_df = st.session_state.get('flights')

    if flights_df is not None:
        if flights_df.empty:
            st.info("No current flights loaded (check debug messages above).")
        else:
            for _, row in flights_df.iterrows():
                st.markdown(f"""
                <div class="card">
                    <h3><i class="fa fa-plane-departure"></i> {row['flight_id']} – {row['airline']}</h3>
                    <p><strong>Destination:</strong> {row['destination']} ({row['dest_iata']})</p>
                    <p><strong>Scheduled:</strong> {row.get('scheduled', 'N/A')[-14:-6] or 'N/A'}</p>
                    <p><strong>Status:</strong> {row['status_emoji']} {row['status']}</p>
                    <p><strong>Route Insight:</strong> {row['otp_rating']}</p>
                </div>
                """, unsafe_allow_html=True)

    # Resolution (using real-time data – note: may not have final results for past flights)
    st.subheader("Resolve Today's Bets")
    if st.button("Run Daily Resolution"):
        if api_key:
            count = resolve_bets(api_key, today_str)
            st.success(f"Resolved {count} bets • SkyCoins updated!")
        else:
            st.error("No API key")

st.caption("SkyStake • Real-time mode (free tier) • AviationStack • March 2026")
