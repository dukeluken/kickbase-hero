import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from bs4 import BeautifulSoup
import urllib.parse
from news_scraper import fetch_latest_news, match_news_with_players

st.set_page_config(page_title="Kickbase Pro Advisor", page_icon="⚽", layout="wide")

BASE_URL = "https://api.kickbase.com/v4"

# --- 1. KICKBASE API HELPER ---
def login(email, password):
    payload = {"em": email, "pass": password, "loy": False, "rep": {}}
    res = requests.post(f"{BASE_URL}/user/login", json=payload)
    if res.status_code == 200:
        return res.json().get("tkn")
    return None

def get_leagues(token):
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.get(f"{BASE_URL}/leagues/selection", headers=headers)
    return res.json().get("leagues", []) if res.status_code == 200 else []

def get_market(token, league_id):
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.get(f"{BASE_URL}/leagues/{league_id}/market", headers=headers)
    return res.json().get("players", []) if res.status_code == 200 else []

def get_lineup(token, league_id):
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.get(f"{BASE_URL}/leagues/{league_id}/lineup", headers=headers)
    return res.json().get("players", []) if res.status_code == 200 else []

@st.cache_data(ttl=1800)
def get_player_stats(token, player_id):
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.get(f"{BASE_URL}/players/{player_id}/stats", headers=headers)
    return res.json() if res.status_code == 200 else {}

# --- 2. LIGAIN SIDER STATUS SCRAPER ---
@st.cache_data(ttl=3600)
def get_ligainsider_status(player_name):
    try:
        search_query = urllib.parse.quote(player_name)
        url = f"https://www.ligainsider.de/suche/{search_query}/"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code != 200:
            return "Unbekannt", "Keine Verbindung zu LigaInsider"
            
        soup = BeautifulSoup(resp.text, "html.parser")
        page_text = soup.get_text().lower()
        
        if "verletz" in page_text or "ausfall" in page_text or "gesperrt" in page_text:
            return "Ausfall", "🔴 Ausfall / Verletzung / Sperre droht"
        elif "fraglich" in page_text or "anschlag" in page_text:
            return "Fraglich", "🟡 Einsatz für kommenden Spieltag fraglich"
        elif "bank" in page_text or "rotationskandidat" in page_text:
            return "Bank", "🟠 Bankplatz / Rotationsrisiko"
        elif "startelf" in page_text or "sicher" in page_text:
            return "Startelf", "🟢 Voraussichtliche Startelf"
        else:
            return "Fit", "🟢 Keine negativen Meldungen bekannt"
    except Exception:
        return "Unbekannt", "Status konnte nicht gescrapt werden"

# --- 3. PEAK & TREND ANALYSE ---
def analyze_peak_and_recommendation(player_data, stats_data, li_status, li_info):
    mv = player_data.get("marketValue", 0)
    avg_points = player_data.get("averagePoints", 0)
    mv_in_mio = max(mv / 1_000_000, 0.5)
    ppm = round(avg_points / mv_in_mio, 2)
    
    mv_history = stats_data.get("marketValueStats", [])
    
    daily_delta = 0
    acceleration = 0
    peak_warning = False
    
    if len(mv_history) >= 3:
        mv_today = mv_history[-1].get("m", mv)
        mv_yesterday = mv_history[-2].get("m", mv)
        mv_prev_day = mv_history[-3].get("m", mv)
        
        daily_delta = mv_today - mv_yesterday
        prev_delta = mv_yesterday - mv_prev_day
        acceleration = daily_delta - prev_delta
        
        if daily_delta > 0 and acceleration < -25_000:
            peak_warning = True

    recommendation = "HALTEN"
    reason = []

    if li_status == "Ausfall":
        recommendation = "🚨 VERKAUFEN (AUSFALL)"
        reason.append(li_info)
    elif daily_delta < 0:
        recommendation = "🛑 VERKAUFEN (FALLEND)"
        reason.append(f"Marktwert verliert {abs(daily_delta):,} €/Tag")
    elif peak_warning:
        recommendation = "⚠️ PEAK NAHT (BALD VERKAUFEN)"
        reason.append(f"Anstieg flacht ab (Beschleunigung: {acceleration:,} €/Tag²). Verfall droht in 1-2 Tagen!")
    elif daily_delta > 100_000 and li_status in ["Startelf", "Fit"]:
        recommendation = "🔥 MUST-BUY / PUSHEN"
        reason.append(f"Starker Anstieg (+{daily_delta:,} €/Tag) & Stammspieler-Status")
    elif ppm >= 5.0:
        recommendation = "💎 TOP PREIS-LEISTUNG"
        reason.append(f"Sehr hohes Punkte/Preis-Verhältnis (PPM: {ppm})")
    else:
        reason.append(f"Stabile Entwicklung (+{daily_delta:,} €/Tag)")

    return {
        "Name": f"{player_data.get('firstName', '')} {player_data.get('lastName', '')}".strip(),
        "Position": player_data.get("position"),
        "Marktwert (€)": mv,
        "Δ / Tag (€)": daily_delta,
        "Beschleunigung (€)": acceleration,
        "PPM": ppm,
        "Schnitt": avg_points,
        "LigaInsider": li_status,
        "Empfehlung": recommendation,
        "Begründung": " | ".join(reason),
        "player_id": player_data.get("id"),
        "history": mv_history
    }

