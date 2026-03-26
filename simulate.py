import sys
import time
import random
import os
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed
from data import HistoricalData, clear_cache
import pandas as pd
import settings

TRADE_FEE = settings.TRADE_FEE

# Per-process worker cache: stores pre-processed ticker data as plain Python
# structures so simulations never touch pandas after the first load.
# Format: {ticker: {"dates": [...], "closes": [...], "monthly": [(year, month, close), ...]}}
_worker_cache = {}


def _worker_init():
    """Initialize worker process with an empty data cache."""
    global _worker_cache
    _worker_cache = {}


def _preprocess_ticker(ticker):
    """Load ticker from SQLite via HistoricalData and pre-process into plain Python.
    
    Returns (processed_dict, was_download) where processed_dict has:
      - 'closes': list of (date_ordinal, close_price) sorted by date
      - 'monthly': dict of (year, month) -> first close price that month
    """
    hd = HistoricalData(ticker)
    # Get full date range - we'll filter per-simulation with bisect
    data = hd.get_data("1990-01-01", datetime.today().strftime("%Y-%m-%d"))
    was_download = hd.was_cache_miss()
    
    if data is None or data.empty or 'Close' not in data.columns:
        return None, was_download
    
    # Convert to sorted list of (date_ordinal, close_price)
    closes = []
    monthly = {}  # (year, month) -> first close price
    
    for dt, row in zip(data.index, data['Close'].values):
        price = float(row)
        ordinal = dt.toordinal() if hasattr(dt, 'toordinal') else pd.Timestamp(dt).toordinal()
        closes.append((ordinal, price))
        key = (dt.year, dt.month)
        if key not in monthly:
            monthly[key] = price
    
    return {'closes': closes, 'monthly': monthly}, was_download


def _get_worker_data(ticker):
    """Get pre-processed stock data with per-process caching."""
    global _worker_cache
    if ticker in _worker_cache:
        return _worker_cache[ticker], False
    processed, was_download = _preprocess_ticker(ticker)
    _worker_cache[ticker] = processed
    return processed, was_download

class OutputManager:
    """Output manager with progress bar and scrolling results."""
    
    def __init__(self, max_lines=8):
        self.max_lines = max_lines
        self.recent_results = []
        self.completed_count = 0
        self.total_count = 0
        self.cache_downloads = set()
        self.last_display_lines = 0
        self._last_display_time = 0
        self._display_interval = 0.01  # seconds between display refreshes
        
    def print_header(self, num_simulations, investment_amount, num_workers):
        """Print static header information."""
        print("🚀 Investment Strategy Simulation")
        print(f"   Running {num_simulations:,} simulations with ${investment_amount:,} investment")
        print(f"   Using {num_workers} processes on {os.cpu_count()} available cores")
        print("   " + "="*60)
        print()
        self.total_count = num_simulations
        
    def add_cache_download(self, ticker):
        """Record a cache download."""
        self.cache_downloads.add(ticker)
        self._update_display()
    
    def add_result(self, result_line=None):
        """Record a completed simulation and optionally display a result line."""
        self.completed_count += 1
        if result_line:
            self.recent_results.append(result_line)
            if len(self.recent_results) > self.max_lines:
                self.recent_results.pop(0)
        # Throttle: only refresh display every _display_interval seconds
        now = time.monotonic()
        if now - self._last_display_time >= self._display_interval:
            self._last_display_time = now
            self._update_display()
    
    def _update_display(self):
        """Update the progress display."""
        # Clear previous output by moving cursor up
        if self.last_display_lines > 0:
            for _ in range(self.last_display_lines):
                print("\033[A\033[K", end="")  # Move up and clear line
        
        lines_printed = 0
        
        # Show cache downloads if any
        if self.cache_downloads:
            downloads = sorted(list(self.cache_downloads))
            if len(downloads) <= 5:
                download_text = ", ".join(downloads)
            else:
                download_text = ", ".join(downloads[-5:]) + f" (+{len(downloads)-5} more)"
            print(f"📥 Downloaded: {download_text}")
            lines_printed += 1
        
        # Show progress bar
        if self.total_count > 0:
            progress = self.completed_count / self.total_count
            bar_width = 40
            filled = int(bar_width * progress)
            bar = "█" * filled + "░" * (bar_width - filled)
            percentage = progress * 100
            print(f"[{bar}] {self.completed_count:,}/{self.total_count:,} ({percentage:.1f}%)")
            lines_printed += 1
        
        # Show recent results
        for line in self.recent_results:
            print(line)
            lines_printed += 1
            
        # Add blank line
        print()
        lines_printed += 1
        
        self.last_display_lines = lines_printed
    
    def finish(self):
        """Clean up display when done."""
        self._update_display()  # Final refresh to show 100%
        print("\n" * 2)

