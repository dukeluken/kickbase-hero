import feedparser
import re

LIGAINSIDER_RSS_URL = "https://www.ligainsider.de/rss/"

POSITIVE_KEYWORDS = [
    "startelf", "fit", "trainingsrückkehr", "kader", 
    "einsatzbereit", "startet", "mit dabei", "beschwerdefrei"
]

NEGATIVE_KEYWORDS = [
    "ausfall", "verletz", "fehlt", "gesperrt", "fraglich", 
    "abbruch", "pause", "geschont", "ausgewechselt", "operiert"
]

def fetch_latest_news():
    """Lädt die neuesten Nachrichten von LigaInsider via RSS."""
    try:
        feed = feedparser.parse(LIGAINSIDER_RSS_URL)
        news_list = []
        for entry in feed.entries:
            news_list.append({
                "title": entry.title,
                "summary": entry.get("summary", ""),
                "link": entry.link,
                "published": entry.get("published", "")
            })
        return news_list
    except Exception:
        return []

def match_news_with_players(news_list, player_list):
    """
    Gleicht RSS-News mit einer Spielerliste (z.B. Transfermarkt) ab.
    Gibt Spieler mit zugehörigen Live-Alerts zurück.
    """
    alerts = []
    
    for player in player_list:
        first_name = player.get("firstName", "")
        last_name = player.get("lastName", "")
        full_name = f"{first_name} {last_name}".strip()
        
        if not last_name:
            continue

        last_name_pattern = re.compile(rf"\b{re.escape(last_name)}\b", re.IGNORECASE)
        
        for item in news_list:
            text = f"{item['title']} {item['summary']}".lower()
            
            if full_name.lower() in text or (len(last_name) > 3 and last_name_pattern.search(text)):
                is_positive = any(kw in text for kw in POSITIVE_KEYWORDS)
                is_negative = any(kw in text for kw in NEGATIVE_KEYWORDS)
                
                signal = "NEUTRAL"
                if is_negative:
                    signal = "🚨 NEGATIV (DROHENDER VERFALL)"
                elif is_positive:
                    signal = "🔥 POSITIV (STEIGERUNG ERWARTET)"
                
                alerts.append({
                    "player_id": player.get("id"),
                    "player_name": full_name,
                    "signal": signal,
                    "news_title": item["title"],
                    "link": item["link"],
                    "published": item["published"]
                })
                break
                
    return alerts
