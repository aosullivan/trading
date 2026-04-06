from routes.chart import bp as chart_bp
from routes.financials import bp as financials_bp
from routes.pages import bp as pages_bp
from routes.settings import bp as settings_bp
from routes.signals import bp as signals_bp
from routes.watchlist import bp as watchlist_bp

ALL_BLUEPRINTS = [chart_bp, financials_bp, pages_bp, settings_bp, signals_bp, watchlist_bp]