def pick_random_stock():
    """Pick a random stock from available stocks, respecting start years."""
    current_year = datetime.now().year
    available_now = [
        (ticker, name, start_year) for ticker, name, start_year, sector 
        in settings.AVAILABLE_STOCKS 
        if start_year <= current_year - 5  # At least 5 years of data
    ]
    ticker, name, start_year = random.choice(available_now)
    return ticker, name, start_year

def pick_random_date_for_stock(stock_start_year, end_year=2020):
    """Picks a random date between stock's start year and end year."""
    start_year = max(stock_start_year, 1990)
    start = datetime(start_year, 1, 1)
    end = datetime(end_year, 12, 31)
    delta = end - start
    random_days = random.randint(0, delta.days)
    return (start + timedelta(days=random_days)).strftime("%Y-%m-%d")

def pick_random_years():
    """Randomly selects 2, 5, or 10 years for DCA."""
    return random.choice([2, 5, 10])

def format_currency(amount):
    """Format amount as currency."""
    return f"${amount:,.0f}"

def calculate_performance(lump, dca):
    """Calculate which strategy performed better and by how much."""
    if lump is None or dca is None:
        return "ERROR", 0
    
    if lump > dca:
        percent_better = ((lump - dca) / dca) * 100 if dca > 0 else 0
        return "LUMP", percent_better
    else:
        percent_better = ((dca - lump) / lump) * 100 if lump > 0 else 0
        return "DCA", percent_better

def _run_chunk(sim_start, chunk_size, investment_amount):
    """Run a batch of simulations in one worker process.
    
    Processes chunk_size simulations and returns a list of result dicts.
    One IPC round-trip per chunk instead of per simulation.
    """
    return [
        run_single_simulation(sim_start + i, investment_amount)
        for i in range(chunk_size)
    ]

