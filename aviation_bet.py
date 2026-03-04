import streamlit as st
import requests
import sqlite3
import pandas as pd
from datetime import date, datetime
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

# ---------------- Fetch Current Real-Time Departures ----------------
@st.cache_data(ttl=1800, show_spinner="Fetching current Manchester departures...")
def fetch_departures(api_key):
    url = "https://api.aviationstack.com/v1/flights"

    params = {
        'access_key': api_key,
        'dep_iata': 'MAN',
        'limit': 50
    }
    
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return pd.DataFrame()
        
        data = r.json()
        if 'data' not in data:
            return pd.DataFrame()
        
        flights = []
        for f in data['data']:
            if f.get('flight', {}).get('codeshared') is not None:
                continue
            
            dep = f.get('departure', {})
            status = f.get('flight_status', 'unknown').capitalize()
            dest_iata = f['arrival'].get('iata', 'UNK')
            rating = ROUTE_RATINGS.get(dest_iata, ROUTE_RATINGS['DEFAULT'])
            
            scheduled_str = dep.get('scheduled')
            scheduled_time = parser.parse(scheduled_str) if scheduled_str else datetime.max
            
            flights.append({
                'flight_id': f['flight'].get('iata', 'N/A'),
                'airline': f['airline'].get('name', 'N/A'),
                'destination': f['arrival'].get('airport', 'Unknown'),
                'dest_iata': dest_iata,
                'scheduled': scheduled_str,
                'scheduled_dt': scheduled_time,
                'estimated': dep.get('estimated'),
                'actual': dep.get('actual'),
                'delay_min': dep.get('delay'),
                'status': status,
                'status_emoji': {'Scheduled': '🛫', 'Active': '✈️', 'Landed': '🛬', 'Cancelled': '❌'}.get(status, '❓'),
                'otp_rating': f"{rating['otp']}% • Avg {rating['avg_delay_min']} min • {rating['risk']}"
            })
        
        df = pd.DataFrame(flights)
        if not df.empty:
            df = df.sort_values('scheduled_dt').reset_index(drop=True)
        return df.drop(columns=['scheduled_dt'], errors='ignore')
    
    except:
        return pd.DataFrame([])

# ---------------- Resolve Bets ----------------
def resolve_bets(api_key, target_date):
    flights_df = fetch_departures(api_key)
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
    success_rate = (correct / total) * 100 if total > 0 else 0.0
    
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

# API key
try:
    api_key = st.secrets["AVIATIONSTACK_API_KEY"]
