import os
import sqlite3
import warnings
import threading
import yfinance as yf
import pandas as pd
import settings
import time

warnings.filterwarnings("ignore", category=FutureWarning)

CACHE_DB = settings.CACHE_DB
DEFAULT_START = "1990-01-01"

# Global download lock for thread safety
_download_lock = threading.Lock()

# RESTORED: Global SQLite access lock to prevent contention
_sqlite_lock = threading.Lock()

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
        self._cache_hit = None
        self._load_attempted = False

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
        # Use object-level locking to prevent race conditions
        if not hasattr(self, '_load_lock'):
            self._load_lock = threading.Lock()
        
        with self._load_lock:
            # Check if another thread already loaded the data
            if self._data is not None:
                return
            
            if self._load_attempted:
                return  # Don't try multiple times
            
            self._load_attempted = True
            
            # RESTORED: Use global SQLite lock to serialize all database access
            with _sqlite_lock:
                # First check if data exists in cache
                if os.path.exists(CACHE_DB):
                    try:
                        with sqlite3.connect(CACHE_DB, timeout=5.0) as conn:
                            # Check if table exists first
                            cursor = conn.cursor()
                            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{self.table_name}';")
                            table_exists = cursor.fetchone() is not None
                            
                            if table_exists:
                                # Check row count
                                cursor.execute(f"SELECT COUNT(*) FROM {self.table_name};")
                                row_count = cursor.fetchone()[0]
                                
                                if row_count > 0:
                                    cached_df = pd.read_sql(f"SELECT * FROM {self.table_name}", conn, parse_dates=['Date'])
                                    
                                    if not cached_df.empty:
                                        cached_df = cached_df.set_index('Date')
                                        self._data = cached_df
                                        self._cache_hit = True
                                        return
                            
                    except Exception as sql_error:
                        pass  # Fall through to download

        # If we get here, we need to download (outside the SQLite lock)
        # Use download lock to prevent multiple threads downloading same ticker
        with _download_lock:
            # Double-check cache after acquiring lock (another thread might have downloaded)
            if self._data is not None:
                return  # Another thread loaded it
                
            # Still a cache miss, proceed with download
            self._cache_hit = False

            try:
                raw_df = yf.download(self.ticker, start=DEFAULT_START, progress=False)

                if raw_df.empty:
                    self._data = pd.DataFrame()
                    return

                df = standardize_dataframe(raw_df.copy())
                df_to_save = df.reset_index()
                
                # RESTORED: Use SQLite lock for writing too
                with _sqlite_lock:
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

        if self._data is None or self._data.empty:
            return pd.DataFrame()  # Return empty DataFrame, not None

        start_date = pd.to_datetime(start)
        end_date = pd.to_datetime(end)

        mask = (self._data.index >= start_date) & (self._data.index <= end_date)
        filtered_data = self._data.loc[mask]
        
        return filtered_data

    @staticmethod
    def update_cache(ticker, silent=False):
        """Explicitly updates the cache for the given ticker."""
        if not silent:
            # Print on same line, overwriting previous ticker
            print(f"\rUpdating cache for {ticker}...", end="", flush=True)
        
        # Use the same download lock for consistency
        with _download_lock:
            try:
                raw_df = yf.download(ticker, start=DEFAULT_START, progress=False)
                if raw_df.empty:
                    if not silent:
                        print(f"\rNo data returned for {ticker}" + " " * 20)
                    return False

                df = standardize_dataframe(raw_df.copy())
                df_to_save = df.reset_index()

                # RESTORED: Use SQLite lock for writing
                with _sqlite_lock:
                    with sqlite3.connect(CACHE_DB) as conn:
                        df_to_save.to_sql(ticker_to_table_name(ticker), conn, if_exists='replace', index=False)

                return True
            except Exception as e:
                if not silent:
                    print(f"\r❌ Error updating cache for {ticker}: {e}" + " " * 20)
                return False

    @staticmethod
    def update_all_caches():
        """Updates the cache for all tickers"""
        try:
            # Get all unique tickers from available stocks (now 4-tuple format)
            available_tickers = [ticker for ticker, _, _, _ in settings.AVAILABLE_STOCKS]
            
            print(f"📥 Updating cache for {len(available_tickers)} tickers...")
            
            # Create database directory if it doesn't exist
            os.makedirs(os.path.dirname(CACHE_DB) if os.path.dirname(CACHE_DB) else '.', exist_ok=True)
            
            successful = 0
            failed = 0
            
            # Calculate max width needed for consistent padding
            max_ticker_len = max(len(ticker) for ticker in available_tickers)
            max_progress_len = len(f"({len(available_tickers)}/{len(available_tickers)})")
            # Total width: "Updating cache for " + ticker + "... " + progress = 19 + max_ticker + 4 + max_progress
            total_width = 19 + max_ticker_len + 4 + max_progress_len
            
            for i, ticker in enumerate(available_tickers, 1):
                # Show progress with current ticker, padded to consistent width
                progress_text = f"({i}/{len(available_tickers)})"
                line = f"Updating cache for {ticker}... {progress_text}"
                padded_line = f"\r{line:<{total_width}}"
                print(padded_line, end="", flush=True)
                
                success = HistoricalData.update_cache(ticker, silent=True)
                if success:
                    successful += 1
                else:
                    failed += 1
            
            # Clear the line and show final results with proper padding
            final_msg = f"🎉 Cache update complete! ✅ {successful} successful, ❌ {failed} failed"
            print(f"\r{final_msg:<{total_width}}")
                
        except Exception as e:
            print(f"\nError updating caches: {e}")

def clear_cache():
    """Deletes the cache database file."""
    if os.path.exists(CACHE_DB):
        os.remove(CACHE_DB)
        print(f"Cache database '{CACHE_DB}' cleared.")
    else:
        print(f"No cache database '{CACHE_DB}' found to clear.")
