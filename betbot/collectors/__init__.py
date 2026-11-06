"""Μητρώο collectors. Η σειρά μετράει:
  1. αποτελέσματα/πρόγραμμα (espn, euroleague)
  2. αποδόσεις (fdco, odds_api) – «κολλάνε» στους ήδη γνωστούς αγώνες
  3. sofascore: στατιστικά, πλάγια, ενδεκάδες, απουσίες, διαιτητής, αποδόσεις με αρχική τιμή
  4. espn_stats: συμπληρώνει στατιστικά όπου το sofascore δεν έφερε
  5. ελληνικό site (αν ρυθμιστεί)
"""
from .espn import EspnCollector
from .euroleague import EuroleagueCollector
from .fdco_odds import FdcoOddsCollector
from .odds_api import OddsApiCollector
from .sofascore import SofascoreCollector
from .espn_stats import EspnStatsCollector
from .greek_site import GreekSiteCollector

ALL = [EspnCollector, EuroleagueCollector, FdcoOddsCollector, OddsApiCollector,
       SofascoreCollector, EspnStatsCollector, GreekSiteCollector]
