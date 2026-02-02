import streamlit as st
import pandas as pd
import random
import math
from datetime import datetime
from pathlib import Path

# ======================
# CONFIG
# ======================
PASSWORT = "test"
K_FAKTOR = 32

DATA_DIR = Path(".")
SPIELER_DATEI = DATA_DIR / "spieler.csv"
SPIELE_DATEI = DATA_DIR / "spiele.csv"

# ======================
# MOBILE + DESIGN CSS
# ======================
st.markdown("""
<style>

/* ===== GLOBAL ===== */
.block-container {
    padding: 2rem 2rem 4rem 2rem;
}

section[data-testid="stSidebar"] {
    width: 260px !important;
}

/* Tabellen */
thead tr th {
    background-color: #f5f5f5;
    font-weight: bold;
}

/* Mobile Karten */
@media screen and (max-width: 600px) {

    .block-container {
        padding: 0.5rem 0.5rem 4rem 0.5rem;
    }

    .stDataFrame {
        display: none;
    }

    .mobile-card {
        background: white;
        padding: 0.8rem;
        border-radius: 10px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.1);
        margin-bottom: 0.7rem;
    }

    .mobile-title {
        font-weight: bold;
        font-size: 1.05rem;
    }

    .mobile-sub {
        font-size: 0.9rem;
        color: #666;
    }
}

</style>
""", unsafe_allow_html=True)

# ======================
# LOGO
# ======================
if Path("logo1.png").exists():
    st.image("logo1.png", width=160)

st.title("🎯 Dart Vereins-Rangliste")

# ======================
# DATEIEN LADEN / ERSTELLEN
# ======================
def lade_spieler():
    if SPIELER_DATEI.exists():
        df = pd.read_csv(SPIELER_DATEI)
    else:
        df = pd.DataFrame(columns=["Spieler", "Punkte"])
    # Absicherung Spalten
    if "Punkte" not in df.columns:
        df["Punkte"] = 1000
    if "Spieler" not in df.columns:
        st.error("Spieler CSV hat keine 'Spieler' Spalte. Bitte prüfen!")
        st.stop()
    return df

def lade_spiele():
    if SPIELE_DATEI.exists():
        return pd.read_csv(SPIELE_DATEI)
    return pd.DataFrame(columns=[
        "Datum", "Spieler A", "Spieler B",
        "Legs A", "Legs B",
        "Avg A", "Avg B",
        "Elo A", "Elo B"
    ])

def speichern_spieler(df):
    df.to_csv(SPIELER_DATEI, index=False)

def speichern_spiele(df):
    df.to_csv(SPIELE_DATEI, index=False)

spieler_df = lade_spieler()
spiele_df = lade_spiele()

# ======================
# ELO SYSTEM
# ======================
def erwartung(a, b):
    return 1 / (1 + 10 ** ((b - a) / 400))

def avg_faktor(avg):
    return min(1.15, max(0.85, 1 + (avg - 50) / 250))

def berechne_elo(a_elo, b_elo, score_a, score_b, legs_a, legs_b, avg_a, avg_b):
    exp_a = erwartung(a_elo, b_elo)
    exp_b = erwartung(b_elo, a_elo)

    diff_legs = abs(legs_a - legs_b)
    G = 1 + diff_legs / 10

    F_a = avg_faktor(avg_a)
    F_b = avg_faktor(avg_b)

    neu_a = round(a_elo + K_FAKTOR * G * F_a * (score_a - exp_a))
    neu_b = round(b_elo + K_FAKTOR * G * F_b * (score_b - exp_b))

    return neu_a, neu_b, neu_a - a_elo, neu_b - b_elo

# ======================
# FORM BERECHNUNG
# ======================
def form_pfeil(spielername):
    letzte = spiele_df[
        (spiele_df["Spieler A"] == spielername) |
        (spiele_df["Spieler B"] == spielername)
    ].tail(3)

    gesamt = 0
    for _, row in letzte.iterrows():
        if row["Spieler A"] == spielername:
            gesamt += row["Elo A"]
        else:
            gesamt += row["Elo B"]

    if gesamt > 0:
        return f"<span style='color:green;font-size:0.85rem'>+{gesamt} ↑</span>"
    elif gesamt < 0:
        return f"<span style='color:red;font-size:0.85rem'>{gesamt} ↓</span>"
    else:
        return "<span style='color:gray;font-size:0.85rem'>0 →</span>"

# ======================
# NAVIGATION
# ======================
menu = st.sidebar.radio(
    "Navigation",
    ["Rangliste", "Spiel eintragen", "Spielstatistiken", "Spieler", "Spieler anlegen", "Auslosung"],
    label_visibility="collapsed"
)

# ======================
# RANGLISTE
# ======================
if menu == "Rangliste":

    rang = []
    for _, row in spieler_df.iterrows():
        name = row["Spieler"]
        spiele = spiele_df[
            (spiele_df["Spieler A"] == name) |
            (spiele_df["Spieler B"] == name)
        ]

        rang.append({
            "Spieler": name,
            "Gespielte Spiele": len(spiele),
            "Punkte": row["Punkte"],
            "Form": form_pfeil(name)
        })

    df = pd.DataFrame(rang)
    if "Punkte" not in df.columns:
        df["Punkte"] = 1000

    df = df.sort_values("Punkte", ascending=False).reset_index(drop=True)
    df.insert(0, "Platzierung", df.index + 1)
    df = df[["Platzierung", "Spieler", "Gespielte Spiele", "Punkte", "Form"]]

    st.subheader("🏆 Aktuelle Rangliste")
    st.dataframe(df, use_container_width=True, hide_index=True)

    for _, row in df.iterrows():
        st.markdown(f"""
        <div class="mobile-card">
            <div class="mobile-title">#{row['Platzierung']} {row['Spieler']}</div>
            <div class="mobile-sub">Spiele: {row['Gespielte Spiele']}</div>
            <div class="mobile-sub">Punkte: {row['Punkte']} {row['Form']}</div>
        </div>
        """, unsafe_allow_html=True)

