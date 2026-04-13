import streamlit as st
import pandas as pd
import os
import math
from math import pow
from datetime import datetime
from PIL import Image
from supabase import create_client
import random
import plotly.express as px
import plotly.graph_objects as go
 
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
@st.cache_data(ttl=30)
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
    lade_spieler.clear()
 
@st.cache_data(ttl=30)
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
    lade_log.clear()
 
def insert_spiel(datum, a, b, la, lb, avga, avgb):
    sb = get_supabase()
    sb.table("spiele_log").insert({
        "datum": datum,
        "spieler_a": a,
        "spieler_b": b,
        "legs_a": int(la),
        "legs_b": int(lb),
        "avg_a": float(avga),
        "avg_b": float(avgb),
        "elo_a": 0,
        "elo_b": 0
    }).execute()
    lade_log.clear()
 
# ---------------------
# AKTIVER SPIELPLAN IN SUPABASE (für geräteübergreifende Sichtbarkeit)
# ---------------------
def lade_spielplan_db():
    """Lädt den aktiven Spielplan aus Supabase. Gibt None zurück wenn keiner existiert."""
    try:
        sb = get_supabase()
        res = sb.table("aktiver_spielplan").select("*").eq("id", 1).execute()
        if not res.data:
            return None
        row = res.data[0]
        spielplan = row["spielplan"] if isinstance(row["spielplan"], list) else []
        ergebnisse_raw = row.get("ergebnisse") or {}
        ergebnisse = {int(k): v for k, v in ergebnisse_raw.items()}
        locked_raw = row.get("locked") or []
        locked = [int(x) for x in locked_raw]
        reihenfolge_raw = row.get("reihenfolge") or list(range(len(spielplan)))
        reihenfolge = [int(x) for x in reihenfolge_raw]
        return {
            "spielplan": spielplan,
            "spieltag": row.get("spieltag", ""),
            "extra_spieler": row.get("extra_spieler"),
            "ergebnisse": ergebnisse,
            "locked": locked,
            "reihenfolge": reihenfolge
        }
    except Exception as e:
        st.warning(f"Spielplan konnte nicht geladen werden: {e}")
        return None
 
def speichere_spielplan_db(spielplan, spieltag, extra_spieler, ergebnisse, locked, reihenfolge):
    """Speichert den aktiven Spielplan in Supabase (upsert auf id=1)."""
    try:
        sb = get_supabase()
        ergebnisse_str = {str(k): v for k, v in ergebnisse.items()}
        sb.table("aktiver_spielplan").upsert({
            "id": 1,
            "spielplan": spielplan,
            "spieltag": str(spieltag),
            "extra_spieler": extra_spieler,
            "ergebnisse": ergebnisse_str,
            "locked": [int(x) for x in locked],
            "reihenfolge": [int(x) for x in reihenfolge]
        }).execute()
    except Exception as e:
        st.error(f"Fehler beim Speichern des Spielplans: {e}")
 
def loesche_spielplan_db():
    """Löscht den aktiven Spielplan aus Supabase."""
    try:
        sb = get_supabase()
        sb.table("aktiver_spielplan").delete().eq("id", 1).execute()
    except Exception as e:
        st.error(f"Fehler beim Löschen des Spielplans: {e}")
 
# ---------------------
# ELO-BERECHNUNG
# ---------------------
def erwartung(a, b):
    return 1 / (1 + pow(10, (b - a) / 400))
 
def _elo_kern(df_spieler, df_log):
    df = df_spieler.copy()
    alle = pd.concat([df.index.to_series(), df_log["Spieler A"], df_log["Spieler B"]]).dropna().unique()
    for s in alle:
        if s not in df.index:
            df.loc[s] = {"Elo": START_ELO, "Spiele": 0}
    df["Elo"] = START_ELO
    df["Spiele"] = 0
    df_log = df_log.copy()
 
    for i, row in df_log.iterrows():
        a, b = row["Spieler A"], row["Spieler B"]
        la, lb = int(row["Legs A"]), int(row["Legs B"])
        avga, avgb = float(row["Avg A"]), float(row["Avg B"])
        ea, eb = df.loc[a, "Elo"], df.loc[b, "Elo"]
 
        exp_a = erwartung(ea, eb)
        exp_b = erwartung(eb, ea)
        sa = 1 if la > lb else 0
        sb_val = 1 - sa
 
        G = 1 + abs(la - lb) / 10
        D = min(1.3, 1 + abs(ea - eb) / 1200)
        M_a = 1 + 0.3*(avga-50)/50 if sa==1 else 1 - 0.3*(avga-50)/50
        M_b = 1 + 0.3*(avgb-50)/50 if sb_val==1 else 1 - 0.3*(avgb-50)/50
 
        delta_a = K_FAKTOR * G * D * (sa - exp_a) * M_a
        delta_b = K_FAKTOR * G * D * (sb_val - exp_b) * M_b
 
        df.loc[a, "Elo"] = round(ea + delta_a)
        df.loc[b, "Elo"] = round(eb + delta_b)
        df_log.at[i, "Elo A"] = round(delta_a)
        df_log.at[i, "Elo B"] = round(delta_b)
        df.loc[a, "Spiele"] += 1
        df.loc[b, "Spiele"] += 1
 
    return df, df_log
 
def berechne_elo_nur_lesen(df_log):
    df_spieler = lade_spieler()
    return _elo_kern(df_spieler, df_log)
 
def berechne_elo_aus_log(df_log):
    df_spieler = lade_spieler()
    df, df_log_neu = _elo_kern(df_spieler, df_log)
    speichere_spieler(df)
    speichere_log(df_log_neu)
    return df, df_log_neu
 
def log_spiel(a, b, la, lb, avga, avgb, spieltag):
    insert_spiel(spieltag, a, b, la, lb, avga, avgb)
    df_log = lade_log()
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
 
def fmt_elo(v):
    v = int(v)
    if v > 0:
        return f"<span style='color:green'>+{v} ▲</span>"
    elif v < 0:
        return f"<span style='color:red'>{v} ▼</span>"
    else:
        return "<span style='color:gray'>0</span>"
 
# ---------------------
# ELO-VERLAUF BERECHNEN
# ---------------------
def berechne_elo_verlauf(df_log):
    if df_log.empty:
        return pd.DataFrame()
 
    alle_spieler = pd.concat([df_log["Spieler A"], df_log["Spieler B"]]).unique()
    spieltage = sorted(df_log["Datum"].astype(str).unique(), key=lambda x: (len(x), x))
 
    elo_aktuell = {s: START_ELO for s in alle_spieler}
    verlauf = {"Spieltag": ["Start"] + spieltage}
    for s in alle_spieler:
        verlauf[s] = [START_ELO]
 
    for st_nr in spieltage:
        spiele = df_log[df_log["Datum"].astype(str) == st_nr]
        for _, row in spiele.iterrows():
            a, b = row["Spieler A"], row["Spieler B"]
            elo_aktuell[a] = elo_aktuell.get(a, START_ELO) + int(row["Elo A"])
            elo_aktuell[b] = elo_aktuell.get(b, START_ELO) + int(row["Elo B"])
        for s in alle_spieler:
            verlauf[s].append(elo_aktuell.get(s, START_ELO))
 
    return pd.DataFrame(verlauf)
 
# ---------------------
# SPIELPLAN ERSTELLEN
# ---------------------
def erstelle_spielplan(paarungen):
    spiele = []
    gesehen = set()
    for s, gegner_set in paarungen.items():
        for g in gegner_set:
            key = tuple(sorted([s, g]))
            if key not in gesehen:
                gesehen.add(key)
                spiele.append(list(key))
 
    for _ in range(10000):
        random.shuffle(spiele)
        gueltig = True
        zuletzt = set()
        for spiel in spiele:
            if zuletzt & set(spiel):
                gueltig = False
                break
            zuletzt = set(spiel)
        if gueltig:
            return spiele
 
    return spiele
 
# ---------------------
# AUSLOSUNG FUNKTION
# ---------------------
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
 
# ---------------------
# SPIELTAG ZUSAMMENFASSUNG
# ---------------------
def zeige_spieltag_zusammenfassung(spieltag_nr, df_log_gesamt):
    spiele = df_log_gesamt[df_log_gesamt["Datum"].astype(str) == str(spieltag_nr)]
    if spiele.empty:
        st.warning("Keine Spiele für diesen Spieltag gefunden.")
        return
 
    elo_changes = {}
    for _, row in spiele.iterrows():
        a, b = row["Spieler A"], row["Spieler B"]
        elo_changes[a] = elo_changes.get(a, 0) + int(row["Elo A"])
        elo_changes[b] = elo_changes.get(b, 0) + int(row["Elo B"])
 
    sorted_elo = sorted(elo_changes.items(), key=lambda x: x[1], reverse=True)
    gewinner = sorted_elo[:3]
    verlierer = sorted_elo[-3:][::-1]
 
    avgs = []
    for _, row in spiele.iterrows():
        avgs.append((row["Spieler A"], float(row["Avg A"]), row["Spieler B"]))
        avgs.append((row["Spieler B"], float(row["Avg B"]), row["Spieler A"]))
    avgs.sort(key=lambda x: x[1], reverse=True)
    avg_king = avgs[0] if avgs else None
 
    df_log_vorher = df_log_gesamt[df_log_gesamt["Datum"].astype(str) < str(spieltag_nr)]
    df_elo_vorher = {}
    for name in pd.concat([df_log_gesamt["Spieler A"], df_log_gesamt["Spieler B"]]).unique():
        df_elo_vorher[name] = START_ELO
    for _, row in df_log_vorher.iterrows():
        a, b = row["Spieler A"], row["Spieler B"]
        df_elo_vorher[a] = df_elo_vorher.get(a, START_ELO) + int(row["Elo A"])
        df_elo_vorher[b] = df_elo_vorher.get(b, START_ELO) + int(row["Elo B"])
 
    ueberraschungen = []
    for _, row in spiele.iterrows():
        a, b = row["Spieler A"], row["Spieler B"]
        la, lb = int(row["Legs A"]), int(row["Legs B"])
        if la == lb:
            continue
        gew_s = a if la > lb else b
        ver_s = b if la > lb else a
        elo_g = df_elo_vorher.get(gew_s, START_ELO)
        elo_v = df_elo_vorher.get(ver_s, START_ELO)
        diff = elo_v - elo_g
        if diff > 0:
            ueberraschungen.append((gew_s, ver_s, diff, la, lb))
    ueberraschungen.sort(key=lambda x: x[2], reverse=True)
    groesste_ueberraschung = ueberraschungen[0] if ueberraschungen else None
 
    alle_avgs = list(spiele["Avg A"].astype(float)) + list(spiele["Avg B"].astype(float))
    gesamtaverage = round(sum(alle_avgs) / len(alle_avgs), 2) if alle_avgs else 0
 
    st.markdown(f"""
    <div style='padding:20px 0 16px 0;border-bottom:2px solid #e0e0e0;margin-bottom:24px;'>
        <h2 style='margin:0 0 8px 0;font-size:28px;font-weight:700;letter-spacing:0.5px;'>Spieltag {spieltag_nr}</h2>
        <div style='display:flex;gap:32px;'>
            <span style='color:#555;font-size:14px;'>{len(spiele)} Spiele ausgetragen</span>
            <span style='color:#555;font-size:14px;'>Ø Average: <strong>{gesamtaverage}</strong></span>
        </div>
    </div>
    """, unsafe_allow_html=True)
 
    col1, col2 = st.columns(2)
 
    with col1:
        st.markdown("<span style='font-size:18px;font-weight:bold;text-decoration:underline;'>Spieltagsgewinner</span>", unsafe_allow_html=True)
        medals = ["🥇", "🥈", "🥉"]
        for idx, (name, delta) in enumerate(gewinner):
            sign = f"+{delta}" if delta >= 0 else str(delta)
            color = "green" if delta >= 0 else "red"
            st.markdown(
                f"{medals[idx]} {name} &nbsp; <span style='color:{color};font-weight:bold;'>{sign}</span>",
                unsafe_allow_html=True
            )
 
    with col2:
        st.markdown("<span style='font-size:18px;font-weight:bold;text-decoration:underline;'>Spieltagsverlierer</span>", unsafe_allow_html=True)
        for idx, (name, delta) in enumerate(verlierer):
            st.markdown(
                f"#{idx+1} {name} &nbsp; <span style='color:red;font-weight:bold;'>{delta}</span>",
                unsafe_allow_html=True
            )
 
    st.markdown("---")
    col3, col4 = st.columns(2)
 
    with col3:
        if avg_king:
            st.markdown("<span style='font-size:18px;font-weight:bold;text-decoration:underline;'>Bestleistung</span>", unsafe_allow_html=True)
            for _, row in spiele.iterrows():
                if row["Spieler A"] == avg_king[0] and row["Spieler B"] == avg_king[2]:
                    ergebnis_str = f"{int(row['Legs A'])}:{int(row['Legs B'])}"
                    break
                elif row["Spieler B"] == avg_king[0] and row["Spieler A"] == avg_king[2]:
                    ergebnis_str = f"{int(row['Legs B'])}:{int(row['Legs A'])}"
                    break
            else:
                ergebnis_str = "–"
            st.markdown(f"{avg_king[0]} ({ergebnis_str} vs {avg_king[2]})")
            st.markdown(f"<span style='color:green;font-weight:bold;font-size:20px;'>{avg_king[1]:.1f} Avg</span>", unsafe_allow_html=True)
 
    with col4:
        st.markdown("<span style='font-size:18px;font-weight:bold;text-decoration:underline;'>Größte Überraschung</span>", unsafe_allow_html=True)
        if groesste_ueberraschung:
            gew_s, ver_s, diff, la, lb = groesste_ueberraschung
            st.markdown(f"{gew_s} ({la}:{lb} vs {ver_s})")
            st.markdown(f"<span style='color:green;font-weight:bold;font-size:20px;'>+{diff} Elo-Differenz</span>", unsafe_allow_html=True)
        else:
            st.markdown("Keine Underdog-Siege in diesem Spieltag.")
 
