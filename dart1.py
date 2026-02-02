import streamlit as st
import pandas as pd
import os
from math import pow
from datetime import datetime
import random
from PIL import Image

DATEI = "dart_elo.csv"
LOG_DATEI = "dart_log.csv"
START_ELO = 1000
K_FAKTOR = 28
PASSWORT = "test"

# ---------------------
# Elo-Berechnung
# ---------------------
def erwartung(elo_a, elo_b):
    return 1 / (1 + pow(10, (elo_b - elo_a) / 400))

# ---------------------
# Spieler-Datei laden / speichern
# ---------------------
def lade_spieler():
    if os.path.exists(DATEI):
        df = pd.read_csv(DATEI, index_col=0)
    else:
        df = pd.DataFrame(columns=["Elo","Spiele"])
    return df

def speichere_spieler(df):
    df.to_csv(DATEI)

# ---------------------
# Log laden / speichern
# ---------------------
def lade_log():
    if os.path.exists(LOG_DATEI):
        return pd.read_csv(LOG_DATEI)
    else:
        return pd.DataFrame(columns=["Datum","Spieler A","Spieler B","Legs A","Legs B","Avg A","Avg B","Elo A","Elo B"])

def speichere_log(df_log):
    df_log.to_csv(LOG_DATEI,index=False)

# ---------------------
# Elo neu berechnen aus Log
# ---------------------
def berechne_elo_aus_log(df_log):
    df = lade_spieler()
    alle_spieler = pd.concat([df.index.to_series(), df_log["Spieler A"], df_log["Spieler B"]]).unique()
    for name in alle_spieler:
        if name not in df.index:
            df.loc[name] = {"Elo": START_ELO, "Spiele": 0}

    df["Elo"] = START_ELO
    df["Spiele"] = 0

    for idx, row in df_log.iterrows():
        a = row["Spieler A"]
        b = row["Spieler B"]
        legs_a = row["Legs A"]
        legs_b = row["Legs B"]
        avg_a = row["Avg A"]
        avg_b = row["Avg B"]

        elo_a = df.loc[a, "Elo"]
        elo_b = df.loc[b, "Elo"]

        exp_a = erwartung(elo_a, elo_b)
        exp_b = erwartung(elo_b, elo_a)

        score_a = 1 if legs_a > legs_b else 0
        score_b = 1 - score_a

        diff_legs = abs(legs_a - legs_b)
        G = 1 + diff_legs / 10

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

        df.loc[a, "Spiele"] = len(df_log[(df_log["Spieler A"] == a) | (df_log["Spieler B"] == a)])
        df.loc[b, "Spiele"] = len(df_log[(df_log["Spieler A"] == b) | (df_log["Spieler B"] == b)])

        df_log.at[idx, "Elo A"] = round(delta_a)
        df_log.at[idx, "Elo B"] = round(delta_b)

    speichere_spieler(df)
    speichere_log(df_log)
    return df, df_log

# ---------------------
# Neues Spiel loggen
# ---------------------
def log_spiel(a, b, legs_a, legs_b, avg_a, avg_b):
    df_log = lade_log()
    df_log.loc[len(df_log)] = {
        "Datum": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "Spieler A": a, "Spieler B": b,
        "Legs A": legs_a, "Legs B": legs_b,
        "Avg A": avg_a, "Avg B": avg_b,
        "Elo A": 0, "Elo B": 0
    }
    speichere_log(df_log)
    return berechne_elo_aus_log(df_log)

# ---------------------
# Streamlit GUI
# ---------------------
st.set_page_config(page_title="Bulls&Friends Power-Ranking", layout="wide")

# -------- Logo + Titel --------
col1, col2 = st.columns([1,4])
with col1:
    logo = Image.open("logo1.png")
    st.image(logo, width=100)
with col2:
    st.title(" Bulls&Friends Power-Ranking")
    st.markdown("<p style='color:gray; font-size:16px;'>Ergebnisse und Ranglisten jederzeit online abrufen</p>", unsafe_allow_html=True)

