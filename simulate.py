import sys
import time
import random
import threading
import os
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from data import HistoricalData, clear_cache
import pandas as pd
import settings

TRADE_FEE = settings.TRADE_FEE

class ThreadSafeOutputManager:
    """Thread-safe output manager with progress bar and scrolling results."""
    
    def __init__(self, max_lines=8):
        self.max_lines = max_lines
        self.recent_results = []
        self.completed_count = 0
        self.total_count = 0
        self.cache_downloads = set()  # Use set to avoid duplicates
        self.lock = threading.Lock()
        self.last_display_lines = 0
        
    def print_header(self, num_simulations, investment_amount, num_threads):
        """Print static header information."""
        print("🚀 Investment Strategy Simulation")
        print(f"   Running {num_simulations:,} simulations with ${investment_amount:,} investment")
        print(f"   Using {num_threads} threads on {os.cpu_count()} available cores")
        print("   " + "="*60)
        print()
        self.total_count = num_simulations
        
    def add_cache_download(self, ticker):
        """Record a cache download."""
        with self.lock:
            self.cache_downloads.add(ticker)
            self._update_display()
    
    def add_result(self, result_line):
        """Add a completed simulation result."""
        with self.lock:
            self.completed_count += 1
            self.recent_results.append(result_line)
            if len(self.recent_results) > self.max_lines:
                self.recent_results.pop(0)
            self._update_display()
    
    def _update_display(self):
        """Update the progress display - MUCH simpler approach."""
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
        with self.lock:
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

class ThreadSafeHistoricalData:
    """Thread-safe wrapper for HistoricalData with download notification."""
    
    _data_cache = {}  # Class-level cache to avoid duplicate HistoricalData objects
    _cache_lock = threading.Lock()
        
    @classmethod
    def get_cached_data(cls, ticker, start_date, end_date, output_manager=None):
        """Get data with thread-safe caching and download notification."""
        # Check if we already have this ticker's HistoricalData object in memory
        with cls._cache_lock:
            if ticker not in cls._data_cache:
                cls._data_cache[ticker] = HistoricalData(ticker)
            
            historical_data = cls._data_cache[ticker]
        
        # Get the data (HistoricalData handles its own download locking)
        data = historical_data.get_data(start_date, end_date)
        
        # Check if it was a cache miss and notify output manager
        if historical_data.was_cache_miss() and output_manager:
            output_manager.add_cache_download(ticker)
        
        return data

class LumpSumStrategy:
    """Thread-safe lump sum investing strategy."""
    def __init__(self, ticker, start_date, investment):
        self.ticker = ticker
        self.start_date = start_date
        self.investment = investment

    def run(self, output_manager=None):
        data = ThreadSafeHistoricalData.get_cached_data(
            self.ticker, self.start_date, datetime.today().strftime("%Y-%m-%d"), output_manager
        )
        
        # Clean error handling
        if data is None or data.empty or 'Close' not in data.columns:
            return None
        
        start_price = data.iloc[0]['Close']
        end_price = data.iloc[-1]['Close']
        
        available = self.investment - TRADE_FEE
        shares = int(available // start_price)
        value_today = shares * end_price
        
        return value_today

class DCAStrategy:
    """Thread-safe dollar-cost averaging strategy."""
    def __init__(self, ticker, start_date, years, investment):
        self.ticker = ticker
        self.start_date = start_date
        self.years = years
        self.investment = investment

    def run(self, output_manager=None):
        start_dt = datetime.strptime(self.start_date, "%Y-%m-%d")
        today_dt = datetime.today()
        available_months = (today_dt.year - start_dt.year) * 12 + (today_dt.month - start_dt.month)
        dca_months = min(self.years * 12, available_months)
        
        if dca_months <= 0:
            return 0
        
        monthly_contribution = self.investment / dca_months
        data = ThreadSafeHistoricalData.get_cached_data(
            self.ticker, self.start_date, today_dt.strftime("%Y-%m-%d"), output_manager
        )
        
        # Clean error handling
        if data is None or data.empty or 'Close' not in data.columns:
            return None
        
        # Make a proper copy to avoid pandas warnings
        data_copy = data.copy()
        data_copy['year_month'] = data_copy.index.to_period('M')
        monthly_data = data_copy.groupby('year_month').first()
        
        shares = 0
        leftover = 0
        months_processed = 0
        
        for period, row in monthly_data.iterrows():
            if months_processed >= dca_months:
                break
            
            price = row['Close']
            available = monthly_contribution + leftover
            
            if available >= (price + TRADE_FEE):
                available_for_shares = available - TRADE_FEE
                buy_shares = int(available_for_shares // price)
                cost_of_shares = buy_shares * price
                leftover = available_for_shares - cost_of_shares
                shares += buy_shares
            else:
                leftover = available
            
            months_processed += 1
        
        end_price = data_copy.iloc[-1]['Close']
        value_today = shares * end_price
        
        return value_today

def run_single_simulation(sim_number, investment_amount, output_manager):
    """Run one simulation - thread-safe version."""
    # Use thread-local random to avoid conflicts
    local_random = random.Random()
    local_random.seed()  # Let it auto-seed properly
    
    # Temporarily replace random functions with thread-local versions
    original_choice = random.choice
    original_randint = random.randint
    random.choice = local_random.choice
    random.randint = local_random.randint
    
    try:
        ticker, name, stock_start_year = pick_random_stock()
        start_date = pick_random_date_for_stock(stock_start_year)
        years = pick_random_years()
        
        lump = LumpSumStrategy(ticker, start_date, investment_amount).run(output_manager)
        dca = DCAStrategy(ticker, start_date, years, investment_amount).run(output_manager)
        
        winner, percent_better = calculate_performance(lump, dca)
        
        # Add result to output
        if winner != "ERROR":
            result_line = f"{ticker} from {start_date}: {winner} wins by {percent_better:5.1f}% ({format_currency(lump if winner == 'LUMP' else dca)})"
            output_manager.add_result(result_line)
        
        return {
            'sim_number': sim_number,
            'ticker': ticker, 
            'name': name,
            'start_date': start_date, 
            'lump': lump, 
            'dca': dca, 
            'years': years,
            'winner': winner,
            'percent_better': percent_better
        }
        
    finally:
        # Restore original random functions
        random.choice = original_choice
        random.randint = original_randint

def run_simulation(num_simulations, investment_amount, verbose=False):
    """Run simulations in parallel with thread-safe output."""
    start_time = time.time()

    # Calculate number of threads (CPU cores * 2, minimum 1)
    num_threads = max(1, os.cpu_count() * 2)
    num_threads = min(num_threads, num_simulations)  # Don't use more threads than simulations
    
    output_manager = ThreadSafeOutputManager()
    output_manager.print_header(num_simulations, investment_amount, num_threads)
    
    results = []
    
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        # Submit all simulations - PASS investment_amount to each simulation
        future_to_sim = {
            executor.submit(run_single_simulation, i, investment_amount, output_manager): i 
            for i in range(num_simulations)
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_sim):
            try:
                result = future.result()
                results.append(result)
            except Exception as exc:
                sim_num = future_to_sim[future]
                print(f'Simulation {sim_num} generated an exception: {exc}')
    
    output_manager.finish()
    
    # Sort results by simulation number to maintain order
    results.sort(key=lambda x: x['sim_number'])
    
    # Calculate elapsed time
    end_time = time.time()
    elapsed_time = end_time - start_time
    
    # Store timing info in results for summary
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
Usage: ./simulate.py [num_simulations] [default_investment_amt] [-v|--verbose] [--clear-cache] [--update-cache] [--list-stocks]

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
