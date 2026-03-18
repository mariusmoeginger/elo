import streamlit as st
import pandas as pd
import os
from math import pow
from datetime import datetime
from PIL import Image
from supabase import create_client
 
# ---------------------
# KONFIGURATION
# ---------------------
START_ELO = 1000
K_FAKTOR = 28
PASSWORT = "bfelo"
 
# ---------------------
# SUPABASE VERBINDUNG
# ---------------------
@st.cache_resource
def get_supabase():
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)
 
# ---------------------
# DATEIEN LADEN/SPEICHERN
# ---------------------
def lade_spieler():
    sb = get_supabase()
    res = sb.table("spieler").select("*").execute()
    if not res.data:
        return pd.DataFrame(columns=["Elo", "Spiele"])
    df = pd.DataFrame(res.data).set_index("name")
    df = df.rename(columns={"elo": "Elo", "spiele": "Spiele"})
    return df[["Elo", "Spiele"]]
 
def speichere_spieler(df):
    sb = get_supabase()
    for name, row in df.iterrows():
        sb.table("spieler").upsert({
            "name": name,
            "elo": int(row["Elo"]),
            "spiele": int(row["Spiele"])
        }).execute()
 
def lade_log():
    sb = get_supabase()
    res = sb.table("spiele_log").select("*").order("id").execute()
    if not res.data:
        return pd.DataFrame(columns=["Datum","Spieler A","Spieler B","Legs A","Legs B","Avg A","Avg B","Elo A","Elo B"])
    df = pd.DataFrame(res.data)
    df = df.rename(columns={
        "datum": "Datum", "spieler_a": "Spieler A", "spieler_b": "Spieler B",
        "legs_a": "Legs A", "legs_b": "Legs B",
        "avg_a": "Avg A", "avg_b": "Avg B",
        "elo_a": "Elo A", "elo_b": "Elo B"
    })
    return df
 
def speichere_log(df):
    sb = get_supabase()
    for _, row in df.iterrows():
        if "id" in df.columns and pd.notna(row.get("id")):
            sb.table("spiele_log").update({
                "datum": row["Datum"],
                "spieler_a": row["Spieler A"],
                "spieler_b": row["Spieler B"],
                "legs_a": int(row["Legs A"]),
                "legs_b": int(row["Legs B"]),
                "avg_a": float(row["Avg A"]),
                "avg_b": float(row["Avg B"]),
                "elo_a": int(row["Elo A"]),
                "elo_b": int(row["Elo B"])
            }).eq("id", int(row["id"])).execute()
        else:
            sb.table("spiele_log").insert({
                "datum": row["Datum"],
                "spieler_a": row["Spieler A"],
                "spieler_b": row["Spieler B"],
                "legs_a": int(row["Legs A"]),
                "legs_b": int(row["Legs B"]),
                "avg_a": float(row["Avg A"]),
                "avg_b": float(row["Avg B"]),
                "elo_a": int(row["Elo A"]),
                "elo_b": int(row["Elo B"])
            }).execute()
 
# ---------------------
# ELO-BERECHNUNG
# ---------------------
def erwartung(a, b):
    return 1 / (1 + pow(10, (b - a) / 400))
 
def berechne_elo_aus_log(df_log):
    df = lade_spieler()
    alle = pd.concat([df.index.to_series(), df_log["Spieler A"], df_log["Spieler B"]]).dropna().unique()
    for s in alle:
        if s not in df.index:
            df.loc[s] = {"Elo": START_ELO, "Spiele": 0}
    df["Elo"] = START_ELO
    df["Spiele"] = 0
 
    for i, row in df_log.iterrows():
        a, b = row["Spieler A"], row["Spieler B"]
        la, lb = int(row["Legs A"]), int(row["Legs B"])
        avga, avgb = float(row["Avg A"]), float(row["Avg B"])
        ea, eb = df.loc[a, "Elo"], df.loc[b, "Elo"]
 
        exp_a = erwartung(ea, eb)
        exp_b = erwartung(eb, ea)
        sa = 1 if la > lb else 0
        sb = 1 - sa
 
        G = 1 + abs(la - lb) / 10
        D = min(1.3, 1 + abs(ea - eb) / 1200)
 
        if sa == 1:
            M_a = 1 + 0.3 * (avga - 50) / 50
        else:
            M_a = 1 - 0.3 * (avga - 50) / 50
 
        if sb == 1:
            M_b = 1 + 0.3 * (avgb - 50) / 50
        else:
            M_b = 1 - 0.3 * (avgb - 50) / 50
 
        delta_a = K_FAKTOR * G * D * (sa - exp_a) * M_a
        delta_b = K_FAKTOR * G * D * (sb - exp_b) * M_b
 
        df.loc[a, "Elo"] = round(ea + delta_a)
        df.loc[b, "Elo"] = round(eb + delta_b)
        df_log.at[i, "Elo A"] = round(delta_a)
        df_log.at[i, "Elo B"] = round(delta_b)
 
        df.loc[a, "Spiele"] += 1
        df.loc[b, "Spiele"] += 1
 
    speichere_spieler(df)
    speichere_log(df_log)
    return df, df_log
 
 
