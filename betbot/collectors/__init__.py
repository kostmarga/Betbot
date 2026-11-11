"""Μητρώο collectors. Η σειρά μετράει:
  1. αποτελέσματα/πρόγραμμα (espn, euroleague)
  2. αποδόσεις (fdco, espn_odds, odds_api) – «κολλάνε» στους ήδη γνωστούς αγώνες
  3. sofascore: στατιστικά, πλάγια, ενδεκάδες, απουσίες, διαιτητής, αποδόσεις με αρχική τιμή
  4. espn_stats: συμπληρώνει στατιστικά όπου το sofascore δεν έφερε
  4β. espn_lineups: ενδεκάδες (και διαιτητής όπου υπάρχει) από το ESPN, λίγο πριν τον αγώνα
  5. fdco_history: ιστορικά αποτελέσματα/κόρνερ/κάρτες από προηγούμενες σεζόν
  6. ελληνικό site (αν ρυθμιστεί)
"""
from .espn import EspnCollector
from .euroleague import EuroleagueCollector
from .fdco_odds import FdcoOddsCollector
from .espn_odds import EspnOddsCollector
from .odds_api import OddsApiCollector
from .sofascore import SofascoreCollector
from .espn_stats import EspnStatsCollector
from .espn_lineups import EspnLineupsCollector
from .espn_standings import EspnStandingsCollector
from .espn_injuries import EspnInjuriesCollector
from .fdco_history import FdcoHistoryCollector
from .greek_site import GreekSiteCollector

ALL = [EspnCollector, EuroleagueCollector, FdcoOddsCollector, EspnOddsCollector, OddsApiCollector,
       SofascoreCollector, EspnStatsCollector, EspnLineupsCollector, EspnStandingsCollector, EspnInjuriesCollector, FdcoHistoryCollector, GreekSiteCollector]