# ---------------------
# SPIELERPROFIL POPUP
# ---------------------
@st.dialog("Spielerprofil", width="large")
def zeige_spieler_popup(gew, df, df_log, rang_liste):
    spiele = df_log[(df_log["Spieler A"] == gew) | (df_log["Spieler B"] == gew)]
 
    siege = sum(
        ((spiele["Spieler A"] == gew) & (spiele["Legs A"] > spiele["Legs B"])) |
        ((spiele["Spieler B"] == gew) & (spiele["Legs B"] > spiele["Legs A"]))
    )
    niederlagen = len(spiele) - siege
    leg_diff = sum(spiele.apply(
        lambda r: r["Legs A"] - r["Legs B"] if r["Spieler A"] == gew else r["Legs B"] - r["Legs A"], axis=1))
    gesamt_avg = (
        sum(spiele.apply(lambda r: r["Avg A"] if r["Spieler A"] == gew else r["Avg B"], axis=1)) / len(spiele)
        if len(spiele) > 0 else 0
    )
    elo_aktuell = int(df.loc[gew, "Elo"])
    rang = rang_liste.index(gew) + 1
    siegquote = round(siege / len(spiele) * 100, 1) if len(spiele) > 0 else 0
    best_avg = max(spiele.apply(lambda r: r["Avg A"] if r["Spieler A"] == gew else r["Avg B"], axis=1)) if not spiele.empty else 0
 
    letzte5 = spiele.tail(5)
    form_str = ""
    for _, r in letzte5.iterrows():
        gewonnen = (r["Spieler A"] == gew and r["Legs A"] > r["Legs B"]) or \
                   (r["Spieler B"] == gew and r["Legs B"] > r["Legs A"])
        form_str += "🟢" if gewonnen else "🔴"
 
    st.markdown(f"""
    <div style='background:linear-gradient(135deg,#1a1a2e,#16213e);padding:24px;border-radius:12px;margin-bottom:20px;border:1px solid #2a3555;'>
        <div style='display:flex;justify-content:space-between;align-items:flex-start;'>
            <div>
                <div style='font-size:12px;letter-spacing:3px;text-transform:uppercase;color:#6b7fa3;margin-bottom:4px;'>Spielerprofil</div>
                <div style='font-size:32px;font-weight:900;color:#ffffff;letter-spacing:1px;'>{gew}</div>
                <div style='font-size:13px;color:#6b7fa3;margin-top:4px;'>Rang #{rang} · Form: {form_str if form_str else "–"}</div>
            </div>
            <div style='text-align:right;'>
                <div style='font-size:12px;color:#6b7fa3;letter-spacing:2px;text-transform:uppercase;'>Elo</div>
                <div style='font-size:44px;font-weight:900;color:#00aaff;line-height:1;'>{elo_aktuell}</div>
            </div>
        </div>
        <div style='display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-top:20px;'>
            <div style='text-align:center;'>
                <div style='font-size:20px;font-weight:700;color:#fff;'>{len(spiele)}</div>
                <div style='font-size:10px;color:#6b7fa3;letter-spacing:1px;text-transform:uppercase;margin-top:2px;'>Spiele</div>
            </div>
            <div style='text-align:center;'>
                <div style='font-size:20px;font-weight:700;color:#22c55e;'>{siege}</div>
                <div style='font-size:10px;color:#6b7fa3;letter-spacing:1px;text-transform:uppercase;margin-top:2px;'>Siege</div>
            </div>
            <div style='text-align:center;'>
                <div style='font-size:20px;font-weight:700;color:#ef4444;'>{niederlagen}</div>
                <div style='font-size:10px;color:#6b7fa3;letter-spacing:1px;text-transform:uppercase;margin-top:2px;'>Niederlagen</div>
            </div>
            <div style='text-align:center;'>
                <div style='font-size:20px;font-weight:700;color:#f59e0b;'>{siegquote}%</div>
                <div style='font-size:10px;color:#6b7fa3;letter-spacing:1px;text-transform:uppercase;margin-top:2px;'>Siegquote</div>
            </div>
            <div style='text-align:center;'>
                <div style='font-size:20px;font-weight:700;color:#fff;'>{round(gesamt_avg, 1)}</div>
                <div style='font-size:10px;color:#6b7fa3;letter-spacing:1px;text-transform:uppercase;margin-top:2px;'>Avg</div>
            </div>
        </div>
        <div style='display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:14px;padding-top:14px;border-top:1px solid #2a3555;'>
            <div style='text-align:center;'>
                <div style='font-size:16px;font-weight:700;color:#fff;'>{leg_diff:+d}</div>
                <div style='font-size:10px;color:#6b7fa3;letter-spacing:1px;text-transform:uppercase;margin-top:2px;'>Leg-Differenz</div>
            </div>
            <div style='text-align:center;'>
                <div style='font-size:16px;font-weight:700;color:#fff;'>{round(best_avg, 1)}</div>
                <div style='font-size:10px;color:#6b7fa3;letter-spacing:1px;text-transform:uppercase;margin-top:2px;'>Best Average</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
 
    if not df_log.empty:
        verlauf_df = berechne_elo_verlauf(df_log)
        if gew in verlauf_df.columns:
            st.markdown("**Elo-Verlauf**")
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=verlauf_df["Spieltag"], y=verlauf_df[gew],
                mode="lines+markers", name=gew,
                line=dict(color="#00aaff", width=3),
                marker=dict(size=8, color="#00aaff"),
                fill="tozeroy", fillcolor="rgba(0,170,255,0.08)"
            ))
            fig.add_hline(y=START_ELO, line_dash="dot", line_color="#444", opacity=0.5)
            fig.update_layout(
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                font_color="#aaa", height=220,
                margin=dict(l=0, r=0, t=8, b=0),
                xaxis=dict(showgrid=False, tickfont=dict(size=11)),
                yaxis=dict(showgrid=True, gridcolor="#1e2d45", tickfont=dict(size=11)),
                showlegend=False
            )
            st.plotly_chart(fig, use_container_width=True)
 
    if not spiele.empty:
        st.markdown("**Letzte Spiele**")
        for _, r in spiele.tail(8).iloc[::-1].iterrows():
            gewonnen = (r["Spieler A"] == gew and r["Legs A"] > r["Legs B"]) or \
                       (r["Spieler B"] == gew and r["Legs B"] > r["Legs A"])
            gegner = r["Spieler B"] if r["Spieler A"] == gew else r["Spieler A"]
            legs_gew = r["Legs A"] if r["Spieler A"] == gew else r["Legs B"]
            legs_geg = r["Legs B"] if r["Spieler A"] == gew else r["Legs A"]
            avg_gew = r["Avg A"] if r["Spieler A"] == gew else r["Avg B"]
            elo_d = int(r["Elo A"]) if r["Spieler A"] == gew else int(r["Elo B"])
            elo_str = f"+{elo_d}" if elo_d >= 0 else str(elo_d)
            farbe = "green" if gewonnen else "red"
            ergebnis = "Sieg" if gewonnen else "Niederlage"
            st.markdown(
                f"<span style='color:{farbe};font-weight:bold;'>{'▲' if gewonnen else '▼'} {ergebnis}</span> &nbsp; "
                f"vs **{gegner}** &nbsp; {int(legs_gew)}:{int(legs_geg)} &nbsp; "
                f"Avg {avg_gew:.1f} &nbsp; "
                f"<span style='color:{farbe};font-weight:bold;'>{elo_str}</span> &nbsp; "
                f"<span style='color:#888;font-size:12px;'>Spieltag {r['Datum']}</span>",
                unsafe_allow_html=True
            )
 
# ---------------------
# STREAMLIT START
# ---------------------
st.set_page_config(
    page_title="Bulls&Friends Ranking",
    layout="centered",
    initial_sidebar_state=st.session_state.get("sidebar_state", "expanded")
)
 
# ---------------------
# BACKSPACE-SCHUTZ (verhindert Browser-Rücknavigation)
# ---------------------
st.markdown("""
<script>
document.addEventListener('keydown', function(e) {
    if (e.key === 'Backspace') {
        var tag = e.target.tagName.toUpperCase();
        var editable = e.target.isContentEditable;
        if (tag !== 'INPUT' && tag !== 'TEXTAREA' && tag !== 'SELECT' && !editable) {
            e.preventDefault();
        }
    }
});
</script>
""", unsafe_allow_html=True)
 
if "menu" not in st.session_state:
    st.session_state.menu = "Rangliste"
if "edit_index" not in st.session_state:
    st.session_state.edit_index = None
if "letzter_spieltag" not in st.session_state:
    st.session_state.letzter_spieltag = None
if "zeige_zusammenfassung" not in st.session_state:
    st.session_state.zeige_zusammenfassung = False
if "zusammenfassung_spieltag" not in st.session_state:
    st.session_state.zusammenfassung_spieltag = None
if "ausgewaehlter_spieler" not in st.session_state:
    st.session_state.ausgewaehlter_spieler = None
if "spiel_submitted" not in st.session_state:
    st.session_state.spiel_submitted = False
 
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
    "Head-to-Head ⚔️",
    "Bestenlisten 🏅",
    "Spieler anlegen ➕",
    "Auslosung 🎲",
    "Spieltage 📊",
    "Turnier 🏆",
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
    df, df_log = berechne_elo_nur_lesen(df_log)
    df = df.sort_values("Elo", ascending=False)
    rang_liste = list(df.index)
 
    df_aktiv = df[df["Spiele"] > 0]
    df_inaktiv = df[df["Spiele"] == 0]
 
    table_rows = ""
    for i, s in enumerate(df_aktiv.index):
        letzte = df_log[(df_log["Spieler A"] == s) | (df_log["Spieler B"] == s)].tail(3)
        form = sum([r["Elo A"] if r["Spieler A"] == s else r["Elo B"] for _, r in letzte.iterrows()])
        elo = int(df_aktiv.loc[s, "Elo"])
        spiele_anz = int(df_aktiv.loc[s, "Spiele"])
        medal = ["🥇","🥈","🥉"][i] if i < 3 else f"{i+1}."
        if form > 0:
            form_html = f"<span style='color:green;font-size:12px;font-weight:600;'>+{int(form)}&nbsp;▲</span>"
        elif form < 0:
            form_html = f"<span style='color:red;font-size:12px;font-weight:600;'>{int(form)}&nbsp;▼</span>"
        else:
            form_html = "<span style='color:#aaa;font-size:12px;'>–</span>"
        table_rows += f"""<tr style='border-bottom:1px solid #eee;'>
            <td style='padding:10px 6px;width:38px;font-size:15px;'>{medal}</td>
            <td style='padding:10px 6px;font-size:15px;'>{s}</td>
            <td style='padding:10px 6px;width:68px;text-align:center;font-size:13px;color:#888;'>{spiele_anz}</td>
            <td style='padding:10px 8px;width:130px;text-align:right;white-space:nowrap;'>
                <span style='font-size:15px;font-weight:700;'>{elo}</span>
                <span style='display:inline-block;width:68px;text-align:right;font-size:12px;font-weight:600;'>{form_html}</span>
            </td>
        </tr>"""
 
    st.markdown(f"""
    <style>
    .rl-wrap{{width:100%;border-collapse:collapse;table-layout:fixed;}}
    .rl-wrap th{{font-size:11px;color:#888;font-weight:700;text-transform:uppercase;
        letter-spacing:1px;padding:6px;border-bottom:2px solid #e0e0e0;}}
    </style>
    <table class='rl-wrap'>
        <thead><tr>
            <th style='text-align:left;width:38px;'>#</th>
            <th style='text-align:left;'>Spieler</th>
            <th style='text-align:center;width:68px;'>Spiele</th>
            <th style='text-align:right;width:130px;padding-right:76px;'>Punkte</th>
        </tr></thead>
        <tbody>{table_rows}</tbody>
    </table>""", unsafe_allow_html=True)
 
    st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
    ausw = st.selectbox(
        "Spielerprofil",
        ["– Spieler auswählen –"] + list(df_aktiv.index),
        key="profil_select"
    )
    if ausw and ausw != "– Spieler auswählen –":
        zeige_spieler_popup(ausw, df, df_log, rang_liste)
 
    if not df_inaktiv.empty:
        if st.checkbox(f"Inaktive Spieler anzeigen ({len(df_inaktiv)})"):
            inaktiv_rows = "".join([
                f"<tr><td style='padding:8px 6px;color:#ccc;'>–</td>"
                f"<td style='padding:8px 6px;color:#aaa;'>{s}</td>"
                f"<td style='padding:8px 6px;width:68px;text-align:center;color:#ccc;'>0</td>"
                f"<td style='padding:8px 6px;width:130px;text-align:right;color:#ccc;padding-right:76px;'>{START_ELO}</td>"
                f"<td style='padding:8px 6px;'></td></tr>"
                for s in df_inaktiv.index
            ])
            st.markdown(f"<table class='rl-wrap'><tbody>{inaktiv_rows}</tbody></table>",
                        unsafe_allow_html=True)
 
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
            with col1:
                st.markdown(
                    f"**Spieltag {row['Datum']}** — "
                    f"{row['Spieler A']} {row['Legs A']}:{row['Legs B']} {row['Spieler B']} "
                    f"(Avg {row['Avg A']} / {row['Avg B']})"
                )
            with col2:
                st.markdown(f"{fmt_elo(row['Elo A'])} | {fmt_elo(row['Elo B'])}", unsafe_allow_html=True)
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
                        "datum": spieltag, "spieler_a": a, "spieler_b": b,
                        "legs_a": int(la), "legs_b": int(lb),
                        "avg_a": float(avga), "avg_b": float(avgb)
                    }).eq("id", idx).execute()
                    lade_log.clear()
                    berechne_elo_aus_log(lade_log())
                    st.success("Spiel aktualisiert!")
                    st.session_state.edit_index = None
                    st.rerun()
 
                if delete:
                    sb = get_supabase()
                    sb.table("spiele_log").delete().eq("id", idx).execute()
                    lade_log.clear()
                    berechne_elo_aus_log(lade_log())
                    st.success("Spiel gelöscht!")
                    st.session_state.edit_index = None
                    st.rerun()
 
# ---------------------
# HEAD-TO-HEAD
# ---------------------
elif "Head-to-Head" in menu:
    st.subheader("⚔️ Head-to-Head")
 
    df_log = lade_log()
    df_spieler_liste = list(lade_spieler().index)
 
    col1, col2 = st.columns(2)
    with col1:
        p1 = st.selectbox("Spieler 1", df_spieler_liste, key="h2h_p1")
    with col2:
        p2 = st.selectbox("Spieler 2", [s for s in df_spieler_liste if s != p1], key="h2h_p2")
 
    if p1 and p2:
        h2h = df_log[
            ((df_log["Spieler A"] == p1) & (df_log["Spieler B"] == p2)) |
            ((df_log["Spieler A"] == p2) & (df_log["Spieler B"] == p1))
        ]
 
        if h2h.empty:
            st.info(f"Noch keine Duelle zwischen {p1} und {p2}.")
        else:
            siege_p1 = sum(
                ((h2h["Spieler A"] == p1) & (h2h["Legs A"] > h2h["Legs B"])) |
                ((h2h["Spieler B"] == p1) & (h2h["Legs B"] > h2h["Legs A"]))
            )
            siege_p2 = len(h2h) - siege_p1
 
            avg_p1 = round(sum(h2h.apply(lambda r: r["Avg A"] if r["Spieler A"] == p1 else r["Avg B"], axis=1)) / len(h2h), 2)
            avg_p2 = round(sum(h2h.apply(lambda r: r["Avg A"] if r["Spieler A"] == p2 else r["Avg B"], axis=1)) / len(h2h), 2)
 
            legs_p1 = sum(h2h.apply(lambda r: r["Legs A"] if r["Spieler A"] == p1 else r["Legs B"], axis=1))
            legs_p2 = sum(h2h.apply(lambda r: r["Legs A"] if r["Spieler A"] == p2 else r["Legs B"], axis=1))
 
            elo_p1 = sum(h2h.apply(lambda r: int(r["Elo A"]) if r["Spieler A"] == p1 else int(r["Elo B"]), axis=1))
            elo_p2 = sum(h2h.apply(lambda r: int(r["Elo A"]) if r["Spieler A"] == p2 else int(r["Elo B"]), axis=1))
 
            st.markdown(f"""
            <div style='background:linear-gradient(135deg,#1a1a2e,#16213e);padding:20px;border-radius:12px;margin-bottom:20px;border:1px solid #2a3555;'>
                <div style='display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:16px;'>
                    <div style='text-align:center;'>
                        <div style='font-size:26px;font-weight:900;color:#fff;'>{p1}</div>
                        <div style='font-size:48px;font-weight:900;color:{"#22c55e" if siege_p1 > siege_p2 else "#ef4444" if siege_p1 < siege_p2 else "#fff"};line-height:1.1;'>{siege_p1}</div>
                        <div style='font-size:11px;color:#6b7fa3;letter-spacing:2px;text-transform:uppercase;'>Siege</div>
                    </div>
                    <div style='text-align:center;'>
                        <div style='font-size:13px;color:#6b7fa3;letter-spacing:2px;text-transform:uppercase;'>{len(h2h)} Duelle</div>
                    </div>
                    <div style='text-align:center;'>
                        <div style='font-size:26px;font-weight:900;color:#fff;'>{p2}</div>
                        <div style='font-size:48px;font-weight:900;color:{"#22c55e" if siege_p2 > siege_p1 else "#ef4444" if siege_p2 < siege_p1 else "#fff"};line-height:1.1;'>{siege_p2}</div>
                        <div style='font-size:11px;color:#6b7fa3;letter-spacing:2px;text-transform:uppercase;'>Siege</div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
 
            def stat_row(label, val1, val2, higher_is_better=True):
                besser1 = (val1 > val2) if higher_is_better else (val1 < val2)
                besser2 = (val2 > val1) if higher_is_better else (val2 < val1)
                c1, c2, c3 = st.columns([2, 2, 2])
                with c1:
                    col = "#22c55e" if besser1 else ("#ef4444" if besser2 else "#fff")
                    st.markdown(f"<div style='text-align:center;font-size:18px;font-weight:700;color:{col};'>{val1}</div>", unsafe_allow_html=True)
                with c2:
                    st.markdown(f"<div style='text-align:center;font-size:12px;color:#6b7fa3;letter-spacing:1px;text-transform:uppercase;padding-top:4px;'>{label}</div>", unsafe_allow_html=True)
                with c3:
                    col = "#22c55e" if besser2 else ("#ef4444" if besser1 else "#fff")
                    st.markdown(f"<div style='text-align:center;font-size:18px;font-weight:700;color:{col};'>{val2}</div>", unsafe_allow_html=True)
 
            stat_row("Legs gewonnen", int(legs_p1), int(legs_p2))
            stat_row("Elo-Gewinn gesamt", f"{elo_p1:+d}", f"{elo_p2:+d}", higher_is_better=True)
 
            st.markdown("---")
            st.markdown("#### Alle Duelle")
            for _, r in h2h.iloc[::-1].iterrows():
                gew_p = p1 if (
                    (r["Spieler A"] == p1 and r["Legs A"] > r["Legs B"]) or
                    (r["Spieler B"] == p1 and r["Legs B"] > r["Legs A"])
                ) else p2
                la = int(r["Legs A"]) if r["Spieler A"] == p1 else int(r["Legs B"])
                lb = int(r["Legs B"]) if r["Spieler A"] == p1 else int(r["Legs A"])
                st.markdown(
                    f"**Spieltag {r['Datum']}** — "
                    f"{p1} **{la}:{lb}** {p2} &nbsp; "
                    f"→ <span style='font-weight:bold;'>Sieg {gew_p}</span>",
                    unsafe_allow_html=True
                )
 
# ---------------------
# BESTENLISTEN
# ---------------------
elif "Bestenlisten" in menu:
    st.subheader("🏅 Bestenlisten")
 
    df_log = lade_log()
    df_sp, df_log = berechne_elo_nur_lesen(df_log)
 
    if df_log.empty:
        st.info("Noch keine Spiele eingetragen.")
    else:
        alle_spieler = list(df_sp.index)
 
        stats = {}
        for s in alle_spieler:
            spiele = df_log[(df_log["Spieler A"] == s) | (df_log["Spieler B"] == s)]
            if spiele.empty:
                continue
            siege = sum(
                ((spiele["Spieler A"] == s) & (spiele["Legs A"] > spiele["Legs B"])) |
                ((spiele["Spieler B"] == s) & (spiele["Legs B"] > spiele["Legs A"]))
            )
            avgs = spiele.apply(lambda r: r["Avg A"] if r["Spieler A"] == s else r["Avg B"], axis=1)
            stats[s] = {
                "spiele": len(spiele),
                "siege": int(siege),
                "niederlagen": len(spiele) - int(siege),
                "siegquote": round(siege / len(spiele) * 100, 1),
                "avg": round(avgs.mean(), 2),
                "best_avg": round(avgs.max(), 2),
                "elo": int(df_sp.loc[s, "Elo"])
            }
 
        tab1, tab2, tab3, tab4 = st.tabs(["🏆 Meiste Siege", "🎯 Höchster Average", "📈 Höchste Siegquote", "⚡ Elo-Rangliste"])
 
        with tab1:
            sieg_rank = sorted(stats.items(), key=lambda x: x[1]["siege"], reverse=True)
            medals = ["🥇", "🥈", "🥉"]
            for i, (name, s) in enumerate(sieg_rank):
                prefix = medals[i] if i < 3 else f"#{i+1}"
                st.markdown(
                    f"{prefix} **{name}** &nbsp; "
                    f"<span style='color:#22c55e;font-weight:bold;'>{s['siege']} Siege</span> &nbsp; "
                    f"<span style='color:#888;font-size:13px;'>aus {s['spiele']} Spielen ({s['siegquote']}%)</span>",
                    unsafe_allow_html=True
                )
 
        with tab2:
            avg_rank = sorted(stats.items(), key=lambda x: x[1]["avg"], reverse=True)
            for i, (name, s) in enumerate(avg_rank):
                prefix = medals[i] if i < 3 else f"#{i+1}"
                st.markdown(
                    f"{prefix} **{name}** &nbsp; "
                    f"<span style='color:#f59e0b;font-weight:bold;'>{s['avg']} Ø Avg</span> &nbsp; "
                    f"<span style='color:#888;font-size:13px;'>Best: {s['best_avg']}</span>",
                    unsafe_allow_html=True
                )
 
        with tab3:
            quote_rank = sorted(
                [(n, s) for n, s in stats.items() if s["spiele"] >= 3],
                key=lambda x: x[1]["siegquote"], reverse=True
            )
            st.caption("Nur Spieler mit mindestens 3 Spielen")
            for i, (name, s) in enumerate(quote_rank):
                prefix = medals[i] if i < 3 else f"#{i+1}"
                st.markdown(
                    f"{prefix} **{name}** &nbsp; "
                    f"<span style='color:#00aaff;font-weight:bold;'>{s['siegquote']}%</span> &nbsp; "
                    f"<span style='color:#888;font-size:13px;'>{s['siege']}S / {s['niederlagen']}N</span>",
                    unsafe_allow_html=True
                )
 
        with tab4:
            elo_rank = sorted(stats.items(), key=lambda x: x[1]["elo"], reverse=True)
            for i, (name, s) in enumerate(elo_rank):
                prefix = medals[i] if i < 3 else f"#{i+1}"
                diff = s["elo"] - START_ELO
                diff_str = f"+{diff}" if diff >= 0 else str(diff)
                farbe = "#22c55e" if diff >= 0 else "#ef4444"
                st.markdown(
                    f"{prefix} **{name}** &nbsp; "
                    f"<span style='color:#00aaff;font-weight:bold;'>{s['elo']}</span> &nbsp; "
                    f"<span style='color:{farbe};font-size:13px;'>({diff_str} seit Start)</span>",
                    unsafe_allow_html=True
                )
 
        st.markdown("---")
        st.markdown("#### Elo-Verlauf aller Spieler")
        verlauf_df = berechne_elo_verlauf(df_log)
        if not verlauf_df.empty:
            spieler_cols = [c for c in verlauf_df.columns if c != "Spieltag"]
            fig = go.Figure()
            farben = px.colors.qualitative.Set2
            for idx, s in enumerate(spieler_cols):
                fig.add_trace(go.Scatter(
                    x=verlauf_df["Spieltag"],
                    y=verlauf_df[s],
                    mode="lines+markers",
                    name=s,
                    line=dict(width=2, color=farben[idx % len(farben)]),
                    marker=dict(size=6)
                ))
            fig.add_hline(y=START_ELO, line_dash="dot", line_color="#444", opacity=0.4)
            fig.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font_color="#aaa",
                height=380,
                margin=dict(l=0, r=0, t=10, b=0),
                xaxis=dict(showgrid=False),
                yaxis=dict(showgrid=True, gridcolor="#1e2d45"),
                legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=12))
            )
            st.plotly_chart(fig, use_container_width=True)
 
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
 
    df_spieler_liste = list(lade_spieler().index)
 
    # Aktiven Spielplan aus Supabase laden (geräteübergreifend)
    db_plan = lade_spielplan_db()
 
    if db_plan is None:
        # ── Kein aktiver Spielplan ──
        if st.session_state.zeige_zusammenfassung and st.session_state.zusammenfassung_spieltag:
            st.success(f"✅ Spieltag {st.session_state.zusammenfassung_spieltag} wurde in die Rangliste übernommen!")
            st.markdown("---")
            st.markdown(f"### Spieltag {st.session_state.zusammenfassung_spieltag} – Zusammenfassung")
            zeige_spieltag_zusammenfassung(st.session_state.zusammenfassung_spieltag, lade_log())
            st.markdown("---")
            if st.button("Neue Auslosung starten"):
                st.session_state.zeige_zusammenfassung = False
                st.session_state.zusammenfassung_spieltag = None
                st.rerun()
        else:
            st.markdown("### Anwesende Spieler auswählen")
            anwesend = st.multiselect("Spieler", df_spieler_liste)
            gegner_anzahl = st.slider("Anzahl Gegner pro Spieler", min_value=3, max_value=5, value=4)
            spieltag_nr = st.text_input("Spieltag-Nummer (z.B. 3)")
 
            if st.button("🎯 Auslosung starten"):
                if len(anwesend) < 4:
                    st.error("Mindestens 4 Spieler erforderlich.")
                elif spieltag_nr.strip() == "":
                    st.error("Bitte Spieltag-Nummer eingeben.")
                else:
                    ergebnis, extra_spieler = auslosen(anwesend, gegner_anzahl)
                    if ergebnis is None:
                        st.error("Keine gültige Auslosung möglich – bitte andere Gegneranzahl oder Spieleranzahl wählen.")
                    else:
                        spielplan = erstelle_spielplan(ergebnis)
                        speichere_spielplan_db(
                            spielplan=spielplan,
                            spieltag=spieltag_nr.strip(),
                            extra_spieler=extra_spieler,
                            ergebnisse={},
                            locked=[],
                            reihenfolge=list(range(len(spielplan)))
                        )
                        st.rerun()
 
    else:
        # ── Aktiver Spielplan vorhanden ──
        spielplan  = db_plan["spielplan"]
        reihenfolge = db_plan["reihenfolge"]
        extra_spieler = db_plan["extra_spieler"]
        spieltag_nr   = db_plan["spieltag"]
        ergebnisse    = db_plan["ergebnisse"]   # {int_idx: {legs_a, legs_b, avg_a, avg_b}}
        locked        = set(db_plan["locked"])   # set of int indices
 
        st.markdown(f"### Spieltag {spieltag_nr}")
 
        if extra_spieler:
            st.info(f"⚠️ Ungerade Spieleranzahl: **{extra_spieler}** hat einen Gegner mehr.")
 
        pw = st.text_input("Passwort zum Eintragen", type="password", key="pw_spielplan")
 
        if pw == PASSWORT:
            # ── Admin-Ansicht: Eingabe + Sperren ──
            st.caption("🔒 sperrt ein eingetipptes Ergebnis (grau). 🔓 entsperrt es wieder. 🗑 entfernt das Spiel.")
 
            # Spaltenheader
            st.markdown("""
            <div style='display:grid;grid-template-columns:3fr 3fr 2fr 2fr 2fr 2fr 1fr 1fr;gap:6px;margin-bottom:2px;'>
                <div></div><div></div>
                <div style='grid-column:3/5;text-align:center;font-weight:bold;text-decoration:underline;font-size:13px;'>Legs</div>
                <div style='grid-column:5/7;text-align:center;font-weight:bold;text-decoration:underline;font-size:13px;'>Avg</div>
                <div></div><div></div>
            </div>
            """, unsafe_allow_html=True)
 
            ergebnisse_temp = {}
            aktion = None  # ("lock"|"unlock"|"delete", orig_idx)
 
            for orig_idx in reihenfolge:
                spiel  = spielplan[orig_idx]
                a, b   = spiel[0], spiel[1]
                vorher = ergebnisse.get(orig_idx, {})
                ist_gesperrt = orig_idx in locked
 
                if ist_gesperrt:
                    # Gesperrte Zeile: kompakt + grau, kein Input
                    la   = vorher.get("legs_a", 0)
                    lb   = vorher.get("legs_b", 0)
                    avga = vorher.get("avg_a", 50.0)
                    avgb = vorher.get("avg_b", 50.0)
                    cols = st.columns([6, 1, 1])
                    with cols[0]:
                        st.markdown(
                            f"<div style='background:#2a2a2a;border-radius:6px;padding:8px 10px;"
                            f"color:#888;font-size:14px;'>✅ <b>{a}</b> {int(la)}:{int(lb)} <b>{b}</b>"
                            f" &nbsp;·&nbsp; Avg {avga:.1f} / {avgb:.1f}</div>",
                            unsafe_allow_html=True
                        )
                    with cols[1]:
                        if st.button("🔓", key=f"unlock_{orig_idx}", help="Entsperren"):
                            aktion = ("unlock", orig_idx)
                    with cols[2]:
                        if st.button("🗑", key=f"del_{orig_idx}", help="Entfernen"):
                            aktion = ("delete", orig_idx)
                    ergebnisse_temp[orig_idx] = {"legs_a": la, "legs_b": lb, "avg_a": avga, "avg_b": avgb}
 
                else:
                    # Normale Eingabe-Zeile
                    cols = st.columns([3, 3, 2, 2, 2, 2, 1, 1])
                    with cols[0]:
                        st.markdown(f"**{a}**")
                    with cols[1]:
                        st.markdown(f"**{b}**")
                    with cols[2]:
                        la = st.number_input("", min_value=0, step=1,
                            value=vorher.get("legs_a", 0),
                            key=f"la_{orig_idx}", label_visibility="collapsed")
                    with cols[3]:
                        lb = st.number_input("", min_value=0, step=1,
                            value=vorher.get("legs_b", 0),
                            key=f"lb_{orig_idx}", label_visibility="collapsed")
                    with cols[4]:
                        avga = st.number_input("", min_value=0.0, step=0.1,
                            value=vorher.get("avg_a", 50.0),
                            key=f"avga_{orig_idx}", label_visibility="collapsed")
                    with cols[5]:
                        avgb = st.number_input("", min_value=0.0, step=0.1,
                            value=vorher.get("avg_b", 50.0),
                            key=f"avgb_{orig_idx}", label_visibility="collapsed")
                    with cols[6]:
                        if st.button("🔒", key=f"lock_{orig_idx}", help="Sperren"):
                            aktion = ("lock", orig_idx)
                    with cols[7]:
                        if st.button("🗑", key=f"del_{orig_idx}", help="Entfernen"):
                            aktion = ("delete", orig_idx)
                    ergebnisse_temp[orig_idx] = {"legs_a": la, "legs_b": lb, "avg_a": avga, "avg_b": avgb}
 
            # ── Aktionen verarbeiten (Lock / Unlock / Delete) ──
            if aktion is not None:
                art, idx_a = aktion
                if art == "lock":
                    neue_locked = list(locked) + [idx_a]
                    speichere_spielplan_db(spielplan, spieltag_nr, extra_spieler,
                                           ergebnisse_temp, neue_locked, reihenfolge)
                elif art == "unlock":
                    neue_locked = [x for x in locked if x != idx_a]
                    speichere_spielplan_db(spielplan, spieltag_nr, extra_spieler,
                                           ergebnisse_temp, neue_locked, reihenfolge)
                elif art == "delete":
                    neue_reihenfolge = [x for x in reihenfolge if x != idx_a]
                    neue_ergebnisse  = {k: v for k, v in ergebnisse_temp.items() if k != idx_a}
                    neue_locked      = [x for x in locked if x != idx_a]
                    speichere_spielplan_db(spielplan, spieltag_nr, extra_spieler,
                                           neue_ergebnisse, neue_locked, neue_reihenfolge)
                st.rerun()
 
            st.markdown("---")
 
            # Zwischenspeichern-Button (speichert aktuelle Eingaben ohne Abzuschließen)
            if st.button("💾 Ergebnisse zwischenspeichern"):
                speichere_spielplan_db(spielplan, spieltag_nr, extra_spieler,
                                       ergebnisse_temp, list(locked), reihenfolge)
                st.success("Zwischenstand gespeichert – andere Geräte sehen jetzt den aktuellen Stand.")
 
            st.markdown("---")
            col_submit, col_reset = st.columns([1, 1])
 
            with col_submit:
                if st.button("✅ In Rangliste übernehmen"):
                    # ── Schutz vor Doppel-Eintrag ──
                    df_log_check = lade_log()
                    if not df_log_check.empty and str(spieltag_nr) in df_log_check["Datum"].astype(str).values:
                        st.error(
                            f"⚠️ Spieltag {spieltag_nr} ist bereits in der Datenbank! "
                            f"Bitte unter 'Vergangene Spiele' prüfen."
                        )
                    else:
                        unvollstaendig = []
                        for orig_idx in reihenfolge:
                            e = ergebnisse_temp[orig_idx]
                            if e["legs_a"] == 0 and e["legs_b"] == 0:
                                spiel = spielplan[orig_idx]
                                unvollstaendig.append(f"{spiel[0]} vs {spiel[1]}")
 
                        if unvollstaendig:
                            st.warning(f"Noch keine Ergebnisse bei: {', '.join(unvollstaendig)}")
                        else:
                            for orig_idx in reihenfolge:
                                spiel = spielplan[orig_idx]
                                a_s, b_s = spiel[0], spiel[1]
                                e = ergebnisse_temp[orig_idx]
                                insert_spiel(spieltag_nr, a_s, b_s,
                                             e["legs_a"], e["legs_b"],
                                             e["avg_a"], e["avg_b"])
 
                            berechne_elo_aus_log(lade_log())
                            loesche_spielplan_db()
 
                            st.session_state.zeige_zusammenfassung = True
                            st.session_state.zusammenfassung_spieltag = spieltag_nr
                            st.rerun()
 
            with col_reset:
                if st.button("🗑 Spielplan verwerfen"):
                    loesche_spielplan_db()
                    st.rerun()
 
        else:
            # ── Nur-Lese-Ansicht (kein Passwort) ──
            st.info(f"📋 Aktiver Spielplan für **Spieltag {spieltag_nr}** — Passwort eingeben zum Bearbeiten.")
            st.markdown("---")
 
            for orig_idx in reihenfolge:
                spiel = spielplan[orig_idx]
                a, b  = spiel[0], spiel[1]
                vorher = ergebnisse.get(orig_idx, {})
                ist_gesperrt = orig_idx in locked
                la = vorher.get("legs_a", 0)
                lb = vorher.get("legs_b", 0)
 
                if ist_gesperrt:
                    ergebnis_str = f"→ **{int(la)}:{int(lb)}**"
                    st.markdown(
                        f"✅ ~~{a}~~ vs ~~{b}~~ &nbsp; {ergebnis_str}",
                        unsafe_allow_html=True
                    )
                elif la > 0 or lb > 0:
                    st.markdown(f"⏳ **{a}** vs **{b}** &nbsp; → {int(la)}:{int(lb)} *(nicht gesperrt)*")
                else:
                    st.markdown(f"⏳ **{a}** vs **{b}**")
 
            if st.button("🔄 Aktualisieren"):
                st.rerun()
 