def log_spiel(a, b, la, lb, avga, avgb, spieltag):
    df_log = lade_log()
    df_log.loc[len(df_log)] = {
        "Datum": spieltag,
        "Spieler A": a,
        "Spieler B": b,
        "Legs A": la,
        "Legs B": lb,
        "Avg A": avga,
        "Avg B": avgb,
        "Elo A": 0,
        "Elo B": 0
    }
    speichere_log(df_log)
    return berechne_elo_aus_log(df_log)
 
# ---------------------
# FORMAT ELO-ANZEIGE
# ---------------------
def fmt(v):
    v = int(v)
    if v > 0:
        return f"<span style='color:green'>+{v} ▴</span>"
    elif v < 0:
        return f"<span style='color:red'>{v} ▾</span>"
    else:
        return "<span style='color:gray'>0</span>"
 
# ---------------------
# STREAMLIT START
# ---------------------
st.set_page_config(
    page_title="Bulls&Friends Ranking",
    layout="centered",
    initial_sidebar_state=st.session_state.get("sidebar_state", "expanded")
)
 
if "menu" not in st.session_state:
    st.session_state.menu = "Rangliste"
 
if "edit_index" not in st.session_state:
    st.session_state.edit_index = None
 
# ---------------------
# HEADER
# ---------------------
col1, col2 = st.columns([1, 5])
with col1:
    if os.path.exists("logo1.png"):
        st.image(Image.open("logo1.png"), width=300)
 
with col2:
    st.markdown("<h1 style='font-size:38px;'>Power - Ranking</h1>", unsafe_allow_html=True)
st.markdown("------")
 
 
# ---------------------
# MENÜ
# ---------------------
st.sidebar.markdown("## Menü")
 
def mbtn(name):
    if st.sidebar.button(name, use_container_width=True):
        st.session_state.menu = name
        st.session_state.edit_index = None
        st.session_state["sidebar_state"] = "collapsed"
        st.rerun()
 
menu_liste = [
    "Rangliste 🥇",
    "Spiel eintragen 🎯",
    "Vergangene Spiele 📄",
    "Spieler 👤",
    "Spieler anlegen ➕",
    "Auslosung 🎲",
    "Admin 🔐"
]
 
for m in menu_liste:
    mbtn(m)
 
menu = st.session_state.menu
 