except:
    st.sidebar.warning("No API key – using sample data.")
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
                st.success("Logged in!")
            else:
                st.error("Invalid credentials.")
    with col2:
        if st.button("Register"):
            try:
                c.execute("INSERT INTO users (username, password, skycoins) VALUES (?, ?, 500)", (username, password))
                conn.commit()
                st.session_state.user = username
                st.success("Registered!")
            except:
                st.error("Username taken.")

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

    # User's current bets
    st.sidebar.subheader("Your Bets Today")
    c.execute("SELECT flight_id, bet_type, delay_range, outcome FROM bets WHERE username=? AND bet_date=?", (user, today_str))
    current_bets = c.fetchall()
    if current_bets:
        for bet in current_bets:
            st.sidebar.markdown(f"- {bet[0]}: {bet[1]} ({bet[2]}) – {bet[3].capitalize()}")
    else:
        st.sidebar.info("No bets yet today.")

    st.subheader(f"Current Manchester Departures – {today_str}")

    if st.button("🔄 Refresh Flights"):
        st.session_state.flights = fetch_departures(api_key) if api_key else pd.DataFrame([
            {'flight_id': 'FR123', 'airline': 'Ryanair', 'destination': 'Dublin', 'dest_iata': 'DUB', 'scheduled': '2026-03-04T08:00:00+00:00', 'status': 'Scheduled', 'status_emoji': '🛫', 'otp_rating': '84% • Avg 12 min • Low'},
            {'flight_id': 'BA456', 'airline': 'British Airways', 'destination': 'London Heathrow', 'dest_iata': 'LHR', 'scheduled': '2026-03-04T09:00:00+00:00', 'status': 'Scheduled', 'status_emoji': '🛫', 'otp_rating': '72% • Avg 22 min • Medium'},
        ])

    flights_df = st.session_state.get('flights', pd.DataFrame())

    if not flights_df.empty:
        now = datetime.utcnow()
        
        for _, row in flights_df.iterrows():
            # Parse scheduled time safely
            try:
                sched_dt = parser.parse(row['scheduled']) if row['scheduled'] else datetime.max
                is_upcoming = sched_dt > now
                time_str = sched_dt.strftime("%H:%M") if row['scheduled'] else 'N/A'
            except (ValueError, TypeError):
                is_upcoming = False
                time_str = 'N/A'
            
            color = "#88ff88" if is_upcoming else "#ff8888"
            
            st.markdown(f"""
            <div class="card" style="border-left: 5px solid {color};">
                <h3><i class="fa fa-plane-departure"></i> {row['flight_id']} – {row['airline']}</h3>
                <p><strong>To:</strong> {row['destination']} ({row['dest_iata']})</p>
                <p><strong>Scheduled:</strong> {time_str} UTC</p>
                <p><strong>Status:</strong> {row['status_emoji']} {row['status']}</p>
                <p><strong>Insight:</strong> {row['otp_rating']}</p>
            </div>
            """, unsafe_allow_html=True)

        c.execute("SELECT COUNT(*) FROM bets WHERE username=? AND bet_date=? AND outcome='pending'", (user, today_str))
        pending_bets = c.fetchone()[0]

        if pending_bets < 5:
            st.subheader(f"Place a Stake ({5 - pending_bets} left today)")
            with st.form("bet_form"):
                flight_options = [f"{row['flight_id']} → {row['dest_iata']} ({row['scheduled'][-14:-6] or 'N/A'})" for _, row in flights_df.iterrows()]
                selected_option = st.selectbox("Select Flight", flight_options)
                
                if selected_option:
                    selected_flight_id = selected_option.split(" → ")[0]
                    bet_type = st.radio("Prediction", ["On Time (<15 min delay)", "Delayed", "Cancelled"])
                    delay_range = "" if bet_type != "Delayed" else st.selectbox("Delay Range", ["Under 20 min", "20–60 min", ">60 min"])
                    
                    if st.form_submit_button("Place Bet ✈️"):
                        sched = flights_df[flights_df['flight_id'] == selected_flight_id]['scheduled'].iloc[0]
                        if sched and parser.parse(sched) < datetime.utcnow():
                            st.error("Cannot bet on past flights.")
                        else:
                            c.execute("INSERT OR REPLACE INTO bets VALUES (?, ?, ?, ?, ?, 'pending')",
                                      (user, selected_flight_id, bet_type, delay_range, today_str))
                            conn.commit()
                            st.success(f"Bet placed on {selected_flight_id}!")
                            st.rerun()
        else:
            st.warning("Max 5 bets today.")

    else:
        st.info("No flights available. Try refreshing.")

    # Leaderboard
    st.subheader("Global Leaderboard")
    leaders = pd.read_sql("SELECT username, skycoins FROM users ORDER BY skycoins DESC LIMIT 10", conn)
    for i, row in leaders.iterrows():
        lvl, _ = get_user_level(row['username'])
        emoji = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
        st.markdown(f"{emoji} **{row['username']}** – {row['skycoins']} SkyCoins ({lvl})")

    # Resolution
    st.subheader("Resolve Bets")
    if st.button("Resolve Today's Bets"):
        count = resolve_bets(api_key, today_str) if api_key else 0
        st.success(f"Resolved {count} bets.")

st.caption("SkyStake v1.0 • Real-time Aviation Betting • Powered by AviationStack")