menu = st.sidebar.radio("Menü", ["Rangliste", "Spiel eintragen", "Spielstatistiken", "Spieler", "Spieler anlegen", "Auslosung"])


# ---------------------
# Rangliste
# ---------------------
if menu == "Rangliste":
    st.subheader("🏆 Aktuelle Rangliste")
    df_log = lade_log()
    df, df_log = berechne_elo_aus_log(df_log)
    df_sorted = df.sort_values("Elo", ascending=False)

    # Form der letzten 3 Spiele
    form_dict = {}
    for spieler in df_sorted.index:
        df_player = df_log[(df_log["Spieler A"] == spieler) | (df_log["Spieler B"] == spieler)].tail(3)
        delta_list = []
        for _, row in df_player.iterrows():
            delta_list.append(row["Elo A"] if row["Spieler A"] == spieler else row["Elo B"])
        form_dict[spieler] = sum(delta_list)

    punkte_list = []
    for spieler in df_sorted.index:
        base = df_sorted.loc[spieler, "Elo"]
        delta = form_dict.get(spieler, 0)
        if delta > 0:
            punkte_list.append(f"{base} <span style='color:green;font-size:90%;'>+{delta} &#9650;</span>")
        elif delta < 0:
            punkte_list.append(f"{base} <span style='color:red;font-size:90%;'>{delta} &#9660;</span>")
        else:
            punkte_list.append(f"{base}")

    platzierung_list = []
    for i in range(len(df_sorted)):
        if i < 3:
            platzierung_list.append(f"<span style='color:gold;font-weight:bold;'>{i+1}</span>")
        else:
            platzierung_list.append(f"{i+1}")

    df_display = pd.DataFrame({
        "Platzierung": platzierung_list,
        "Spieler": df_sorted.index,
        "Gespielte Spiele": df_sorted["Spiele"],
        "Punkte": punkte_list
    })
    st.markdown(df_display.to_html(escape=False, index=False), unsafe_allow_html=True)

# ---------------------
# Spiel eintragen
# ---------------------
elif menu == "Spiel eintragen":
    st.subheader("🔒 Spiel eintragen (passwortgeschützt)")
    pw_input = st.text_input("Passwort eingeben", type="password")
    if pw_input == PASSWORT:
        df_log = lade_log()
        df, df_log = berechne_elo_aus_log(df_log)
        df_spieler = list(lade_spieler().index)

        st.markdown("### Neues Spiel eintragen")
        with st.form("spiel_form"):
            col1, col2 = st.columns(2)
            with col1:
                a = st.selectbox("Spieler A", options=df_spieler)
                legs_a = st.number_input("Legs A", min_value=0, step=1)
                avg_a = st.number_input("Average A", min_value=0.0, step=0.1, value=50.0)
            with col2:
                b = st.selectbox("Spieler B", options=df_spieler)
                legs_b = st.number_input("Legs B", min_value=0, step=1)
                avg_b = st.number_input("Average B", min_value=0.0, step=0.1, value=50.0)
            submitted = st.form_submit_button("Match eintragen")
            if submitted:
                if a != b:
                    df, df_log = log_spiel(a, b, legs_a, legs_b, avg_a, avg_b)
                    st.success(f"{a} {legs_a}:{legs_b} {b} eingetragen! (Avg: {avg_a}/{avg_b})")
                else:
                    st.error("Bitte zwei unterschiedliche Spieler auswählen!")

# ---------------------
# Spielstatistiken
# ---------------------
elif menu == "Spielstatistiken":
    st.subheader("📊 Spielstatistiken")
    df_log = lade_log()
    if df_log.empty:
        st.info("Noch keine Spiele eingetragen.")
    else:
        for idx, row in df_log.iterrows():
            st.write(f"{row['Datum']} | {row['Spieler A']} {row['Legs A']}:{row['Legs B']} {row['Spieler B']} | Avg {row['Avg A']}/{row['Avg B']} | Elo Δ {row['Elo A']}/{row['Elo B']}")

