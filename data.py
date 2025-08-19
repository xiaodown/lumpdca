import os
import sqlite3
import warnings
import yfinance as yf
import pandas as pd
import settings

warnings.filterwarnings("ignore", category=FutureWarning)

CACHE_DB = settings.CACHE_DB
DEFAULT_START = "1990-01-01"  # Changed to 1990 as requested

def ticker_to_table_name(ticker):
    """Sanitizes ticker for use as a SQLite table name."""
    return f"stock_{ticker.replace('^', '').replace('-', '_')}"

def flatten_yfinance_columns(df):
    """Flattens yfinance MultiIndex columns to simple column names."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
    else:
        new_columns = []
        for col in df.columns:
            if isinstance(col, str) and col.startswith("('") and col.endswith("')"):
                try:
                    parts = col.strip("()").split("', '")
                    if len(parts) >= 1:
                        new_columns.append(parts[0].strip("'\""))
                    else:
                        new_columns.append(col)
                except:
                    new_columns.append(col)
            else:
                new_columns.append(str(col))
        df.columns = new_columns
    return df

def standardize_dataframe(df):
    """Standardizes a yfinance DataFrame for consistent storage and retrieval."""
    df = flatten_yfinance_columns(df)

    if 'Date' not in df.columns and df.index.name != 'Date':
        if pd.api.types.is_datetime64_any_dtype(df.index):
            df.index.name = 'Date'
        else:
            df = df.reset_index()
            for col in df.columns:
                if 'date' in col.lower() or pd.api.types.is_datetime64_any_dtype(df[col]):
                    df = df.rename(columns={col: 'Date'})
                    break

    expected_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
    
    if 'Close' not in df.columns and 'Adj Close' in df.columns:
        df['Close'] = df['Adj Close']

    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.set_index('Date')

    if not pd.api.types.is_datetime64_any_dtype(df.index):
        df.index = pd.to_datetime(df.index)

    return df

class HistoricalData:
    """Handles fetching and caching historical stock/index data using yfinance and SQLite."""

    def __init__(self, ticker):
        self.ticker = ticker
        self.table_name = ticker_to_table_name(self.ticker)
        self._data = None
        self._cache_hit = None  # Track if last load was cache hit or miss

    def _is_cached(self):
        """Check if ticker data exists in cache."""
        try:
            with sqlite3.connect(CACHE_DB) as conn:
                cursor = conn.cursor()
                cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{self.table_name}';")
                return cursor.fetchone() is not None
        except Exception:
            return False

    def _load_or_download(self):
        """Loads data from cache or downloads and caches it if missing."""
        # First check if data exists in cache
        try:
            with sqlite3.connect(CACHE_DB) as conn:
                cached_df = pd.read_sql(f"SELECT * FROM {self.table_name}", conn, parse_dates=['Date'])
                cached_df = cached_df.set_index('Date')
                self._data = cached_df
                self._cache_hit = True
                return
        except Exception:
            # Cache miss - need to download
            self._cache_hit = False

        # Download from yfinance
        try:
            raw_df = yf.download(self.ticker, start=DEFAULT_START, progress=False)

            if raw_df.empty:
                self._data = pd.DataFrame()
                return

            df = standardize_dataframe(raw_df.copy())
            df_to_save = df.reset_index()
            
            with sqlite3.connect(CACHE_DB) as conn:
                df_to_save.to_sql(self.table_name, conn, if_exists='replace', index=False)

            self._data = df

        except Exception as e:
            self._data = pd.DataFrame()

    def was_cache_miss(self):
        """Returns True if the last data load was a cache miss."""
        return self._cache_hit is False

    def get_data(self, start, end):
        """Returns cached data for the given date range."""
        if self._data is None:
            self._load_or_download()

        if self._data.empty:
            return pd.DataFrame()

        start_date = pd.to_datetime(start)
        end_date = pd.to_datetime(end)

        mask = (self._data.index >= start_date) & (self._data.index <= end_date)
        return self._data.loc[mask]

    @staticmethod
    def update_cache(ticker):
        """Explicitly updates the cache for the given ticker."""
        print(f"Updating cache for {ticker}...")
        try:
            raw_df = yf.download(ticker, start=DEFAULT_START, progress=False)
            if raw_df.empty:
                print(f"No data returned for {ticker}")
                return

            df = standardize_dataframe(raw_df.copy())
            df_to_save = df.reset_index()

            with sqlite3.connect(CACHE_DB) as conn:
                df_to_save.to_sql(ticker_to_table_name(ticker), conn, if_exists='replace', index=False)

            print(f"Successfully updated cache for {ticker}")
        except Exception as e:
            print(f"Error updating cache for {ticker}: {e}")

    @staticmethod
    def update_all_caches():
        """Updates the cache for all tickers"""
        if not os.path.exists(CACHE_DB):
            print("No cache database found. Nothing to update.")
            return

        try:
            # Get all unique tickers from available stocks (now 4-tuple format)
            available_tickers = [ticker for ticker, _, _, _ in settings.AVAILABLE_STOCKS]
            
            for ticker in available_tickers:
                HistoricalData.update_cache(ticker)
                
        except Exception as e:
            print(f"Error updating caches: {e}")

def clear_cache():
    """Deletes the cache database file."""
    if os.path.exists(CACHE_DB):
        os.remove(CACHE_DB)
        print(f"Cache database '{CACHE_DB}' cleared.")
    else:
        print(f"No cache database '{CACHE_DB}' found to clear.")
