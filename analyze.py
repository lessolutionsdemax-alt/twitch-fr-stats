#!/usr/bin/env python3
"""
Analyse des snapshots (à lancer en local, après quelques semaines de collecte).

  python analyze.py                  classement des catégories (médiane sur tous les créneaux)
  python analyze.py --best           meilleurs créneaux (jour × heure × catégorie)
  python analyze.py "Minecraft"      heatmap jour × heure pour une catégorie

Métrique clé : avg_hors_top3 = viewers restants / chaînes restantes une fois les 3 plus
grosses chaînes retirées. C'est ce qu'une chaîne "normale" peut espérer capter, bien plus
parlant que la moyenne brute qui est tirée vers le haut par un seul gros streamer.

pip install pandas
"""
import glob
import sys

import pandas as pd

JOURS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
MIN_SNAPSHOTS = 10   # une catégorie doit apparaître dans au moins N snapshots pour être classée


def load() -> pd.DataFrame:
    files = sorted(glob.glob("data/20*.csv"))
    if not files:
        sys.exit("Aucun fichier data/*.csv")
    df = pd.concat((pd.read_csv(f) for f in files), ignore_index=True)
    ts = pd.to_datetime(df["ts_utc"], utc=True).dt.tz_convert("Europe/Paris")
    df["jour"] = ts.dt.weekday.map(lambda i: JOURS[i])
    df["heure"] = ts.dt.hour
    return df


def classement(df: pd.DataFrame) -> None:
    g = (df.groupby("game_name")
           .agg(snapshots=("ts_utc", "count"),
                viewers=("viewers", "median"),
                chaines=("channels", "median"),
                avg_brute=("avg_viewers", "median"),
                avg_hors_top3=("avg_hors_top3", "median"),
                top1_share=("top1_share", "median"))
           .query("snapshots >= @MIN_SNAPSHOTS")
           .sort_values("avg_hors_top3", ascending=False))
    pd.set_option("display.width", 160); pd.set_option("display.max_columns", 20)
    print(g.head(40).round(1))
    g.to_csv("classement_categories.csv")


def meilleurs_creneaux(df: pd.DataFrame) -> None:
    g = (df.groupby(["game_name", "jour", "heure"])
           .agg(n=("ts_utc", "count"),
                viewers=("viewers", "median"),
                chaines=("channels", "median"),
                avg_hors_top3=("avg_hors_top3", "median"))
           .query("n >= 3 and viewers >= 300")
           .sort_values("avg_hors_top3", ascending=False)
           .reset_index())
    pd.set_option("display.width", 160); pd.set_option("display.max_columns", 20)
    print(g.head(50).round(1).to_string(index=False))
    g.to_csv("meilleurs_creneaux.csv", index=False)


def heatmap(df: pd.DataFrame, game: str) -> None:
    sub = df[df["game_name"].str.lower() == game.lower()]
    if sub.empty:
        sys.exit(f"Catégorie inconnue : {game}")
    for metric in ("avg_hors_top3", "viewers", "channels"):
        pv = (sub.pivot_table(index="heure", columns="jour", values=metric, aggfunc="median")
                 .reindex(columns=JOURS).round(0))
        print(f"\n=== {game} — {metric} (médiane, heure de Paris) ===")
        print(pv.fillna("").to_string())
        pv.to_csv(f"heatmap_{game.lower().replace(' ', '_')}_{metric}.csv")


if __name__ == "__main__":
    data = load()
    args = sys.argv[1:]
    if not args:
        classement(data)
    elif args[0] == "--best":
        meilleurs_creneaux(data)
    else:
        heatmap(data, " ".join(args))