# ---------------------
# RANGLISTE
# ---------------------
if "Rangliste" in menu:
    st.markdown("<h2 style='font-size:28px;'>🥇 Rangliste</h2>", unsafe_allow_html=True)
 
    df_log = lade_log()
    df, df_log = berechne_elo_aus_log(df_log)
    df = df.sort_values("Elo", ascending=False)
 
    rows = []
    for i, s in enumerate(df.index):
        letzte = df_log[(df_log["Spieler A"] == s) | (df_log["Spieler B"] == s)].tail(3)
        form = sum([r["Elo A"] if r["Spieler A"] == s else r["Elo B"] for _, r in letzte.iterrows()])
        elo = int(df.loc[s, "Elo"])
        spiele = int(df.loc[s, "Spiele"])
 
        if form > 0:
            punkte = f"{elo} <span style='color:green;font-size:70%;'>+{int(form)} ▲</span>"
        elif form < 0:
            punkte = f"{elo} <span style='color:red;font-size:70%;'>{int(form)} ▼</span>"
        else:
            punkte = str(elo)
 
        platz = f"<span style='color:gold;font-weight:bold'>{i+1}</span>" if i < 3 else str(i+1)
        rows.append({"Platz": platz, "Spieler": s, "Spiele": spiele, "Punkte": punkte})
 
    st.markdown(
        "<style>table td, table th { text-align: center !important; }</style>" +
        pd.DataFrame(rows).to_html(escape=False, index=False),
        unsafe_allow_html=True
    )
    
    st.markdown("------")
 
    st.markdown("""
    <div style="background-color:#f5f5f5; padding:15px; border-radius:10px; font-size:16px;">
    <h2 style='font-size:28px;'>ℹ️ Erklärung</h2> 
 
Das **Bulls&Friends Power-Ranking** ist ein **Elo-basiertes Punktesystem**, welches die Leistung der Spieler bei jedem offiziellen Spiel bewertet. Das System zieht **Ergebnis, Differenz, Average und Rangpunkte des Gegners** in Betracht und errechnet daraus **automatisch** eine Punktzahl, welche dann Einfluss auf die persönliche Rangpunktzahl nimmt.
 
 
***Ablauf:***
    Die Saison besteht aus **fix terminierten Spieltagen** (1-2x pro Monat).
   Alle an einem Spieltag anwesende Spieler bekommen **zufällig 4 Gegner zugelost**.
    Die Partien werden gespielt und **eingetragen**.
    Punktzahl und Platzierungen verändert sich je nach Leistung, Spieler **steigen und fallen im Ranking**.
    Zum Jahreswechsel wird die Rangliste durch einen Multiplikator zusammengezogen, wodurch die **Punkteabstände reduziert** werden.
    Diese Maßnahme zieht das Feld wieder enger zusammen, ohne die **relativen Leistungen der Spieler** vollständig zu verlieren.
 
 
***Vorteile einer hohen Ranglistenplatzierung:***
    Die **Top 16 Spieler** sind automatisch für die **Vereinsmeisterschaft** gesetzt. (Ab Platz 17 wird eine "Silber-VM" gespielt)
    Die **Top 4 Spieler** erhalten ab September das **Spielrecht bei Ligaspielen**, bei Ausfall rücken die Nächstplatzierten nach.
    Achtung: Diese Vorteile gelten nur für Spieler, die **mindestens 8 Spiele** absolviert haben (d.h. Teilnahme an 3 Spieltagen).
 
 
***Zusatz:***
    Es ist nicht nachteilig, wenn Spieler nur selten teilnehmen oder **zufällig starke Gegner zugelost bekommen**.
    Das Elo-System gleicht solche Effekte langfristig aus: Spieler, die **selten spielen, behalten ihre Punkte**, Niederlagen gegen starke Spieler werden **nicht zu sehr** bestraft und jeder hat die Chance, durch gute Leistungen **aufzusteigen**.
    
    """, unsafe_allow_html=True)
 
 
# ---------------------
# SPIEL EINTRAGEN
# ---------------------
elif "Spiel eintragen" in menu:
    st.subheader("🎯 Spiel eintragen")
    pw = st.text_input("Passwort", type="password")
 
    if pw == PASSWORT:
        df_spieler = list(lade_spieler().index)
 
        with st.form("spiel_form"):
            a = st.selectbox("Spieler A", df_spieler)
            b = st.selectbox("Spieler B", df_spieler)
            legs_a = st.number_input("Legs A", min_value=0, step=1)
            legs_b = st.number_input("Legs B", min_value=0, step=1)
            avg_a = st.number_input("Average A", min_value=0.0, value=50.0, step=0.1)
            avg_b = st.number_input("Average B", min_value=0.0, value=50.0, step=0.1)
            spieltag = st.text_input("Spieltag (z.B. 3)")
 
            submitted = st.form_submit_button("Match eintragen")
 
            if submitted:
                if a != b:
                    df, df_log = log_spiel(a, b, legs_a, legs_b, avg_a, avg_b, spieltag)
 
                    last = df_log.iloc[-1]
                    elo_a = int(last["Elo A"])
                    elo_b = int(last["Elo B"])
 
                    st.success(f"{a} {legs_a}:{legs_b} {b} eingetragen! (Avg: {avg_a}/{avg_b})")
                    st.markdown("### Elo-Veränderung")
                    st.markdown(f"{fmt(elo_a)} | {fmt(elo_b)}", unsafe_allow_html=True)
                else:
                    st.error("Bitte zwei unterschiedliche Spieler auswählen!")
 
