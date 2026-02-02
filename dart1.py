import streamlit as st
import pandas as pd
import os
from math import pow
from datetime import datetime
import random
from PIL import Image

# ---------------------
# Konfiguration
# ---------------------
DATEI = "dart_elo.csv"
LOG_DATEI = "dart_log.csv"
START_ELO = 1000
K_FAKTOR = 28
PASSWORT = "test"

# ---------------------
# Mobile CSS
# ---------------------
st.set_page_config(page_title="Dart Vereins-Elo", layout="wide")

st.markdown("""
<style>
@media only screen and (max-width: 768px) {
    .block-container {
        padding: 0.5rem 0.5rem 4rem 0.5rem;
    }
    h1, h2, h3 {
        font-size: 1.2rem !important;
    }
    button {
        width: 100% !important;
        font-size: 1rem !important;
    }
    .stDataFrame, .stTable {
        font-size: 0.8rem;
    }
}
</style>
""", unsafe_allow_html=True)

# ---------------------
# Hilfsfunktionen
# ---------------------
def erwartung(elo_a, elo_b):
    return 1 / (1 + pow(10, (elo_b - elo_a) / 400))

def lade_spieler():
    if os.path.exists(DATEI):
        return pd.read_csv(DATEI, index_col=0)
    return pd.DataFrame(columns=["Elo", "Spiele"])

def speichere_spieler(df):
    df.to_csv(DATEI)

def lade_log():
    if os.path.exists(LOG_DATEI):
        return pd.read_csv(LOG_DATEI)
    return pd.DataFrame(columns=["Datum", "Spieler A", "Spieler B", "Legs A", "Legs B", "Avg A", "Avg B", "Elo A", "Elo B"])

def speichere_log(df):
    df.to_csv(LOG_DATEI, index=False)

# ---------------------
# Elo neu berechnen
# ---------------------
def berechne_elo_aus_log(df_log):
    df = lade_spieler()

    alle = pd.concat([
        df.index.to_series(),
        df_log["Spieler A"],
        df_log["Spieler B"]
    ]).dropna().unique()

    for s in alle:
        if s not in df.index:
            df.loc[s] = {"Elo": START_ELO, "Spiele": 0}

    df["Elo"] = START_ELO
    df["Spiele"] = 0

    for i, r in df_log.iterrows():
        a, b = r["Spieler A"], r["Spieler B"]
        legs_a, legs_b = int(r["Legs A"]), int(r["Legs B"])
        avg_a, avg_b = float(r["Avg A"]), float(r["Avg B"])

        elo_a = df.loc[a, "Elo"]
        elo_b = df.loc[b, "Elo"]

        exp_a = erwartung(elo_a, elo_b)
        exp_b = erwartung(elo_b, elo_a)

        score_a = 1 if legs_a > legs_b else 0
        score_b = 1 - score_a

        G = 1 + abs(legs_a - legs_b) / 10
        U_a = min(1.3, 1 + (elo_b - elo_a) / 2000)
        U_b = min(1.3, 1 + (elo_a - elo_b) / 2000)
        D = min(1.3, 1 + abs(elo_a - elo_b) / 1200)

        c = 0.1
        M_a = 1 + c * (avg_a - 50) / 50
        M_b = 1 + c * (avg_b - 50) / 50

        delta_a = K_FAKTOR * G * U_a * D * (score_a - exp_a) * M_a
        delta_b = K_FAKTOR * G * U_b * D * (score_b - exp_b) * M_b

        df.loc[a, "Elo"] = round(elo_a + delta_a)
        df.loc[b, "Elo"] = round(elo_b + delta_b)

        df_log.at[i, "Elo A"] = round(delta_a)
        df_log.at[i, "Elo B"] = round(delta_b)

    for s in df.index:
        df.loc[s, "Spiele"] = len(df_log[(df_log["Spieler A"] == s) | (df_log["Spieler B"] == s)])

    speichere_spieler(df)
    speichere_log(df_log)
    return df, df_log

# ---------------------
# Spiel speichern
# ---------------------
def log_spiel(a, b, la, lb, avga, avgb):
    df_log = lade_log()

    neu = {
        "Datum": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "Spieler A": a,
        "Spieler B": b,
        "Legs A": la,
        "Legs B": lb,
        "Avg A": avga,
        "Avg B": avgb,
        "Elo A": 0,
        "Elo B": 0
    }

    df_log.loc[len(df_log)] = neu
    speichere_log(df_log)

    df, df_log = berechne_elo_aus_log(df_log)
    last = df_log.iloc[-1].to_dict()
    st.session_state["last_match"] = last
    return df

# ---------------------
# Header
# ---------------------
col1, col2 = st.columns([1, 4])
with col1:
    if os.path.exists("logo1.png"):
        st.image(Image.open("logo1.png"), width=90)
with col2:
    st.title("🎯 Dart Vereins-Elo System")
    st.markdown("<p style='color:gray;'>Live-Rangliste & Spielverwaltung</p>", unsafe_allow_html=True)

# ---------------------
# Sidebar Navigation
# ---------------------
if "menu" not in st.session_state:
    st.session_state.menu = "Rangliste"

st.sidebar.markdown("### 📌 Menü")
for m in ["Rangliste", "Spiel eintragen", "Spielstatistiken", "Spieler", "Spieler anlegen", "Auslosung"]:
    if st.sidebar.button(m):
        st.session_state.menu = m

menu = st.session_state.menu