# ---------------------
# SPIELTAGE
# ---------------------
elif "Spieltage 📊" in menu:
    st.subheader("📊 Spieltags-Übersicht")
 
    df_log = lade_log()
 
    if df_log.empty:
        st.info("Noch keine Spiele eingetragen.")
    else:
        spieltage = sorted(df_log["Datum"].astype(str).unique(), key=lambda x: (len(x), x))
 
        ausgewaehlter_spieltag = st.selectbox(
            "Spieltag auswählen",
            spieltage,
            index=len(spieltage) - 1,
            format_func=lambda x: f"Spieltag {x}"
        )
 
        zeige_spieltag_zusammenfassung(ausgewaehlter_spieltag, df_log)
 
# ---------------------
# TURNIER ROUTING
# ---------------------
elif "Turnier" in menu:
    turnier_main()

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
 
        st.markdown("---")
        st.markdown("### Elos neu berechnen")
        st.caption("Nützlich nach manuellen Änderungen in Supabase.")
        if st.button("🔄 Alle Elos neu berechnen"):
            berechne_elo_aus_log(lade_log())
            st.success("Elos wurden neu berechnet!")
 
        st.markdown("---")
        st.markdown("### Aktiven Spielplan zurücksetzen")
        st.caption("Löscht den aktuell laufenden Spielplan aus der Datenbank (z.B. nach Fehler).")
        if st.button("🗑 Spielplan in DB löschen"):
            loesche_spielplan_db()
            st.success("Spielplan gelöscht.")