def run_single_simulation(sim_number, investment_amount):
    """Run one complete simulation in a worker process.
    
    Pure function: takes simple args, returns a result dict.
    Uses pre-processed plain Python data — no pandas in the hot path.
    """
    ticker, name, stock_start_year = pick_random_stock()
    start_date = pick_random_date_for_stock(stock_start_year)
    years = pick_random_years()
    
    # Get pre-processed data (cached per-process for repeat tickers)
    processed, was_download = _get_worker_data(ticker)
    
    if processed is None:
        return {
            'sim_number': sim_number, 'ticker': ticker, 'name': name,
            'start_date': start_date, 'lump': None, 'dca': None,
            'years': years, 'winner': 'ERROR', 'percent_better': 0,
            'was_download': was_download,
        }
    
    closes = processed['closes']  # list of (ordinal, price), sorted by date
    monthly = processed['monthly']  # dict of (year, month) -> first close price
    
    # Find the slice of closes within [start_date, today]
    start_ord = datetime.strptime(start_date, "%Y-%m-%d").toordinal()
    today_ord = datetime.today().toordinal()
    
    # Binary search for start index
    lo, hi = 0, len(closes)
    while lo < hi:
        mid = (lo + hi) // 2
        if closes[mid][0] < start_ord:
            lo = mid + 1
        else:
            hi = mid
    start_idx = lo
    
    # Binary search for end index (inclusive)
    lo, hi = start_idx, len(closes)
    while lo < hi:
        mid = (lo + hi) // 2
        if closes[mid][0] <= today_ord:
            lo = mid + 1
        else:
            hi = mid
    end_idx = lo - 1
    
    if start_idx > end_idx or start_idx >= len(closes):
        return {
            'sim_number': sim_number, 'ticker': ticker, 'name': name,
            'start_date': start_date, 'lump': None, 'dca': None,
            'years': years, 'winner': 'ERROR', 'percent_better': 0,
            'was_download': was_download,
        }
    
    start_price = closes[start_idx][1]
    end_price = closes[end_idx][1]
    
    # --- Lump Sum (pure arithmetic) ---
    available = investment_amount - TRADE_FEE
    shares = int(available // start_price)
    lump = shares * end_price
    
    # --- DCA (pure arithmetic on pre-computed monthly prices) ---
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    today_dt = datetime.today()
    available_months = (today_dt.year - start_dt.year) * 12 + (today_dt.month - start_dt.month)
    dca_months = min(years * 12, available_months)
    
    if dca_months <= 0:
        dca = 0
    else:
        monthly_contribution = investment_amount / dca_months
        shares = 0
        leftover = 0.0
        
        year = start_dt.year
        month = start_dt.month
        
        for _ in range(dca_months):
            price = monthly.get((year, month))
            if price is not None:
                available = monthly_contribution + leftover
                if available >= (price + TRADE_FEE):
                    available_for_shares = available - TRADE_FEE
                    buy_shares = int(available_for_shares // price)
                    leftover = available_for_shares - buy_shares * price
                    shares += buy_shares
                else:
                    leftover = available
            
            # Advance to next month
            month += 1
            if month > 12:
                month = 1
                year += 1
        
        dca = shares * end_price
    
    winner, percent_better = calculate_performance(lump, dca)
    
    return {
        'sim_number': sim_number,
        'ticker': ticker,
        'name': name,
        'start_date': start_date,
        'lump': lump,
        'dca': dca,
        'years': years,
        'winner': winner,
        'percent_better': percent_better,
        'was_download': was_download,
    }

def run_simulation(num_simulations, investment_amount, verbose=False):
    """Run simulations in parallel using a process pool with chunked batching."""
    start_time = time.time()

    num_workers = max(1, os.cpu_count())
    num_workers = min(num_workers, num_simulations)
    
    # Divide work into chunks — enough for smooth progress, few enough to minimize IPC
    num_chunks = num_workers * 8
    num_chunks = min(num_chunks, num_simulations)
    base_chunk_size = num_simulations // num_chunks
    remainder = num_simulations % num_chunks
    
    output_manager = OutputManager()
    output_manager.print_header(num_simulations, investment_amount, num_workers)
    
    results = []
    
    with ProcessPoolExecutor(max_workers=num_workers, initializer=_worker_init) as executor:
        futures = []
        sim_offset = 0
        for i in range(num_chunks):
            chunk_size = base_chunk_size + (1 if i < remainder else 0)
            futures.append(executor.submit(_run_chunk, sim_offset, chunk_size, investment_amount))
            sim_offset += chunk_size
        
        for future in as_completed(futures):
            try:
                chunk_results = future.result()
                for result in chunk_results:
                    results.append(result)
                    
                    if result['was_download']:
                        output_manager.add_cache_download(result['ticker'])
                    
                    if result['winner'] != "ERROR":
                        winner = result['winner']
                        result_line = (
                            f"{result['ticker']} from {result['start_date']}: "
                            f"{winner} wins by {result['percent_better']:5.1f}% "
                            f"({format_currency(result['lump'] if winner == 'LUMP' else result['dca'])})"
                        )
                        output_manager.add_result(result_line)
                    else:
                        output_manager.add_result()
                    
            except Exception as exc:
                print(f'Chunk generated an exception: {exc}')
    
    output_manager.finish()
    
    results.sort(key=lambda x: x['sim_number'])
    
    end_time = time.time()
    elapsed_time = end_time - start_time
    
    return results, elapsed_time

def print_summary(results, investment_amount, elapsed_time):
    """Print summary statistics."""
    valid_results = [r for r in results if r['winner'] != 'ERROR']
    
    if not valid_results:
        print("❌ No valid results to summarize")
        return
    
    lump_wins = len([r for r in valid_results if r['winner'] == 'LUMP'])
    dca_wins = len([r for r in valid_results if r['winner'] == 'DCA'])
    total = len(valid_results)
    
    # Calculate statistics for both strategies
    lump_values = [r['lump'] for r in valid_results if r['lump'] is not None]
    dca_values = [r['dca'] for r in valid_results if r['dca'] is not None]
    
    if lump_values and dca_values:
        import statistics
        
        avg_lump = statistics.mean(lump_values)
        avg_dca = statistics.mean(dca_values)
        median_lump = statistics.median(lump_values)
        median_dca = statistics.median(dca_values)
        
        # Show min/max for context
        min_lump, max_lump = min(lump_values), max(lump_values)
        min_dca, max_dca = min(dca_values), max(dca_values)
    else:
        avg_lump = avg_dca = median_lump = median_dca = 0
        min_lump = max_lump = min_dca = max_dca = 0
    
    print("="*60)
    print("📊 SIMULATION SUMMARY")
    print("="*60)
    print(f"Total Simulations: {total:,}")
    print(f"Starting Capital:  {format_currency(investment_amount)}")
    print(f"Time Elapsed:      {elapsed_time:.2f} seconds")
    print(f"Lump Sum Wins:     {lump_wins:,} ({lump_wins/total*100:.1f}%)")
    print(f"DCA Wins:          {dca_wins:,} ({dca_wins/total*100:.1f}%)")
    
    print(f"\n📈 Returns Analysis:")
    print(f"{'Strategy':<12} {'Median':<12} {'Average':<12} {'Min':<12} {'Max':<12}")
    print("-" * 60)
    print(f"{'Lump Sum':<12} {format_currency(median_lump):<12} {format_currency(avg_lump):<12} {format_currency(min_lump):<12} {format_currency(max_lump):<12}")
    print(f"{'DCA':<12} {format_currency(median_dca):<12} {format_currency(avg_dca):<12} {format_currency(min_dca):<12} {format_currency(max_dca):<12}")
    
    # Show best and worst performers
    best_lump = max(valid_results, key=lambda x: x['lump'] if x['lump'] else 0)
    best_dca = max(valid_results, key=lambda x: x['dca'] if x['dca'] else 0)
    worst_lump = min(valid_results, key=lambda x: x['lump'] if x['lump'] else float('inf'))
    worst_dca = min(valid_results, key=lambda x: x['dca'] if x['dca'] else float('inf'))
    
    print(f"\n🏆 Best Performers:")
    print(f"Lump Sum: {best_lump['ticker']} {format_currency(best_lump['lump'])} (from {best_lump['start_date']})")
    print(f"DCA:      {best_dca['ticker']} {format_currency(best_dca['dca'])} (from {best_dca['start_date']})")
    
    print(f"\n📉 Worst Performers:")
    print(f"Lump Sum: {worst_lump['ticker']} {format_currency(worst_lump['lump'])} (from {worst_lump['start_date']})")
    print(f"DCA:      {worst_dca['ticker']} {format_currency(worst_dca['dca'])} (from {worst_dca['start_date']})")
    
    # Show some context about outliers
    if max_lump > avg_lump * 3:
        print(f"\n⚠️  Note: Large outliers detected. Median may be more representative than average.")
    
    print("="*60)

def print_available_stocks():
    """Print all available stocks for simulation, grouped by sector in two columns."""
    print("📈 Available stocks for simulation:")
    print()
    
    # Group stocks by sector
    sectors = {}
    for ticker, name, start_year, sector in settings.AVAILABLE_STOCKS:
        if sector not in sectors:
            sectors[sector] = []
        sectors[sector].append((ticker, name, start_year))
    
    # Calculate the maximum width needed across ALL stocks for consistent columns
    max_width = 0
    all_formatted_stocks = []
    for sector in sectors:
        for ticker, name, start_year in sectors[sector]:
            formatted = f"  {ticker:<6} - {name} (data from {start_year})"
            all_formatted_stocks.append(formatted)
            max_width = max(max_width, len(formatted))
    
    # Sort sectors with ETF first, then alphabetically
    sector_order = sorted(sectors.keys())
    if 'ETF' in sector_order:
        sector_order.remove('ETF')
        sector_order.insert(0, 'ETF')
    
    # Print each sector using the global max width
    for sector in sector_order:
        stocks = sorted(sectors[sector])
        print(f"{sector}:")
        
        # Format all stocks in this sector
        formatted_stocks = []
        for ticker, name, start_year in stocks:
            formatted = f"  {ticker:<6} - {name} (data from {start_year})"
            formatted_stocks.append(formatted)
        
        # Print in two columns with consistent width
        for i in range(0, len(formatted_stocks), 2):
            left_col = formatted_stocks[i]
            right_col = formatted_stocks[i + 1] if i + 1 < len(formatted_stocks) else ""
            
            if right_col:
                # Use global max width for consistent alignment
                print(f"{left_col:<{max_width + 2}}{right_col}")
            else:
                print(left_col)
        
        print()
    
    print(f"Total: {len(settings.AVAILABLE_STOCKS)} stocks across {len(sectors)} sectors")

def print_help():
    """Prints usage information."""
    help_text = """
Usage: python simulate.py [num_simulations] [default_investment_amt] [-v|--verbose] [--clear-cache] [--update-cache] [--list-stocks]

Arguments:
  num_simulations         Number of simulations to run (default: settings.NUM_SIMULATIONS)
  default_investment_amt  Dollar amount to invest per simulation (default: settings.DEFAULT_INVESTMENT)
Options:
  -h, --help              Show this help message and exit
  -v, --verbose           Enable verbose output
  --clear-cache           Clear the cached historical data and exit
  --update-cache          Update the cache for all locally cached stocks
  --list-stocks           Show all available stocks for simulation and exit
"""
    print(help_text)

def parse_args():
    """Parses command line arguments."""
    num_simulations = settings.NUM_SIMULATIONS
    default_investment = settings.DEFAULT_INVESTMENT
    verbose = False
    clear_cache_flag = False
    update_cache_flag = False
    list_stocks_flag = False

    args = [arg for arg in sys.argv[1:] if not arg.startswith('-')]
    flags = [arg for arg in sys.argv[1:] if arg.startswith('-')]

    if '-h' in flags or '--help' in flags:
        print_help()
        sys.exit(0)
    if '-v' in flags or '--verbose' in flags:
        verbose = True
    if '--clear-cache' in flags:
        clear_cache_flag = True
    if '--update-cache' in flags:
        update_cache_flag = True
    if '--list-stocks' in flags:
        list_stocks_flag = True

    if len(args) > 0:
        try:
            num_simulations = int(args[0])
        except ValueError:
            print(f"Warning: Could not parse number of simulations '{args[0]}', using default {settings.NUM_SIMULATIONS}")

    if len(args) > 1:
        original_arg = args[1]
        amt_str = original_arg.replace('$', '').replace(',', '').strip()
        
        try:
            # sigh, this turned out to just be a bash thing, trying to get rid of the $
            float_value = float(amt_str)
            default_investment = int(float_value)
            
        except ValueError as e:
            print(f"Warning: Could not parse investment amount '{original_arg}': {e}")
            print(f"Using default ${settings.DEFAULT_INVESTMENT}")

    return num_simulations, default_investment, verbose, clear_cache_flag, update_cache_flag, list_stocks_flag

if __name__ == "__main__":
    num_simulations, default_investment, verbose, clear_cache_flag, update_cache_flag, list_stocks_flag = parse_args()
    
    if clear_cache_flag:
        clear_cache()
        sys.exit(0)
    if update_cache_flag:
        HistoricalData.update_all_caches()
        sys.exit(0)
    if list_stocks_flag:
        print_available_stocks()
        sys.exit(0)
    
    # Pass investment_amount explicitly to avoid global variable issues
    results, elapsed_time = run_simulation(num_simulations, default_investment, verbose)
    print_summary(results, default_investment, elapsed_time)