# ---------------------
# Rangliste
# ---------------------
if menu == "Rangliste":
    df = lade_spieler()
    if not df.empty:
        df = df.sort_values("Elo", ascending=False).reset_index()
        df.index += 1
        df.columns = ["Spieler", "Punkte", "Gespielte Spiele"]
        df.insert(0, "Platzierung", df.index)
        st.table(df)
    else:
        st.info("Noch keine Spieler vorhanden.")

# ---------------------
# Spiel eintragen
# ---------------------
elif menu == "Spiel eintragen":
    st.subheader("➕ Spiel eintragen")

    df = lade_spieler()
    spieler = list(df.index)

    if len(spieler) < 2:
        st.warning("Bitte zuerst Spieler anlegen.")
    else:
        a = st.selectbox("Spieler A", spieler)
        b = st.selectbox("Spieler B", [s for s in spieler if s != a])

        la = st.number_input("Legs Spieler A", 0, 20, 3)
        lb = st.number_input("Legs Spieler B", 0, 20, 1)

        avga = st.number_input("Average Spieler A", 0.0, 120.0, 50.0)
        avgb = st.number_input("Average Spieler B", 0.0, 120.0, 50.0)

        pw = st.text_input("Passwort", type="password")

        if st.button("Spiel speichern"):
            if pw != PASSWORT:
                st.error("Falsches Passwort")
            else:
                log_spiel(a, b, la, lb, avga, avgb)
                st.success("Spiel gespeichert!")

    # ---------------------
    # Zusammenfassung
    # ---------------------
    if "last_match" in st.session_state:
        m = st.session_state["last_match"]

        def elo_fmt(val):
            col = "green" if val >= 0 else "red"
            arrow = "↑" if val >= 0 else "↓"
            return f"<span style='color:{col}'>{'+' if val>=0 else ''}{val} {arrow}</span>"

        st.markdown("### 🧾 Letztes Spiel – Zusammenfassung")
        st.markdown(f"""
        <div style="background:#f5f5f5;padding:15px;border-radius:10px;">
        <b>{m['Spieler A']}</b> {m['Legs A']} : {m['Legs B']} <b>{m['Spieler B']}</b><br><br>
        Average {m['Spieler A']}: {m['Avg A']}<br>
        Average {m['Spieler B']}: {m['Avg B']}<br><br>
        Elo {m['Spieler A']}: {elo_fmt(int(m['Elo A']))}<br>
        Elo {m['Spieler B']}: {elo_fmt(int(m['Elo B']))}
        </div>
        """, unsafe_allow_html=True)

# ---------------------
# Spieler anlegen
# ---------------------
elif menu == "Spieler anlegen":
    st.subheader("👤 Spieler anlegen")

    name = st.text_input("Name")
    pw = st.text_input("Passwort", type="password")

    if st.button("Spieler speichern"):
        if pw != PASSWORT:
            st.error("Falsches Passwort")
        else:
            df = lade_spieler()
            if name in df.index:
                st.warning("Spieler existiert bereits")
            else:
                df.loc[name] = {"Elo": START_ELO, "Spiele": 0}
                speichere_spieler(df)
                st.success("Spieler angelegt!")

# ---------------------
# Spielstatistiken
# ---------------------
elif menu == "Spielstatistiken":
    df_log = lade_log()
    if df_log.empty:
        st.info("Noch keine Spiele gespeichert.")
    else:
        st.dataframe(df_log)

# ---------------------
# Spielerübersicht
# ---------------------
elif menu == "Spieler":
    df = lade_spieler()
    df_log = lade_log()

    spieler = list(df.index)
    s = st.selectbox("Spieler auswählen", spieler)

    spiele = df_log[(df_log["Spieler A"] == s) | (df_log["Spieler B"] == s)]

    if spiele.empty:
        st.info("Noch keine Spiele für diesen Spieler.")
    else:
        wins = 0
        legs_diff = 0
        avg_list = []

        for _, r in spiele.iterrows():
            if r["Spieler A"] == s:
                wins += 1 if r["Legs A"] > r["Legs B"] else 0
                legs_diff += r["Legs A"] - r["Legs B"]
                avg_list.append(r["Avg A"])
            else:
                wins += 1 if r["Legs B"] > r["Legs A"] else 0
                legs_diff += r["Legs B"] - r["Legs A"]
                avg_list.append(r["Avg B"])

        st.metric("Spiele", len(spiele))
        st.metric("Siege", wins)
        st.metric("Niederlagen", len(spiele) - wins)
        st.metric("Leg-Differenz", legs_diff)
        st.metric("Ø Average", round(sum(avg_list) / len(avg_list), 1))
        st.metric("Elo Punkte", int(df.loc[s, "Elo"]))

# ---------------------
# Auslosung
# ---------------------
elif menu == "Auslosung":
    st.subheader("🎲 Spieltags-Auslosung")

    df = lade_spieler()
    anwesend = st.multiselect("Anwesende Spieler", list(df.index))

    if st.button("Auslosung starten"):
        n = len(anwesend)
        if n < 5:
            st.warning("Mindestens 5 Spieler nötig.")
        else:
            for _ in range(500):
                z = {s: 0 for s in anwesend}
                pairs = [(a, b) for i, a in enumerate(anwesend) for b in anwesend[i+1:]]
                random.shuffle(pairs)
                spiele = []

                for a, b in pairs:
                    if z[a] < 4 and z[b] < 4:
                        z[a] += 1
                        z[b] += 1
                        spiele.append((a, b))

                if all(v == 4 for v in z.values()):
                    st.table(pd.DataFrame(spiele, columns=["Spieler A", "Spieler B"]))
                    break
            else:
                st.error("Keine gültige Auslosung möglich. Mehr Spieler auswählen.")