# =====================================================
# TURNIER
# =====================================================
# Benötigt Supabase-Tabelle:
#   CREATE TABLE turniere (
#     id INTEGER PRIMARY KEY,
#     name TEXT NOT NULL DEFAULT 'Turnier',
#     status TEXT NOT NULL DEFAULT 'setup',
#     config JSONB NOT NULL DEFAULT '{}',
#     gruppen JSONB NOT NULL DEFAULT '{}',
#     gruppen_spiele JSONB NOT NULL DEFAULT '[]',
#     ko_spiele JSONB NOT NULL DEFAULT '[]',
#     qualifizierte JSONB NOT NULL DEFAULT '{}',
#     erstellt_am TIMESTAMPTZ DEFAULT NOW()
#   );
# =====================================================

TURNIER_BOARDS = 4

# --- Supabase-Hilfsfunktionen ---

@st.cache_data(ttl=10)
def lade_turnier():
    try:
        sb = get_supabase()
        res = sb.table("turniere").select("*").eq("id", 1).execute()
        if not res.data:
            return None
        row = res.data[0]
        return {
            "name": row.get("name", "Turnier"),
            "status": row.get("status", "setup"),
            "config": row.get("config") or {},
            "gruppen": row.get("gruppen") or {},
            "gruppen_spiele": row.get("gruppen_spiele") or [],
            "ko_spiele": row.get("ko_spiele") or [],
            "qualifizierte": row.get("qualifizierte") or {}
        }
    except Exception:
        return None