# ---------------------
# VERGANGENE SPIELE + BEARBEITEN
# ---------------------
elif "Vergangene Spiele" in menu:
    st.subheader("📄 Vergangene Spiele")
 
    df_log = lade_log()
 
    if "edit_index" not in st.session_state:
        st.session_state.edit_index = None
 
    if df_log.empty:
        st.info("Noch keine Spiele eingetragen.")
    else:
 
        for i, row in df_log.iterrows():
            col1, col2, col3 = st.columns([5, 2, 1])
 
            def fmt_elo(v):
                v = int(v)
                if v > 0:
                    return f"<span style='color:green'>+{v} ▲</span>"
                elif v < 0:
                    return f"<span style='color:red'>{v} ▼</span>"
                else:
                    return "<span style='color:gray'>0</span>"
 
            with col1:
                st.markdown(
                    f"**Spieltag {row['Datum']}** — "
                    f"{row['Spieler A']} {row['Legs A']}:{row['Legs B']} {row['Spieler B']} "
                    f"(Avg {row['Avg A']} / {row['Avg B']})"
                )
 
            with col2:
                st.markdown(
                    f"{fmt_elo(row['Elo A'])} | {fmt_elo(row['Elo B'])}",
                    unsafe_allow_html=True
                )
 
            with col3:
                row_id = int(row["id"]) if "id" in df_log.columns else i
                if st.button("🛠", key=f"edit_{row_id}"):
                    st.session_state.edit_index = row_id
                    st.rerun()
 
        if st.session_state.edit_index is not None:
 
            st.markdown("---")
            st.subheader("🛠 Spiel bearbeiten")
 
            idx = st.session_state.edit_index
            df_log = lade_log()
 
            if "id" in df_log.columns:
                row = df_log[df_log["id"] == idx].iloc[0]
            else:
                row = df_log.loc[idx]
 
            pw = st.text_input("Admin-Passwort", type="password")
 
            if pw == PASSWORT:
 
                spieler = list(lade_spieler().index)
 
                with st.form("edit_form"):
 
                    a = st.selectbox("Spieler A", spieler, index=spieler.index(row["Spieler A"]))
                    b = st.selectbox("Spieler B", spieler, index=spieler.index(row["Spieler B"]))
                    la = st.number_input("Legs A", min_value=0, step=1, value=int(row["Legs A"]))
                    lb = st.number_input("Legs B", min_value=0, step=1, value=int(row["Legs B"]))
                    avga = st.number_input("Average A", min_value=0.0, step=0.1, value=float(row["Avg A"]))
                    avgb = st.number_input("Average B", min_value=0.0, step=0.1, value=float(row["Avg B"]))
                    spieltag = st.text_input("Spieltag", value=str(row["Datum"]))
                    save = st.form_submit_button("💾 Änderungen speichern")
                    delete = st.form_submit_button("🗑 Spiel löschen")
 
                if save:
                    sb = get_supabase()
                    sb.table("spiele_log").update({
                        "datum": spieltag,
                        "spieler_a": a,
                        "spieler_b": b,
                        "legs_a": int(la),
                        "legs_b": int(lb),
                        "avg_a": float(avga),
                        "avg_b": float(avgb)
                    }).eq("id", idx).execute()
                    berechne_elo_aus_log(lade_log())
                    st.success("Spiel aktualisiert!")
                    st.session_state.edit_index = None
                    st.rerun()
 
                if delete:
                    sb = get_supabase()
                    sb.table("spiele_log").delete().eq("id", idx).execute()
                    berechne_elo_aus_log(lade_log())
                    st.success("Spiel gelöscht!")
                    st.session_state.edit_index = None
                    st.rerun()
 
 
# ---------------------
# SPIELER
# ---------------------
elif "Spieler 👤" in menu:
    st.subheader("👤 Spieler")
 
    df_spieler = list(lade_spieler().index)
    gew = st.selectbox("Spieler auswählen", df_spieler)
 
    df_log = lade_log()
    df, df_log = berechne_elo_aus_log(df_log)
 
    spiele = df_log[(df_log["Spieler A"] == gew) | (df_log["Spieler B"] == gew)]
 
    siege = sum(
        ((spiele["Spieler A"] == gew) & (spiele["Legs A"] > spiele["Legs B"])) |
        ((spiele["Spieler B"] == gew) & (spiele["Legs B"] > spiele["Legs A"]))
    )
 
    niederlagen = len(spiele) - siege
 
    leg_diff = sum(
        spiele.apply(
            lambda r: r["Legs A"] - r["Legs B"] if r["Spieler A"] == gew
            else r["Legs B"] - r["Legs A"], axis=1
        )
    )
 
    gesamt_avg = (
        sum(spiele.apply(lambda r: r["Avg A"] if r["Spieler A"] == gew else r["Avg B"], axis=1)) / len(spiele)
        if len(spiele) > 0 else 0
    )
 
    elo = (
        sum(spiele.apply(lambda r: r["Elo A"] if r["Spieler A"] == gew else r["Elo B"], axis=1))
        if len(spiele) > 0 else START_ELO
    )
 
    st.write(f"Spiele: {len(spiele)}, Siege: {siege}, Niederlagen: {niederlagen}")
    st.write(f"Leg-Differenz: {leg_diff}, Gesamtaverage: {round(gesamt_avg, 2)}, Elo-Punkte: {elo}")
 