# ---------------------
# Spieler-Statistiken
# ---------------------
elif menu == "Spieler":
    st.subheader("👤 Spieler-Statistiken")
    df_log = lade_log()
    df, df_log = berechne_elo_aus_log(df_log)
    df_spieler = list(lade_spieler().index)
    if df_spieler:
        gewaehlter_spieler = st.selectbox("Spieler auswählen", df_spieler)
        spiele = df_log[(df_log["Spieler A"] == gewaehlter_spieler) | (df_log["Spieler B"] == gewaehlter_spieler)]
        if not spiele.empty:
            siege = sum(((spiele["Spieler A"] == gewaehlter_spieler) & (spiele["Legs A"] > spiele["Legs B"])) |
                        ((spiele["Spieler B"] == gewaehlter_spieler) & (spiele["Legs B"] > spiele["Legs A"])))
            niederlagen = len(spiele) - siege
            leg_diff = sum(spiele.apply(lambda row: row["Legs A"] - row["Legs B"] if row["Spieler A"] == gewaehlter_spieler else row["Legs B"] - row["Legs A"], axis=1))
            gesamt_avg = sum(spiele.apply(lambda row: row["Avg A"] if row["Spieler A"] == gewaehlter_spieler else row["Avg B"], axis=1)) / len(spiele)
            elo = sum(spiele.apply(lambda row: row["Elo A"] if row["Spieler A"] == gewaehlter_spieler else row["Elo B"], axis=1))
        else:
            siege = niederlagen = leg_diff = 0
            gesamt_avg = 0
            elo = START_ELO
        st.write(f"**Spiele:** {len(spiele)}  |  **Siege:** {siege}  |  **Niederlagen:** {niederlagen}")
        st.write(f"**Leg-Differenz:** {leg_diff}  |  **Gesamtaverage:** {round(gesamt_avg,2)}  |  **Elo-Punkte:** {elo}")

# ---------------------
# Spieler anlegen
# ---------------------
elif menu == "Spieler anlegen":
    st.subheader("➕ Neuer Spieler (passwortgeschützt)")
    pw_input = st.text_input("Passwort eingeben", type="password", key="spieler")
    if pw_input == PASSWORT:
        df = lade_spieler()
        with st.form("spieler_form"):
            neuer_spieler = st.text_input("Spielername")
            submitted = st.form_submit_button("Spieler anlegen")
            if submitted:
                if neuer_spieler.strip() != "" and neuer_spieler.strip() not in df.index:
                    df.loc[neuer_spieler.strip()] = {"Elo": START_ELO, "Spiele": 0}
                    speichere_spieler(df)
                    st.success(f"Spieler {neuer_spieler.strip()} erfolgreich angelegt!")
                elif neuer_spieler.strip() in df.index:
                    st.warning("Spieler existiert bereits!")
                else:
                    st.error("Bitte gültigen Spielernamen eingeben.")

# ---------------------
# Auslosung (robust)
# ---------------------
elif menu == "Auslosung":
    st.subheader("🎲 Spieltags-Auslosung")
    df_spieler = list(lade_spieler().index)
    anwesend = st.multiselect("Anwesende Spieler auswählen", df_spieler)

    if st.button("Auslosung starten"):
        n = len(anwesend)
        if n < 5:
            st.warning("Bitte mindestens 5 Spieler auswählen für 4 Partien pro Spieler!")
        else:
            max_tries = 1000
            for attempt in range(max_tries):
                spiele = []
                zähler = {s:0 for s in anwesend}
                mögliche_paarungen = [(s1,s2) for i,s1 in enumerate(anwesend) for s2 in anwesend[i+1:]]
                random.shuffle(mögliche_paarungen)
                
                for s1,s2 in mögliche_paarungen:
                    if zähler[s1] < 4 and zähler[s2] < 4:
                        spiele.append((s1,s2))
                        zähler[s1] += 1
                        zähler[s2] += 1
                
                if all(v==4 for v in zähler.values()):
                    break
            else:
                st.error("Auslosung konnte nach mehreren Versuchen nicht erstellt werden. Bitte Spielerzahl prüfen.")
                st.stop()

            df_auslosung = pd.DataFrame(spiele, columns=["Spieler A","Spieler B"])
            st.table(df_auslosung)