def speichere_turnier(data):
    sb = get_supabase()
    sb.table("turniere").upsert({
        "id": 1,
        "name": data.get("name", "Turnier"),
        "status": data.get("status", "setup"),
        "config": data.get("config", {}),
        "gruppen": data.get("gruppen", {}),
        "gruppen_spiele": data.get("gruppen_spiele", []),
        "ko_spiele": data.get("ko_spiele", []),
        "qualifizierte": data.get("qualifizierte", {})
    }).execute()
    lade_turnier.clear()

def loesche_turnier():
    sb = get_supabase()
    sb.table("turniere").delete().eq("id", 1).execute()
    lade_turnier.clear()

# --- Logik ---

def t_erstelle_gruppen(teilnehmer, n_gruppen):
    """Verteilt Teilnehmer zufällig auf Gruppen (Snake-Seeding)."""
    zuf = teilnehmer.copy()
    random.shuffle(zuf)
    buchstaben = "ABCDEFGHIJKLMNOP"
    gruppen = {buchstaben[i]: [] for i in range(n_gruppen)}
    for idx, t in enumerate(zuf):
        gruppen[buchstaben[idx % n_gruppen]].append(t)
    return gruppen

def t_erstelle_gruppenspiele(gruppen, boards):
    """Round-Robin-Spiele je Gruppe, interleaved für optimale Board-Verteilung."""
    gruppen_paarungen = {}
    for gk in sorted(gruppen.keys()):
        m = gruppen[gk]
        paarungen = []
        for i in range(len(m)):
            for j in range(i + 1, len(m)):
                paarungen.append((m[i], m[j]))
        gruppen_paarungen[gk] = paarungen

    spiele = []
    board_counter = 0
    max_p = max(len(p) for p in gruppen_paarungen.values()) if gruppen_paarungen else 0

    for round_idx in range(max_p):
        for gk in sorted(gruppen_paarungen.keys()):
            if round_idx < len(gruppen_paarungen[gk]):
                a, b = gruppen_paarungen[gk][round_idx]
                spiele.append({
                    "id": len(spiele),
                    "phase": "gruppe",
                    "gruppe": gk,
                    "spieler_a": a,
                    "spieler_b": b,
                    "board": (board_counter % boards) + 1,
                    "legs_a": None,
                    "legs_b": None,
                    "avg_a": None,
                    "avg_b": None,
                    "abgeschlossen": False
                })
                board_counter += 1
    return spiele

def t_berechne_tabelle(gruppe_key, mitglieder, gruppen_spiele):
    """Berechnet die Tabelle einer Gruppe."""
    tab = {t: {"Sp": 0, "S": 0, "N": 0, "+L": 0, "-L": 0, "Diff": 0,
               "Avg": 0.0, "Pts": 0, "_avgs": []} for t in mitglieder}
    for sp in gruppen_spiele:
        if sp.get("phase") != "gruppe" or sp.get("gruppe") != gruppe_key:
            continue
        if not sp.get("abgeschlossen"):
            continue
        a, b = sp["spieler_a"], sp["spieler_b"]
        la, lb = sp.get("legs_a") or 0, sp.get("legs_b") or 0
        avga, avgb = sp.get("avg_a") or 0.0, sp.get("avg_b") or 0.0
        if a not in tab or b not in tab:
            continue
        tab[a]["Sp"] += 1; tab[b]["Sp"] += 1
        tab[a]["+L"] += la; tab[a]["-L"] += lb
        tab[b]["+L"] += lb; tab[b]["-L"] += la
        tab[a]["_avgs"].append(avga); tab[b]["_avgs"].append(avgb)
        if la > lb:
            tab[a]["Pts"] += 2; tab[a]["S"] += 1; tab[b]["N"] += 1
        elif lb > la:
            tab[b]["Pts"] += 2; tab[b]["S"] += 1; tab[a]["N"] += 1
        else:
            tab[a]["Pts"] += 1; tab[b]["Pts"] += 1
    result = []
    for t, s in tab.items():
        s["Diff"] = s["+L"] - s["-L"]
        s["Avg"] = round(sum(s["_avgs"]) / len(s["_avgs"]), 1) if s["_avgs"] else 0.0
        result.append((t, s))
    result.sort(key=lambda x: (-x[1]["Pts"], -x[1]["Diff"], -x[1]["Avg"]))
    return result

def t_erstelle_ko_spiele(n_qualifizierte):
    """Erstellt leere KO-Matches für Single-Elimination-Bracket."""
    bracket_size = 1
    while bracket_size < n_qualifizierte:
        bracket_size *= 2
    total_r = int(math.log2(bracket_size))
    namen = ["Finale", "Halbfinale", "Viertelfinale", "Achtelfinale",
             "16tel-Finale", "32tel-Finale"]
    ko = []
    mid = 0
    for r in range(total_r):
        n_m = bracket_size // (2 ** (r + 1))
        name_idx = total_r - 1 - r
        rname = namen[name_idx] if name_idx < len(namen) else f"Runde {r + 1}"
        for m in range(n_m):
            ko.append({
                "id": mid, "runde_idx": r, "runde_name": rname, "match_nr": m,
                "spieler_a": None, "spieler_b": None, "board": None,
                "legs_a": None, "legs_b": None, "avg_a": None, "avg_b": None,
                "abgeschlossen": False, "sieger": None
            })
            mid += 1
    return ko

def t_get_qualifizierte(gruppen, gruppen_spiele, weiter_pro_gruppe):
    """Gibt die Qualifizierten in Seeding-Reihenfolge zurück."""
    positionen = {}
    for gk in sorted(gruppen.keys()):
        tab = t_berechne_tabelle(gk, gruppen[gk], gruppen_spiele)
        positionen[gk] = [name for name, _ in tab]
    qual = []
    for pos in range(weiter_pro_gruppe):
        for gk in sorted(gruppen.keys()):
            if pos < len(positionen[gk]):
                qual.append(positionen[gk][pos])
    return qual

def t_befuelle_ko_erste_runde(ko_spiele, qualifizierte, boards):
    """Befüllt die erste KO-Runde mit Qualifizierten (Seeded Snake-Bracket)."""
    if not ko_spiele:
        return ko_spiele
    max_r = max(s["runde_idx"] for s in ko_spiele)
    erste = sorted([s for s in ko_spiele if s["runde_idx"] == max_r],
                   key=lambda x: x["match_nr"])
    n = len(qualifizierte)
    n_slots = len(erste) * 2
    seeded = qualifizierte[:] + ["BYE"] * (n_slots - n)
    bc = 0
    for i, sp in enumerate(erste):
        s1 = seeded[i]
        s2 = seeded[n_slots - 1 - i]
        sp["spieler_a"] = s1
        sp["spieler_b"] = s2
        if s2 == "BYE":
            sp["abgeschlossen"] = True
            sp["sieger"] = s1
            sp["legs_a"] = 1
            sp["legs_b"] = 0
            sp["avg_a"] = 0.0
            sp["avg_b"] = 0.0
        else:
            sp["board"] = (bc % boards) + 1
            bc += 1
    return ko_spiele