# --- 4. STREAMLIT UI ---
st.title("⚽ Kickbase Local Advisor — Pro Analytics")

with st.sidebar:
    st.header("🔑 Kickbase Login")
    email = st.text_input("E-Mail")
    password = st.text_input("Passwort", type="password")
    login_btn = st.button("Anmelden")

if "token" not in st.session_state:
    st.session_state["token"] = None

if login_btn and email and password:
    token = login(email, password)
    if token:
        st.session_state["token"] = token
        st.success("Erfolgreich eingeloggt!")
    else:
        st.error("Login fehlgeschlagen. Anmeldedaten prüfen.")

if st.session_state["token"]:
    token = st.session_state["token"]
    leagues = get_leagues(token)
    
    if leagues:
        league_names = {l["name"]: l["id"] for l in leagues}
        selected_league_name = st.selectbox("Liga auswählen", list(league_names.keys()))
        league_id = league_names[selected_league_name]
        
        tab1, tab2 = st.tabs(["🛒 Transfermarkt & News", "📋 Mein Kader"])
        
        def render_player_table(raw_players, is_market=True):
            analyzed = []
            with st.spinner("Analysiere Marktwert-Kurven & LigaInsider..."):
                for p in raw_players:
                    p_name = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
                    p_id = p.get("id")
                    
                    stats = get_player_stats(token, p_id)
                    li_status, li_info = get_ligainsider_status(p_name)
                    res = analyze_peak_and_recommendation(p, stats, li_status, li_info)
                    analyzed.append(res)
            
            df = pd.DataFrame(analyzed)
            
            display_cols = ["Name", "Empfehlung", "LigaInsider", "Marktwert (€)", "Δ / Tag (€)", "Beschleunigung (€)", "PPM", "Begründung"]
            st.dataframe(
                df[display_cols].sort_values(by="Δ / Tag (€)", ascending=False),
                use_container_width=True,
                height=400
            )
            
            st.markdown("### 📈 Marktwert-Verlauf & Peak-Analyse")
            selected_player_name = st.selectbox(
                "Spieler auswählen für Detail-Graph",
                df["Name"].tolist(),
                key="select_" + ("m" if is_market else "k")
            )
            
            if selected_player_name:
                p_row = df[df["Name"] == selected_player_name].iloc[0]
                history = p_row["history"]
                
                if history:
                    hist_df = pd.DataFrame(history)
                    hist_df["Datum"] = pd.to_datetime(hist_df["d"])
                    hist_df["Marktwert"] = hist_df["m"]
                    
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=hist_df["Datum"], 
                        y=hist_df["Marktwert"],
                        mode='lines+markers',
                        name='Marktwert (€)',
                        line=dict(color='#00CC96', width=3)
                    ))
                    fig.update_layout(
                        title=f"Marktwert-Entwicklung: {selected_player_name}",
                        xaxis_title="Datum",
                        yaxis_title="Marktwert in €",
                        template="plotly_dark",
                        height=350
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    st.info(f"**Empfehlung:** {p_row['Empfehlung']} — *{p_row['Begründung']}*")

        # --- TAB 1: TRANSFERMARKT & NEWS ---
        with tab1:
            st.subheader("🛒 Transfermarkt")
            market_raw = get_market(token, league_id)
            
            if market_raw:
                latest_news = fetch_latest_news()
                alerts = match_news_with_players(latest_news, market_raw)
                
                if alerts:
                    st.markdown("#### 🔔 Eil-News Alerts für Transfermarkt-Spieler")
                    for alert in alerts:
                        if "POSITIV" in alert["signal"]:
                            st.success(f"**{alert['player_name']}**: {alert['signal']}\n\n[{alert['news_title']}]({alert['link']})")
                        elif "NEGATIV" in alert["signal"]:
                            st.error(f"**{alert['player_name']}**: {alert['signal']}\n\n[{alert['news_title']}]({alert['link']})")
                        else:
                            st.info(f"**{alert['player_name']}**: {alert['news_title']} - [Details]({alert['link']})")
                
                render_player_table(market_raw, is_market=True)
            else:
                st.info("Keine Spieler auf dem Transfermarkt.")
                
        # --- TAB 2: MEIN KADER ---
        with tab2:
            st.subheader("📋 Mein Kader")
            lineup_raw = get_lineup(token, league_id)
            if lineup_raw:
                render_player_table(lineup_raw, is_market=False)
            else:
                st.info("Kader konnte nicht geladen werden.")
else:
    st.warning("Bitte melde dich in der Sidebar mit deinen Kickbase-Daten an.")