# ======================
# SPIEL EINTRAGEN
# ======================
elif menu == "Spiel eintragen":
    st.subheader("🎯 Spiel eintragen")

    pw = st.text_input("Passwort", type="password")
    if pw != PASSWORT:
        st.warning("Passwort erforderlich")
        st.stop()

    namen = spieler_df["Spieler"].tolist()

    a = st.selectbox("Spieler A", namen)
    b = st.selectbox("Spieler B", [n for n in namen if n != a])

    legs_a = st.number_input("Legs A", 0, 10, 3)
    legs_b = st.number_input("Legs B", 0, 10, 1)

    avg_a = st.number_input("Average A", 0.0, 150.0, 50.0)
    avg_b = st.number_input("Average B", 0.0, 150.0, 50.0)

    if st.button("Spiel speichern"):
        elo_a = int(spieler_df.loc[spieler_df["Spieler"] == a, "Punkte"].values[0])
        elo_b = int(spieler_df.loc[spieler_df["Spieler"] == b, "Punkte"].values[0])

        score_a = 1 if legs_a > legs_b else 0
        score_b = 1 - score_a

        neu_a, neu_b, diff_a, diff_b = berechne_elo(
            elo_a, elo_b, score_a, score_b,
            legs_a, legs_b, avg_a, avg_b
        )

        spieler_df.loc[spieler_df["Spieler"] == a, "Punkte"] = neu_a
        spieler_df.loc[spieler_df["Spieler"] == b, "Punkte"] = neu_b

        speichern_spieler(spieler_df)

        spiele_df.loc[len(spiele_df)] = [
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            a, b, legs_a, legs_b,
            avg_a, avg_b,
            diff_a, diff_b
        ]

        speichern_spiele(spiele_df)

        st.success("Spiel gespeichert!")

        st.markdown(f"""
        ### 📋 Spiel-Zusammenfassung
        **{a} {legs_a}:{legs_b} {b}**  
        Avg: {avg_a} | {avg_b}  
        Elo: {diff_a:+} | {diff_b:+}
        """)

# ======================
# SPIELSTATISTIKEN
# ======================
elif menu == "Spielstatistiken":
    st.subheader("📊 Spiele")
    st.dataframe(spiele_df.sort_index(ascending=False), use_container_width=True)

# ======================
# SPIELER DETAIL
# ======================
elif menu == "Spieler":
    st.subheader("👤 Spieler Statistik")
    name = st.selectbox("Spieler auswählen", spieler_df["Spieler"].tolist())

    spiele = spiele_df[
        (spiele_df["Spieler A"] == name) |
        (spiele_df["Spieler B"] == name)
    ]

    siege = 0
    niederlagen = 0
    legdiff = 0
    avgs = []

    for _, s in spiele.iterrows():
        if s["Spieler A"] == name:
            legdiff += s["Legs A"] - s["Legs B"]
            avgs.append(s["Avg A"])
            if s["Legs A"] > s["Legs B"]:
                siege += 1
            else:
                niederlagen += 1
        else:
            legdiff += s["Legs B"] - s["Legs A"]
            avgs.append(s["Avg B"])
            if s["Legs B"] > s["Legs A"]:
                siege += 1
            else:
                niederlagen += 1

    st.metric("Spiele", len(spiele))
    st.metric("Siege", siege)
    st.metric("Niederlagen", niederlagen)
    st.metric("Leg-Differenz", legdiff)
    st.metric("Ø Average", round(sum(avgs) / len(avgs), 1) if avgs else 0)

# ======================
# SPIELER ANLEGEN
# ======================
elif menu == "Spieler anlegen":
    st.subheader("➕ Neuer Spieler")

    pw = st.text_input("Passwort", type="password")
    if pw != PASSWORT:
        st.warning("Passwort erforderlich")
        st.stop()

    name = st.text_input("Spielername")

    if st.button("Spieler speichern"):
        if name and name not in spieler_df["Spieler"].values:
            spieler_df.loc[len(spieler_df)] = [name, 1000]
            speichern_spieler(spieler_df)
            st.success("Spieler angelegt!")

# ======================
# AUSLOSUNG
# ======================
elif menu == "Auslosung":
    st.subheader("🎲 Spieltags-Auslosung")

    teilnehmer = st.multiselect("Anwesende Spieler", spieler_df["Spieler"].tolist())

    if st.button("Auslosen"):
        if len(teilnehmer) < 5:
            st.error("Mindestens 5 Spieler nötig")
        else:
            paare = set()
            spiele = []

            for s in teilnehmer:
                gegner = [g for g in teilnehmer if g != s]
                random.shuffle(gegner)
                count = 0
                for g in gegner:
                    pair = tuple(sorted([s, g]))
                    if pair not in paare:
                        paare.add(pair)
                        spiele.append(pair)
                        count += 1
                    if count == 4:
                        break

            for i, (a, b) in enumerate(spiele, 1):
                st.write(f"Spiel {i}: {a} vs {b}")