def t_propagiere_sieger(ko_spiele, boards):
    """Trägt Sieger in die nächste KO-Runde ein und vergibt Boards."""
    if not ko_spiele:
        return ko_spiele
    max_r = max(s["runde_idx"] for s in ko_spiele)
    bc = sum(1 for s in ko_spiele if s.get("board") is not None)
    for r in range(max_r, 0, -1):
        runde = sorted([s for s in ko_spiele if s["runde_idx"] == r],
                       key=lambda x: x["match_nr"])
        naechste = sorted([s for s in ko_spiele if s["runde_idx"] == r - 1],
                          key=lambda x: x["match_nr"])
        for sp in runde:
            if not sp.get("abgeschlossen") or not sp.get("sieger"):
                continue
            nm = sp["match_nr"] // 2
            slot = sp["match_nr"] % 2
            for ns in naechste:
                if ns["match_nr"] == nm:
                    if slot == 0:
                        ns["spieler_a"] = sp["sieger"]
                    else:
                        ns["spieler_b"] = sp["sieger"]
                    if (ns.get("spieler_a") and ns.get("spieler_b")
                            and ns["board"] is None and not ns["abgeschlossen"]):
                        ns["board"] = (bc % boards) + 1
                        bc += 1
    return ko_spiele

def t_bracket_html(ko_spiele):
    """Rendert das KO-Bracket als HTML."""
    if not ko_spiele:
        return ""
    max_r = max(s["runde_idx"] for s in ko_spiele)
    n_first = len([s for s in ko_spiele if s["runde_idx"] == max_r])
    MATCH_H = 72
    total_h = max(n_first * MATCH_H, 120)

    css = """<style>
.brk{display:flex;gap:0;overflow-x:auto;padding:16px;background:#0a1020;border-radius:12px;align-items:stretch;}
.brk-col{display:flex;flex-direction:column;align-items:stretch;min-width:170px;}
.brk-col+.brk-col{margin-left:0;}
.brk-head{font-size:11px;color:#6b7fa3;text-transform:uppercase;letter-spacing:1px;
    text-align:center;padding:4px 8px;background:#1a2540;border-radius:3px;margin-bottom:8px;white-space:nowrap;}
.brk-matches{display:flex;flex-direction:column;justify-content:space-around;flex:1;}
.brk-match{display:flex;flex-direction:column;gap:2px;position:relative;}
.brk-board{font-size:10px;color:#4a5568;text-align:center;margin-bottom:1px;}
.brk-p{padding:5px 10px;background:#1e2d45;border-radius:4px;font-size:12px;
    color:#9bacc8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:160px;}
.brk-p.win{color:#22c55e;font-weight:700;}
.brk-p.tbd{color:#374151;font-style:italic;}
.brk-p.bye{color:#374151;text-decoration:line-through;}
.brk-connector{width:18px;display:flex;flex-direction:column;justify-content:space-around;
    align-self:stretch;position:relative;}
</style>"""

    def p_cls(name, is_win):
        if not name:
            return "tbd"
        if name == "BYE":
            return "bye"
        if is_win:
            return "win"
        return ""

    html = css + "<div class='brk'>"
    for r in range(max_r, -1, -1):
        runde_spiele = sorted([s for s in ko_spiele if s["runde_idx"] == r],
                               key=lambda x: x["match_nr"])
        rname = runde_spiele[0]["runde_name"] if runde_spiele else ""
        html += f"<div class='brk-col'><div class='brk-head'>{rname}</div>"
        html += f"<div class='brk-matches' style='height:{total_h}px;'>"
        for sp in runde_spiele:
            la = sp.get("legs_a")
            lb = sp.get("legs_b")
            done = sp.get("abgeschlossen", False)
            win_a = done and la is not None and lb is not None and la > lb
            win_b = done and la is not None and lb is not None and lb > la
            pa = sp.get("spieler_a") or "TBD"
            pb = sp.get("spieler_b") or "TBD"
            la_str = f" <small>({la})</small>" if done and la is not None else ""
            lb_str = f" <small>({lb})</small>" if done and lb is not None else ""
            board_h = (f"<div class='brk-board'>Board {sp['board']}</div>"
                       if sp.get("board") else "<div class='brk-board'>&nbsp;</div>")
            html += (f"<div class='brk-match'>{board_h}"
                     f"<div class='brk-p {p_cls(pa, win_a)}'>{pa}{la_str}</div>"
                     f"<div class='brk-p {p_cls(pb, win_b)}'>{pb}{lb_str}</div></div>")
        html += "</div></div>"
        # Connector between rounds
        if r > 0:
            html += "<div class='brk-connector'></div>"
    html += "</div>"
    return html

# --- UI-Abschnitte ---

def _t_setup_ui():
    """Formular für ein neues Turnier."""
    st.markdown("""
    <div style='text-align:center;padding:30px 0 10px 0;'>
        <div style='font-size:48px;'>🏆</div>
        <div style='font-size:22px;font-weight:700;color:#fff;margin-top:8px;'>Neues Turnier erstellen</div>
        <div style='font-size:13px;color:#6b7fa3;margin-top:4px;'>Kein aktives Turnier vorhanden</div>
    </div>
    """, unsafe_allow_html=True)

    with st.form("neues_turnier_form"):
        name = st.text_input("Turniername", placeholder="z.B. Vereinsmeisterschaft 2026")

        st.markdown("#### Modus")
        st.selectbox("Turniermodus", ["Gruppen + KO"], disabled=True)

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### Gruppenphase")
            n_teilnehmer = st.number_input("Anzahl Teilnehmer", 4, 32, 8, 1)
            n_gruppen = st.number_input("Anzahl Gruppen", 1, 8, 2, 1)
            weiter = st.number_input("Weiterkommer pro Gruppe", 1, 4, 2, 1)
            legs_g = st.selectbox("Legs pro Spiel (Gruppe)", [3, 5, 7], index=0)
        with col2:
            st.markdown("#### KO-Phase")
            legs_k = st.selectbox("Legs pro Spiel (KO)", [5, 7, 9], index=0)

            n_qual = int(n_gruppen) * int(weiter)
            bracket_size = 1
            while bracket_size < n_qual:
                bracket_size *= 2
            st.markdown("&nbsp;")
            st.markdown("**Bracket-Vorschau:**")
            if n_qual == bracket_size:
                st.success(f"✅ {n_qual} Qualifizierte → sauberes {bracket_size}er-Bracket")
            else:
                byes = bracket_size - n_qual
                st.warning(f"⚠️ {n_qual} Qualifizierte → {bracket_size}er-Bracket ({byes} Freilos{'e' if byes>1 else ''})")
            n_runden = int(math.log2(bracket_size))
            runden_namen = ["Finale", "Halbfinale", "Viertelfinale", "Achtelfinale",
                            "16tel-Finale", "32tel-Finale"]
            for ri in range(n_runden - 1, -1, -1):
                name_idx = n_runden - 1 - ri
                rn = runden_namen[name_idx] if name_idx < len(runden_namen) else f"Runde {ri+1}"
                n_m = bracket_size // (2 ** (ri + 1))
                st.caption(f"→ {rn}: {n_m} Spiel{'e' if n_m>1 else ''}")

        submitted = st.form_submit_button("🏆 Turnier erstellen", type="primary")
        if submitted:
            if not name.strip():
                st.error("Bitte einen Turniernamen eingeben.")
            else:
                config = {
                    "modus": "gruppen_ko",
                    "n_teilnehmer": int(n_teilnehmer),
                    "n_gruppen": int(n_gruppen),
                    "weiter_pro_gruppe": int(weiter),
                    "legs_gruppen": int(legs_g),
                    "legs_ko": int(legs_k),
                    "teilnehmer": []
                }
                speichere_turnier({
                    "name": name.strip(),
                    "status": "auslosung",
                    "config": config,
                    "gruppen": {},
                    "gruppen_spiele": [],
                    "ko_spiele": [],
                    "qualifizierte": {}
                })
                st.rerun()