# ---------------------
# SPIELER ANLEGEN
# ---------------------
elif "Spieler anlegen ➕" in menu:
    st.subheader("➕ Spieler anlegen")
 
    pw = st.text_input("Passwort", type="password", key="spieler")
 
    if pw == PASSWORT:
        df = lade_spieler()
 
        with st.form("spieler_form"):
            name = st.text_input("Spielername")
            submitted = st.form_submit_button("Spieler anlegen")
 
            if submitted:
                if name.strip() != "" and name.strip() not in df.index:
                    df.loc[name.strip()] = {"Elo": START_ELO, "Spiele": 0}
                    speichere_spieler(df)
                    st.success(f"Spieler {name.strip()} angelegt!")
                else:
                    st.error("Ungültiger oder bereits existierender Name.")
 
# ---------------------
# AUSLOSUNG
# ---------------------
elif "Auslosung 🎲" in menu:
    st.subheader("🎲 Spieltags-Auslosung")
 
    df_spieler = list(lade_spieler().index)
 
    st.markdown("### Anwesende Spieler auswählen")
    anwesend = st.multiselect("Spieler", df_spieler)
 
    gegner_anzahl = st.slider(
        "Anzahl Gegner pro Spieler",
        min_value=3,
        max_value=5,
        value=4
    )
 
    import random
 
    def auslosen(spieler, gegner):
        if len(spieler) < gegner + 1:
            return None, None
 
        n = len(spieler)
        ein_extra = (n * gegner) % 2 != 0
 
        for _ in range(5000):
            paarungen = {s: set() for s in spieler}
            extra_spieler = random.choice(spieler) if ein_extra else None
 
            for s in spieler:
                limit = gegner + 1 if s == extra_spieler else gegner
                moeglich = [x for x in spieler if x != s and x not in paarungen[s]]
                random.shuffle(moeglich)
 
                for g in moeglich:
                    g_limit = gegner + 1 if g == extra_spieler else gegner
                    if len(paarungen[s]) < limit and len(paarungen[g]) < g_limit:
                        paarungen[s].add(g)
                        paarungen[g].add(s)
 
            if all(
                len(paarungen[s]) == (gegner + 1 if s == extra_spieler else gegner)
                for s in spieler
            ):
                return paarungen, extra_spieler
 
        return None, None
 
    if st.button("🎯 Auslosung starten"):
        if len(anwesend) < 4:
            st.error("Mindestens 4 Spieler erforderlich.")
        else:
            ergebnis, extra_spieler = auslosen(anwesend, gegner_anzahl)
 
            if ergebnis is None:
                st.error("Keine gültige Auslosung möglich – bitte andere Gegneranzahl oder Spieleranzahl wählen.")
            else:
                st.success("Auslosung erfolgreich!")
 
                if extra_spieler:
                    st.info(f"⚠️ Ungerade Spieleranzahl: **{extra_spieler}** bekommt {gegner_anzahl + 1} Gegner statt {gegner_anzahl}.")
 
                st.markdown("## 📋 Paarungen")
                for s in sorted(ergebnis.keys()):
                    gegner_liste = ", ".join(sorted(ergebnis[s]))
                    anzahl = len(ergebnis[s])
                    if s == extra_spieler:
                        st.markdown(f"**{s}** spielt gegen: {gegner_liste} ⚠️ ({anzahl} Spiele)")
                    else:
                        st.markdown(f"**{s}** spielt gegen: {gegner_liste}")
 
 
# ---------------------
# ADMIN
# ---------------------
elif "Admin 🔐" in menu:
    st.subheader("🔐 Admin")
 
    pw = st.text_input("Passwort", type="password", key="admin")
 
    if pw == PASSWORT:
        df = lade_spieler()
 
        st.markdown("### Saison Multiplikator (Abstände zusammenziehen)")
        faktor = st.slider("Multiplikator", 0.1, 1.0, 0.5, 0.05)
 
        preview = df.copy()
        preview["Neu"] = 1000 + ((preview["Elo"] - 1000) * faktor)
 
        st.dataframe(preview[["Elo", "Neu"]].round(0))
 
        if st.button("Abschließend übernehmen"):
            df["Elo"] = preview["Neu"].round(0)
            speichere_spieler(df)
            st.success("Punkteabstände übernommen!")
 




