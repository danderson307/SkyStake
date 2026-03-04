import streamlit as st
import requests
import sqlite3
import pandas as pd
from datetime import date
from dateutil import parser as date_parser

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

# ---------------- Fetch Current Real-Time Departures ----------------
@st.cache_data(ttl=1800, show_spinner="Fetching current Manchester departures...")
def fetch_departures(api_key):
    url = "https://api.aviationstack.com/v1/flights"  # HTTPS preferred; fallback http if restricted

    params = {
        'access_key': api_key,
        'dep_iata': 'MAN',
        'limit': 50
    }
    
    try:
        r = requests.get(url, params=params, timeout=10)
        
        st.write("**API Debug (remove later)**")
        st.write("Status Code:", r.status_code)
        if r.status_code != 200:
            st.error(f"API Error {r.status_code}: {r.text[:400]}...")
            return pd.DataFrame()
        
        data = r.json()
        if 'data' not in data:
            st.warning("No 'data' in response.")
            return pd.DataFrame()
        
        flights = []
        for f in data['data']:
            # Skip codeshares (keep only primary/operating flights)
            if f.get('flight', {}).get('codeshared') is not None:
                continue  # Exclude if it's a codeshare record
            
            dep = f.get('departure', {})
            status = f.get('flight_status', 'unknown').capitalize()
            dest_iata = f['arrival'].get('iata', 'UNK')
            rating = ROUTE_RATINGS.get(dest_iata, ROUTE_RATINGS['DEFAULT'])
            
            scheduled_str = dep.get('scheduled')
            scheduled_time = date_parser.parse(scheduled_str) if scheduled_str else None
            
            flights.append({
                'flight_id': f['flight'].get('iata', 'N/A'),
                'airline': f['airline'].get('name', 'N/A'),
                'destination': f['arrival'].get('airport', 'Unknown'),
                'dest_iata': dest_iata,
                'scheduled': scheduled_str,
                'scheduled_dt': scheduled_time,  # For sorting
                'estimated': dep.get('estimated'),
                'actual': dep.get('actual'),
                'delay_min': dep.get('delay'),
                'status': status,
                'status_emoji': {'Scheduled': '🛫', 'Active': '✈️', 'Landed': '🛬', 'Cancelled': '❌'}.get(status, '❓'),
                'otp_rating': f"{rating['otp']}% • Avg {rating['avg_delay_min']} min • {rating['risk']}"
            })
        
        df = pd.DataFrame(flights)
        if not df.empty:
            # Sort by scheduled departure time (soonest first)
            df = df.sort_values('scheduled_dt').reset_index(drop=True)
            st.success(f"Loaded {len(df)} unique departures (codeshares excluded)!")
        return df.drop(columns=['scheduled_dt'])  # Clean up temp column
    
    except Exception as e:
        st.error(f"Fetch error: {str(e)}")
        return pd.DataFrame([])

# ---------------- Resolve Bets (simplified, using real-time) ----------------
# ... (keep your existing resolve_bets function here; unchanged for now)

# ---------------- Level Calculation ----------------
# ... (keep your existing get_user_level function)

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

try:
    api_key = st.secrets["AVIATIONSTACK_API_KEY"]
    st.sidebar.success(f"API key loaded (length: {len(api_key)})")
except:
    st.sidebar.error("Secrets error – check Streamlit Cloud settings.")
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
                st.success("Registered!")
            except:
                st.error("Callsign taken.")

if st.session_state.user:
    user = st.session_state.user
    today_str = date.today().isoformat()

    c.execute("SELECT skycoins FROM users WHERE username=?", (user,))
    skycoins = c.fetchone()[0] or 500

    level, success_pct = get_user_level(user)  # your function

    st.sidebar.markdown(f"**Callsign:** {user}")
    st.sidebar.markdown(f"**SkyCoins:** **{skycoins}**")
    st.sidebar.markdown(f"**Level:** <span class='badge'>{level}</span> ({success_pct:.1f}% success)", unsafe_allow_html=True)
    if st.sidebar.button("Logout"):
        st.session_state.user = None
        st.rerun()

    st.subheader(f"Current Manchester (MAN) Departures – {today_str}")

    if st.button("🔄 Refresh Live Flights"):
        if api_key:
            st.session_state.flights = fetch_departures(api_key)
        else:
            st.error("No API key.")

    flights_df = st.session_state.get('flights', pd.DataFrame())

    if not flights_df.empty:
        # Display sorted flights as cards
        for _, row in flights_df.iterrows():
            st.markdown(f"""
            <div class="card">
                <h3><i class="fa fa-plane-departure"></i> {row['flight_id']} – {row['airline']}</h3>
                <p><strong>To:</strong> {row['destination']} ({row['dest_iata']})</p>
                <p><strong>Scheduled:</strong> {row['scheduled'][-14:-6] if row['scheduled'] else 'N/A'}</p>
                <p><strong>Status:</strong> {row['status_emoji']} {row['status']}</p>
                <p><strong>Insight:</strong> {row['otp_rating']}</p>
            </div>
            """, unsafe_allow_html=True)

        # Bet placement
        c.execute("SELECT COUNT(*) FROM bets WHERE username=? AND bet_date=? AND outcome='pending'", (user, today_str))
        pending_bets = c.fetchone()[0]

        if pending_bets < 5:
            st.subheader(f"Place a Stake ({5 - pending_bets} remaining today)")
            with st.form("bet_form"):
                # Select flight
                flight_options = [f"{row['flight_id']} → {row['dest_iata']} ({row['scheduled'][-14:-6] or 'N/A'})" for _, row in flights_df.iterrows()]
                selected_option = st.selectbox("Select Flight to Bet On", flight_options)
                
                if selected_option:
                    selected_flight_id = selected_option.split(" → ")[0]

                    bet_type = st.radio("Your Prediction", ["On Time (<15 min delay)", "Delayed", "Cancelled"])

                    delay_range = ""
                    if bet_type == "Delayed":
                        delay_range = st.selectbox("Expected Delay Range", ["Under 20 min", "20–60 min", ">60 min"])

                    submitted = st.form_submit_button("Place Bet ✈️")
                    if submitted:
                        c.execute("INSERT OR REPLACE INTO bets (username, flight_id, bet_type, delay_range, bet_date, outcome) VALUES (?,?,?,?,?,'pending')",
                                  (user, selected_flight_id, bet_type, delay_range, today_str))
                        conn.commit()
                        st.success(f"Bet placed on **{selected_flight_id}**! Good luck.")
                        st.rerun()
        else:
            st.warning("You've reached your 5 daily bets. Come back tomorrow!")

    else:
        st.info("No flights loaded yet. Press refresh (check debug above if issues).")

    # Resolution button (keep as-is)
    st.subheader("Resolve Bets (Admin)")
    if st.button("Run Resolution for Today"):
        if api_key:
            count = resolve_bets(api_key, today_str)  # your function
            st.success(f"Resolved {count} pending bets!")
        else:
            st.error("No API key.")

st.caption("SkyStake • Real-time departures only (free tier) • Codeshares excluded • Sorted soonest first")