def _t_auslosung_ui(turnier):
    """Teilnehmer eingeben und Gruppen auslosen."""
    config = turnier.get("config", {})
    n_tln = config.get("n_teilnehmer", 8)
    n_grp = config.get("n_gruppen", 2)
    weiter = config.get("weiter_pro_gruppe", 2)
    legs_g = config.get("legs_gruppen", 3)
    legs_k = config.get("legs_ko", 5)

    st.markdown(f"""
    <div style='background:#1a2540;border-radius:8px;padding:14px 18px;margin-bottom:20px;display:flex;flex-wrap:wrap;gap:20px;'>
        <div><div style='font-size:11px;color:#6b7fa3;'>Teilnehmer</div><div style='font-size:20px;font-weight:700;color:#fff;'>{n_tln}</div></div>
        <div><div style='font-size:11px;color:#6b7fa3;'>Gruppen</div><div style='font-size:20px;font-weight:700;color:#fff;'>{n_grp}</div></div>
        <div><div style='font-size:11px;color:#6b7fa3;'>Weiterkommer/Gruppe</div><div style='font-size:20px;font-weight:700;color:#fff;'>{weiter}</div></div>
        <div><div style='font-size:11px;color:#6b7fa3;'>Legs Gruppe</div><div style='font-size:20px;font-weight:700;color:#fff;'>Best of {legs_g}</div></div>
        <div><div style='font-size:11px;color:#6b7fa3;'>Legs KO</div><div style='font-size:20px;font-weight:700;color:#fff;'>Best of {legs_k}</div></div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("### Teilnehmer")
    df_spieler_liste = list(lade_spieler().index)
    eingabe_modus = st.radio("Eingabe", ["Aus Spielerliste", "Manuell"], horizontal=True, label_visibility="collapsed")

    teilnehmer = []
    if eingabe_modus == "Aus Spielerliste":
        ausgewaehlt = st.multiselect(
            f"Spieler auswählen ({n_tln} benötigt)",
            df_spieler_liste
        )
        teilnehmer = ausgewaehlt
    else:
        text = st.text_area(
            f"Namen eingeben (einer pro Zeile, {n_tln} benötigt)",
            height=200, placeholder="Max Mustermann\nAnna Beispiel\n..."
        )
        teilnehmer = [t.strip() for t in text.strip().split("\n") if t.strip()]

    n_aktuell = len(teilnehmer)
    if n_aktuell > 0:
        if n_aktuell == n_tln:
            st.success(f"✅ {n_aktuell}/{n_tln} Teilnehmer – bereit zur Auslosung!")
        else:
            st.warning(f"⚠️ {n_aktuell}/{n_tln} Teilnehmer")

    col1, col2 = st.columns([2, 1])
    with col1:
        if st.button("🎲 Gruppen auslosen!", disabled=(n_aktuell != n_tln), type="primary", use_container_width=True):
            gruppen = t_erstelle_gruppen(teilnehmer, n_grp)
            gruppen_spiele = t_erstelle_gruppenspiele(gruppen, TURNIER_BOARDS)
            neue_config = dict(config)
            neue_config["teilnehmer"] = teilnehmer
            speichere_turnier({
                **turnier,
                "status": "gruppen",
                "config": neue_config,
                "gruppen": gruppen,
                "gruppen_spiele": gruppen_spiele
            })
            st.rerun()
    with col2:
        if st.button("⚙️ Einstellungen ändern", use_container_width=True):
            loesche_turnier()
            st.rerun()


def _t_uebersicht_ui(turnier):
    """Übersicht: Status, Gruppentabellen, Champion."""
    config = turnier.get("config", {})
    gruppen = turnier.get("gruppen", {})
    gs = turnier.get("gruppen_spiele", [])
    ko = turnier.get("ko_spiele", [])
    status = turnier.get("status", "gruppen")
    weiter_n = config.get("weiter_pro_gruppe", 2)

    # Metriken
    total_g = len(gs)
    done_g = sum(1 for s in gs if s.get("abgeschlossen"))
    real_ko = [s for s in ko if s.get("spieler_b") != "BYE"]
    done_k = sum(1 for s in real_ko if s.get("abgeschlossen"))

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Gruppenspiele", f"{done_g}/{total_g}")
    col2.metric("KO-Spiele", f"{done_k}/{len(real_ko)}" if ko else "–")
    col3.metric("Qualifizierte", f"{weiter_n * len(gruppen)}")
    col4.metric("Boards", str(TURNIER_BOARDS))

    st.markdown("---")

    # Champion
    if status == "abgeschlossen" and ko:
        finale = [s for s in ko if s["runde_idx"] == 0]
        if finale and finale[0].get("sieger"):
            st.markdown(f"""
            <div style='background:linear-gradient(135deg,#1a1a0e,#2a2000);padding:28px;border-radius:14px;
                text-align:center;margin-bottom:24px;border:2px solid #f59e0b88;'>
                <div style='font-size:52px;'>🏆</div>
                <div style='font-size:34px;font-weight:900;color:#f59e0b;margin-top:8px;'>{finale[0]['sieger']}</div>
                <div style='font-size:13px;color:#92814a;letter-spacing:3px;text-transform:uppercase;margin-top:4px;'>Turniersieger</div>
            </div>
            """, unsafe_allow_html=True)

    # Gruppentabellen
    if gruppen:
        st.markdown("### Gruppentabellen")
        cols = st.columns(min(len(gruppen), 4))
        for i, (gk, mitglieder) in enumerate(sorted(gruppen.items())):
            tab = t_berechne_tabelle(gk, mitglieder, gs)
            with cols[i % len(cols)]:
                st.markdown(f"**Gruppe {gk}**")
                rows = ""
                for pos, (name, s) in enumerate(tab):
                    bg = "background:#0f2a1a;" if pos < weiter_n else ""
                    badge = "🟢" if pos < weiter_n else "·"
                    rows += (
                        f"<tr style='{bg}'>"
                        f"<td style='padding:4px 6px;font-size:12px;'>{badge}</td>"
                        f"<td style='padding:4px 6px;font-size:13px;font-weight:600;'>{name}</td>"
                        f"<td style='padding:4px 6px;font-size:13px;text-align:center;font-weight:700;'>{s['Pts']}</td>"
                        f"<td style='padding:4px 6px;font-size:12px;text-align:center;color:#888;'>{s['Diff']:+d}</td>"
                        f"<td style='padding:4px 6px;font-size:12px;text-align:center;color:#6b7fa3;'>{s['Avg']}</td>"
                        f"</tr>"
                    )
                st.markdown(
                    f"<table style='width:100%;border-collapse:collapse;'>"
                    f"<thead><tr><th></th><th style='font-size:10px;color:#6b7fa3;text-align:left;padding:2px 6px;'>Spieler</th>"
                    f"<th style='font-size:10px;color:#6b7fa3;'>Pts</th><th style='font-size:10px;color:#6b7fa3;'>+/-</th>"
                    f"<th style='font-size:10px;color:#6b7fa3;'>Avg</th></tr></thead>"
                    f"<tbody>{rows}</tbody></table>",
                    unsafe_allow_html=True
                )

    # Qualifizierte
    if status in ("ko", "abgeschlossen") and turnier.get("qualifizierte"):
        st.markdown("---")
        st.markdown("### Qualifizierte für KO-Phase")
        qual = turnier.get("qualifizierte", {})
        qual_cols = st.columns(min(len(qual), 4))
        for i, (seed, name) in enumerate(sorted(qual.items(), key=lambda x: int(x[0]))):
            with qual_cols[i % len(qual_cols)]:
                st.markdown(
                    f"<div style='background:#1a2540;border-radius:6px;padding:6px 12px;margin-bottom:4px;'>"
                    f"<span style='color:#6b7fa3;font-size:11px;'>Seed {seed}</span> "
                    f"<span style='font-weight:700;font-size:14px;'>{name}</span></div>",
                    unsafe_allow_html=True
                )


def _t_gruppenphase_ui(turnier, readonly=False):
    """Spielplan + Gruppentabellen der Gruppenphase."""
    config = turnier.get("config", {})
    gruppen = turnier.get("gruppen", {})
    gs = turnier.get("gruppen_spiele", [])
    weiter_n = config.get("weiter_pro_gruppe", 2)

    if not gruppen:
        st.info("Noch keine Gruppen ausgelost.")
        return

    if not readonly:
        pw_key = "t_gp_pw"
        pw = st.text_input("Passwort zum Eintragen", type="password", key=pw_key)
        admin_mode = (pw == PASSWORT)
        if admin_mode:
            st.caption("🔒 Ergebnis sperren · 🔓 Entsperren")
    else:
        admin_mode = False

    sub = st.tabs(["📅 Spielplan (nach Boards)", "📊 Gruppentabellen"])

    # --- SPIELPLAN ---
    with sub[0]:
        board_tab_labels = [f"Board {b}" for b in range(1, TURNIER_BOARDS + 1)] + ["Alle Spiele"]
        board_tabs = st.tabs(board_tab_labels)

        for board_idx in range(TURNIER_BOARDS + 1):
            with board_tabs[board_idx]:
                if board_idx < TURNIER_BOARDS:
                    board_nr = board_idx + 1
                    sicht_spiele = [s for s in gs if s.get("board") == board_nr]
                else:
                    sicht_spiele = gs

                if not sicht_spiele:
                    st.info("Keine Spiele auf diesem Board.")
                    continue

                aktion = None
                live_ergebnisse = {}

                for sp in sicht_spiele:
                    sid = sp["id"]
                    a, b = sp["spieler_a"], sp["spieler_b"]
                    gk = sp.get("gruppe", "?")
                    ist_fertig = sp.get("abgeschlossen", False)
                    board_label = f"<span style='background:#2a3555;border-radius:3px;padding:1px 6px;font-size:11px;color:#6b7fa3;'>Gr.{gk}</span>"

                    if ist_fertig:
                        la = sp.get("legs_a", 0); lb = sp.get("legs_b", 0)
                        avga = sp.get("avg_a", 0.0); avgb = sp.get("avg_b", 0.0)
                        cols = st.columns([1, 9, 1] if admin_mode else [1, 10])
                        with cols[0]:
                            st.markdown(board_label, unsafe_allow_html=True)
                        with cols[1]:
                            gew_style = lambda p: "color:#22c55e;font-weight:700;" if (p == a and la > lb) or (p == b and lb > la) else ""
                            st.markdown(
                                f"<div style='background:#1a2a1a;border-radius:6px;padding:7px 12px;'>"
                                f"✅ <span style='{gew_style(a)}'>{a}</span>"
                                f" <span style='color:#f59e0b;font-weight:700;font-size:15px;'>{int(la)}:{int(lb)}</span> "
                                f"<span style='{gew_style(b)}'>{b}</span>"
                                f"<span style='color:#6b7fa3;font-size:12px;'> · Avg {avga:.1f} / {avgb:.1f}</span></div>",
                                unsafe_allow_html=True
                            )
                        if admin_mode and not readonly and len(cols) > 2:
                            with cols[2]:
                                if st.button("🔓", key=f"t_unlock_g_{sid}_{board_idx}"):
                                    aktion = ("unlock", sid)
                        live_ergebnisse[sid] = sp
                    else:
                        if admin_mode and not readonly:
                            c = st.columns([1, 2, 2, 1, 1, 1, 1, 1])
                            with c[0]:
                                st.markdown(board_label, unsafe_allow_html=True)
                            with c[1]:
                                st.markdown(f"**{a}**")
                            with c[2]:
                                st.markdown(f"**{b}**")
                            with c[3]:
                                la = st.number_input("", 0, step=1, value=sp.get("legs_a") or 0,
                                                     key=f"t_gla_{sid}_{board_idx}", label_visibility="collapsed")
                            with c[4]:
                                lb = st.number_input("", 0, step=1, value=sp.get("legs_b") or 0,
                                                     key=f"t_glb_{sid}_{board_idx}", label_visibility="collapsed")
                            with c[5]:
                                avga = st.number_input("", 0.0, step=0.1, value=sp.get("avg_a") or 0.0,
                                                       key=f"t_gavga_{sid}_{board_idx}", label_visibility="collapsed")
                            with c[6]:
                                avgb = st.number_input("", 0.0, step=0.1, value=sp.get("avg_b") or 0.0,
                                                       key=f"t_gavgb_{sid}_{board_idx}", label_visibility="collapsed")
                            with c[7]:
                                if st.button("🔒", key=f"t_lock_g_{sid}_{board_idx}"):
                                    aktion = ("lock", sid, la, lb, avga, avgb)
                            live_ergebnisse[sid] = {**sp, "legs_a": la, "legs_b": lb, "avg_a": avga, "avg_b": avgb}
                        else:
                            c = st.columns([1, 9])
                            with c[0]:
                                st.markdown(board_label, unsafe_allow_html=True)
                            with c[1]:
                                st.markdown(f"⏳ **{a}** vs **{b}**")
                            live_ergebnisse[sid] = sp

                if aktion and admin_mode and not readonly:
                    neue_gs = []
                    for sp in gs:
                        sp = dict(sp)
                        if sp["id"] == aktion[1]:
                            if aktion[0] == "lock" and len(aktion) > 2:
                                sp["legs_a"] = aktion[2]; sp["legs_b"] = aktion[3]
                                sp["avg_a"] = aktion[4]; sp["avg_b"] = aktion[5]
                                sp["abgeschlossen"] = True
                            elif aktion[0] == "unlock":
                                sp["abgeschlossen"] = False
                        neue_gs.append(sp)
                    speichere_turnier({**turnier, "gruppen_spiele": neue_gs})
                    st.rerun()

        # Gruppenphase abschließen
        if admin_mode and not readonly:
            st.markdown("---")
            fehlend = [s for s in gs if not s.get("abgeschlossen")]
            if not fehlend:
                st.success("✅ Alle Gruppenspiele eingetragen!")
                if st.button("🏆 Gruppenphase abschließen & KO-Phase starten", type="primary"):
                    qual_list = t_get_qualifizierte(gruppen, gs, config.get("weiter_pro_gruppe", 2))
                    ko_spiele = t_erstelle_ko_spiele(len(qual_list))
                    ko_spiele = t_befuelle_ko_erste_runde(ko_spiele, qual_list, TURNIER_BOARDS)
                    ko_spiele = t_propagiere_sieger(ko_spiele, TURNIER_BOARDS)
                    qual_dict = {str(i + 1): n for i, n in enumerate(qual_list)}
                    speichere_turnier({
                        **turnier,
                        "status": "ko",
                        "ko_spiele": ko_spiele,
                        "qualifizierte": qual_dict
                    })
                    st.rerun()
            else:
                st.warning(f"Noch {len(fehlend)} Spiel(e) ausstehend. Alle Ergebnisse eintragen, um zur KO-Phase zu wechseln.")

    # --- GRUPPENTABELLEN ---
    with sub[1]:
        for gk in sorted(gruppen.keys()):
            mitglieder = gruppen[gk]
            tab = t_berechne_tabelle(gk, mitglieder, gs)
            st.markdown(f"### Gruppe {gk}")
            rows = ""
            for pos, (name, s) in enumerate(tab):
                bg = "background:#0a1f12;" if pos < weiter_n else ""
                badge = "🟢" if pos < weiter_n else "🔴"
                diff_col = "#22c55e" if s["Diff"] > 0 else "#ef4444" if s["Diff"] < 0 else "#9bacc8"
                rows += (
                    f"<tr style='{bg}border-bottom:1px solid #1e2d45;'>"
                    f"<td style='padding:9px 10px;font-size:14px;'>{badge} {pos+1}.</td>"
                    f"<td style='padding:9px 10px;font-size:15px;font-weight:700;'>{name}</td>"
                    f"<td style='padding:9px 8px;text-align:center;font-size:13px;color:#6b7fa3;'>{s['Sp']}</td>"
                    f"<td style='padding:9px 8px;text-align:center;font-size:13px;color:#22c55e;'>{s['S']}</td>"
                    f"<td style='padding:9px 8px;text-align:center;font-size:13px;color:#ef4444;'>{s['N']}</td>"
                    f"<td style='padding:9px 8px;text-align:center;font-size:13px;'>{s['+L']}:{s['-L']}</td>"
                    f"<td style='padding:9px 8px;text-align:center;font-size:13px;color:{diff_col};'>{s['Diff']:+d}</td>"
                    f"<td style='padding:9px 8px;text-align:center;font-size:13px;color:#f59e0b;'>{s['Avg']}</td>"
                    f"<td style='padding:9px 10px;text-align:center;font-size:16px;font-weight:900;color:#fff;'>{s['Pts']}</td>"
                    f"</tr>"
                )
            header = (
                "<tr style='border-bottom:2px solid #2a3555;'>"
                "<th style='padding:6px 10px;font-size:10px;color:#6b7fa3;text-align:left;'>#</th>"
                "<th style='padding:6px 10px;font-size:10px;color:#6b7fa3;text-align:left;'>Spieler</th>"
                "<th style='padding:6px 8px;font-size:10px;color:#6b7fa3;'>Sp</th>"
                "<th style='padding:6px 8px;font-size:10px;color:#6b7fa3;'>S</th>"
                "<th style='padding:6px 8px;font-size:10px;color:#6b7fa3;'>N</th>"
                "<th style='padding:6px 8px;font-size:10px;color:#6b7fa3;'>Legs</th>"
                "<th style='padding:6px 8px;font-size:10px;color:#6b7fa3;'>Diff</th>"
                "<th style='padding:6px 8px;font-size:10px;color:#6b7fa3;'>Avg</th>"
                "<th style='padding:6px 10px;font-size:10px;color:#6b7fa3;'>Pts</th>"
                "</tr>"
            )
            st.markdown(
                f"<table style='width:100%;border-collapse:collapse;background:#111827;border-radius:8px;"
                f"overflow:hidden;margin-bottom:24px;'>"
                f"<thead>{header}</thead><tbody>{rows}</tbody></table>",
                unsafe_allow_html=True
            )
            gruppe_spiele = [s for s in gs if s.get("gruppe") == gk]
            with st.expander(f"Spiele Gruppe {gk} ({sum(1 for s in gruppe_spiele if s.get('abgeschlossen'))}/{len(gruppe_spiele)})"):
                for sp in gruppe_spiele:
                    if sp.get("abgeschlossen"):
                        la, lb = sp.get("legs_a", 0), sp.get("legs_b", 0)
                        avga, avgb = sp.get("avg_a", 0.0), sp.get("avg_b", 0.0)
                        gew = sp["spieler_a"] if la > lb else sp["spieler_b"]
                        st.markdown(
                            f"✅ **{sp['spieler_a']}** {int(la)}:{int(lb)} **{sp['spieler_b']}** "
                            f"<span style='color:#6b7fa3;font-size:12px;'>Avg {avga:.1f}/{avgb:.1f} · Board {sp.get('board', '?')}</span>",
                            unsafe_allow_html=True
                        )
                    else:
                        st.markdown(f"⏳ **{sp['spieler_a']}** vs **{sp['spieler_b']}** · Board {sp.get('board', '?')}")


def _t_ko_ui(turnier):
    """KO-Phasen Spielplan mit Ergebniseintragung."""
    ko = turnier.get("ko_spiele", [])
    status = turnier.get("status", "ko")

    if not ko:
        st.info("Keine KO-Spiele vorhanden.")
        return

    pw = st.text_input("Passwort zum Eintragen", type="password", key="t_ko_pw")
    admin_mode = (pw == PASSWORT)
    if admin_mode:
        st.caption("🔒 Ergebnis sperren · 🔓 Entsperren")

    max_r = max(s["runde_idx"] for s in ko)

    for r in range(max_r, -1, -1):
        runde_spiele = sorted([s for s in ko if s["runde_idx"] == r], key=lambda x: x["match_nr"])
        rname = runde_spiele[0]["runde_name"] if runde_spiele else f"Runde {r}"

        st.markdown(f"### {rname}")
        aktion = None

        for sp in runde_spiele:
            sid = sp["id"]
            a = sp.get("spieler_a") or "TBD"
            b = sp.get("spieler_b") or "TBD"

            if b == "BYE":
                st.markdown(
                    f"<div style='background:#0f1f0f;border-radius:6px;padding:8px 12px;margin-bottom:4px;'>"
                    f"🎯 <b>{a}</b> — <span style='color:#22c55e;'>Freilos (BYE)</span></div>",
                    unsafe_allow_html=True
                )
                continue

            ist_fertig = sp.get("abgeschlossen", False)
            board_str = f"Board {sp['board']}" if sp.get("board") else "Board TBD"

            if ist_fertig:
                la, lb = sp.get("legs_a", 0), sp.get("legs_b", 0)
                avga, avgb = sp.get("avg_a", 0.0), sp.get("avg_b", 0.0)
                sieger = sp.get("sieger", "?")
                cols = st.columns([8, 1] if admin_mode else [10])
                with cols[0]:
                    gew_a = la is not None and lb is not None and la > lb
                    st.markdown(
                        f"<div style='background:#1a2a1a;border-radius:6px;padding:9px 14px;margin-bottom:4px;'>"
                        f"<span style='font-size:11px;color:#6b7fa3;'>{board_str}</span><br>"
                        f"✅ <span style='{'color:#22c55e;font-weight:700;' if gew_a else ''}'>{a}</span>"
                        f" <span style='color:#f59e0b;font-weight:700;font-size:16px;'>{int(la)}:{int(lb)}</span> "
                        f"<span style='{'color:#22c55e;font-weight:700;' if not gew_a else ''}'>{b}</span>"
                        f"<span style='color:#6b7fa3;font-size:12px;'> · Avg {avga:.1f}/{avgb:.1f}</span>"
                        f"<span style='color:#22c55e;font-size:12px;font-weight:600;'> → {sieger}</span></div>",
                        unsafe_allow_html=True
                    )
                if admin_mode and len(cols) > 1:
                    with cols[1]:
                        if st.button("🔓", key=f"t_unlock_ko_{sid}"):
                            aktion = ("unlock", sid)
            elif a == "TBD" or b == "TBD":
                st.markdown(
                    f"<div style='background:#111827;border-radius:6px;padding:8px 12px;margin-bottom:4px;color:#4b5563;'>"
                    f"⏸ TBD vs TBD – wartet auf Vorrundenergebnis</div>",
                    unsafe_allow_html=True
                )
            else:
                if admin_mode:
                    c = st.columns([2, 2, 1, 1, 1, 1, 1])
                    with c[0]:
                        st.markdown(f"**{a}**")
                    with c[1]:
                        st.markdown(f"**{b}**")
                    with c[2]:
                        la = st.number_input("", 0, step=1, value=0,
                                             key=f"t_kola_{sid}", label_visibility="collapsed")
                    with c[3]:
                        lb = st.number_input("", 0, step=1, value=0,
                                             key=f"t_kolb_{sid}", label_visibility="collapsed")
                    with c[4]:
                        avga = st.number_input("", 0.0, step=0.1, value=0.0,
                                               key=f"t_koavga_{sid}", label_visibility="collapsed")
                    with c[5]:
                        avgb = st.number_input("", 0.0, step=0.1, value=0.0,
                                               key=f"t_koavgb_{sid}", label_visibility="collapsed")
                    with c[6]:
                        if st.button("🔒", key=f"t_lock_ko_{sid}"):
                            aktion = ("lock", sid, la, lb, avga, avgb)
                else:
                    st.markdown(
                        f"<div style='background:#111827;border-radius:6px;padding:8px 12px;margin-bottom:4px;'>"
                        f"⏳ <b>{a}</b> vs <b>{b}</b>"
                        f"<span style='color:#6b7fa3;font-size:12px;'> · {board_str}</span></div>",
                        unsafe_allow_html=True
                    )

        if aktion and admin_mode:
            neue_ko = []
            for sp in ko:
                sp = dict(sp)
                if sp["id"] == aktion[1]:
                    if aktion[0] == "lock" and len(aktion) > 2:
                        _, sid_a, la_v, lb_v, avga_v, avgb_v = aktion
                        sp["legs_a"] = la_v; sp["legs_b"] = lb_v
                        sp["avg_a"] = avga_v; sp["avg_b"] = avgb_v
                        sp["abgeschlossen"] = True
                        sp["sieger"] = sp["spieler_a"] if la_v > lb_v else sp["spieler_b"]
                    elif aktion[0] == "unlock":
                        sp["abgeschlossen"] = False
                        sp["sieger"] = None
                neue_ko.append(sp)
            neue_ko = t_propagiere_sieger(neue_ko, TURNIER_BOARDS)
            neue_status = turnier.get("status", "ko")
            finale = [s for s in neue_ko if s["runde_idx"] == 0]
            if finale and finale[0].get("abgeschlossen"):
                neue_status = "abgeschlossen"
            speichere_turnier({**turnier, "ko_spiele": neue_ko, "status": neue_status})
            st.rerun()

        st.markdown("---")


def _t_baum_ui(turnier):
    """Visueller Turnierbaum."""
    ko = turnier.get("ko_spiele", [])
    if not ko:
        st.info("Der Turnierbaum wird nach Abschluss der Gruppenphase verfügbar.")
        return
    st.markdown("### Turnierbaum")
    st.markdown(t_bracket_html(ko), unsafe_allow_html=True)
    if turnier.get("status") == "abgeschlossen":
        finale = [s for s in ko if s["runde_idx"] == 0]
        if finale and finale[0].get("sieger"):
            st.markdown(f"""
            <div style='text-align:center;margin-top:24px;padding:24px;
                background:linear-gradient(135deg,#1a1a0e,#2a2000);border-radius:14px;
                border:2px solid #f59e0b88;'>
                <div style='font-size:48px;'>🏆</div>
                <div style='font-size:30px;font-weight:900;color:#f59e0b;margin-top:8px;'>{finale[0]['sieger']}</div>
                <div style='font-size:12px;color:#92814a;letter-spacing:3px;text-transform:uppercase;margin-top:6px;'>Turniersieger</div>
            </div>
            """, unsafe_allow_html=True)


def turnier_main():
    """Haupt-Dispatcher für den Turnier-Bereich."""
    turnier = lade_turnier()
    st.markdown("<h2 style='font-size:28px;'>🏆 Turnier</h2>", unsafe_allow_html=True)

    if turnier is None:
        _t_setup_ui()
        return

    status = turnier.get("status", "setup")
    name = turnier.get("name", "Turnier")

    status_map = {
        "auslosung": ("🎲 Auslosung", "#f59e0b"),
        "gruppen": ("⚽ Gruppenphase", "#3b82f6"),
        "ko": ("🏆 KO-Phase", "#22c55e"),
        "abgeschlossen": ("✅ Abgeschlossen", "#22c55e")
    }
    slabel, scolor = status_map.get(status, ("⚙️ Setup", "#6b7fa3"))

    st.markdown(f"""
    <div style='background:#1a2540;padding:14px 20px;border-radius:10px;margin-bottom:20px;
        display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;'>
        <div>
            <div style='font-size:24px;font-weight:800;color:#fff;'>{name}</div>
            <div style='font-size:12px;color:#6b7fa3;margin-top:2px;'>Modus: Gruppen + KO · {TURNIER_BOARDS} Boards</div>
        </div>
        <div style='background:{scolor}22;color:{scolor};padding:5px 14px;border-radius:20px;
            font-size:13px;font-weight:700;border:1px solid {scolor}55;'>
            {slabel}
        </div>
    </div>
    """, unsafe_allow_html=True)

    if status == "auslosung":
        tabs = st.tabs(["🎲 Auslosung"])
        with tabs[0]:
            _t_auslosung_ui(turnier)
    elif status == "gruppen":
        tabs = st.tabs(["📋 Übersicht", "⚽ Gruppenphase", "🌳 Turnierbaum"])
        with tabs[0]:
            _t_uebersicht_ui(turnier)
        with tabs[1]:
            _t_gruppenphase_ui(turnier)
        with tabs[2]:
            _t_baum_ui(turnier)
    elif status in ("ko", "abgeschlossen"):
        tabs = st.tabs(["📋 Übersicht", "⚽ Gruppenphase", "🏆 KO-Phase", "🌳 Turnierbaum"])
        with tabs[0]:
            _t_uebersicht_ui(turnier)
        with tabs[1]:
            _t_gruppenphase_ui(turnier, readonly=True)
        with tabs[2]:
            _t_ko_ui(turnier)
        with tabs[3]:
            _t_baum_ui(turnier)

    st.markdown("---")
    with st.expander("⚠️ Turnier verwalten"):
        st.caption("Achtung: Das Löschen kann nicht rückgängig gemacht werden.")
        if st.button("🗑 Turnier löschen", type="secondary"):
            loesche_turnier()
            st.rerun()
