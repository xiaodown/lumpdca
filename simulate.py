import sys
import random
import threading
import time
from datetime import datetime, timedelta
from data import HistoricalData, clear_cache
import pandas as pd
import settings

TRADE_FEE = settings.TRADE_FEE
DEFAULT_INVESTMENT = settings.DEFAULT_INVESTMENT

class OutputManager:
    """Manages fancy console output with spinner and scrolling results."""
    
    def __init__(self, max_lines=10):
        self.max_lines = max_lines
        self.results_lines = []
        self.spinner_active = False
        self.spinner_thread = None
        self.current_status = ""
        self.header_printed = False
        
    def print_header(self, num_simulations, investment_amount):
        """Print static header information."""
        print("🚀 Investment Strategy Simulation")
        print(f"   Running {num_simulations} simulations with ${investment_amount:,} investment")
        print("   " + "="*50)
        print()  # One blank line
        self.header_printed = True
        
    def start_spinner(self, status="Processing..."):
        """Start the spinner with given status."""
        self.current_status = status
        self.spinner_active = True
        self.spinner_thread = threading.Thread(target=self._spin)
        self.spinner_thread.daemon = True
        self.spinner_thread.start()
        
    def stop_spinner(self):
        """Stop the spinner."""
        self.spinner_active = False
        if self.spinner_thread:
            self.spinner_thread.join()
        # Clear the spinner line
        print("\r" + " " * 80 + "\r", end="", flush=True)
        
    def _spin(self):
        """Internal spinner animation."""
        chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        while self.spinner_active:
            for char in chars:
                if not self.spinner_active:
                    break
                print(f"\r{char} {self.current_status}", end="", flush=True)
                time.sleep(0.1)
                
    def add_result(self, line):
        """Add a simulation result line."""
        self.results_lines.append(line)
        if len(self.results_lines) > self.max_lines:
            self.results_lines.pop(0)
        self._update_display()
        
    def _update_display(self):
        """Update the scrolling display."""
        # Force cursor to beginning of line, then move up to overwrite previous lines
        if self.results_lines:
            print(f"\r\033[{len(self.results_lines)}A", end="")
            for line in self.results_lines:
                print(f"\033[K{line}")  # Clear line and print
        
    def cache_miss(self, ticker):
        """Show cache miss notification."""
        self.stop_spinner()
        print(f"\r📥 Downloading fresh data for {ticker}...")
        
    def clear_results(self):
        """Clear the results display area."""
        if self.results_lines:
            # Only add 3 newlines instead of many
            print("\n\n\n")

def print_available_stocks():
    """Print all available stocks for simulation, grouped by sector."""
    print("📈 Available stocks for simulation:")
    print()
    
    # Group stocks by sector
    sectors = {}
    for ticker, name, start_year, sector in settings.AVAILABLE_STOCKS:
        if sector not in sectors:
            sectors[sector] = []
        sectors[sector].append((ticker, name, start_year))
    
    # Sort sectors for consistent display
    for sector in sorted(sectors.keys()):
        stocks = sectors[sector]
        print(f"{sector}:")
        for ticker, name, start_year in sorted(stocks):
            print(f"  {ticker:<6} - {name} (data from {start_year})")
        print()
    
    print(f"Total: {len(settings.AVAILABLE_STOCKS)} stocks across {len(sectors)} sectors")

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
    # Use the stock's actual start year, but no earlier than 1990
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

class LumpSumStrategy:
    """Simulates lump sum investing."""
    def __init__(self, ticker, start_date, investment):
        self.ticker = ticker
        self.start_date = start_date
        self.investment = investment

    def run(self):
        data = HistoricalData(self.ticker).get_data(self.start_date, datetime.today().strftime("%Y-%m-%d"))
        
        if data.empty:
            return None
        
        if 'Close' not in data.columns:
            return None
        
        start_price = data.iloc[0]['Close']
        end_price = data.iloc[-1]['Close']
        
        available = self.investment - TRADE_FEE
        shares = int(available // start_price)
        value_today = shares * end_price
        
        return value_today

class DCAStrategy:
    """Simulates dollar-cost averaging."""
    def __init__(self, ticker, start_date, years, investment):
        self.ticker = ticker
        self.start_date = start_date
        self.years = years
        self.investment = investment

    def run(self, debug=False):
        start_dt = datetime.strptime(self.start_date, "%Y-%m-%d")
        today_dt = datetime.today()
        available_months = (today_dt.year - start_dt.year) * 12 + (today_dt.month - start_dt.month)
        dca_months = min(self.years * 12, available_months)
        
        if dca_months <= 0:
            return 0
        
        monthly_contribution = self.investment / dca_months
        data = HistoricalData(self.ticker).get_data(self.start_date, today_dt.strftime("%Y-%m-%d"))
        
        if data.empty or 'Close' not in data.columns:
            return None
        
        # Group by year-month and get first trading day of each month
        data['year_month'] = data.index.to_period('M')
        monthly_data = data.groupby('year_month').first()
        
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
        
        end_price = data.iloc[-1]['Close']
        value_today = shares * end_price
        
        return value_today

def run_simulation(num_simulations, verbose=False):
    """Runs the lump sum vs DCA simulation."""
    output = OutputManager()
    results = []
    
    # Print static header
    output.print_header(num_simulations, DEFAULT_INVESTMENT)
    output.start_spinner("Initializing simulations...")
    
    for i in range(num_simulations):
        ticker, name, stock_start_year = pick_random_stock()
        start_date = pick_random_date_for_stock(stock_start_year)
        years = pick_random_years()
        
        output.current_status = f"Simulating {ticker} ({i+1}/{num_simulations})..."
        
        # Run lump sum strategy (this will load/cache data)
        lump_strategy = LumpSumStrategy(ticker, start_date, DEFAULT_INVESTMENT)
        lump = lump_strategy.run()
        
        # Check if we had a cache miss during lump sum calculation
        historical_data = HistoricalData(ticker)
        if historical_data.was_cache_miss():
            output.cache_miss(ticker)
            output.start_spinner(f"Simulating {ticker} ({i+1}/{num_simulations})...")
        
        # Run DCA strategy (data should now be cached)
        dca = DCAStrategy(ticker, start_date, years, DEFAULT_INVESTMENT).run()
        
        winner, percent_better = calculate_performance(lump, dca)
        
        if winner != "ERROR":
            # Left-justified formatting
            result_line = f"{ticker} from {start_date}: {winner} wins by {percent_better:5.1f}% ({format_currency(lump if winner == 'LUMP' else dca)})"
            output.add_result(result_line)
        
        results.append({
            'ticker': ticker, 
            'name': name,
            'start_date': start_date, 
            'lump': lump, 
            'dca': dca, 
            'years': years,
            'winner': winner,
            'percent_better': percent_better
        })
        
        # Removed time.sleep(0.1) - no more pauses!
    
    output.stop_spinner()
    output.clear_results()
    
    return results

def print_summary(results):
    """Print summary statistics with better statistical analysis."""
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
    print(f"Total Simulations: {total}")
    print(f"Starting Capital:  {format_currency(DEFAULT_INVESTMENT)}")  # Added starting capital line
    print(f"Lump Sum Wins:     {lump_wins} ({lump_wins/total*100:.1f}%)")
    print(f"DCA Wins:          {dca_wins} ({dca_wins/total*100:.1f}%)")
    
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
    if max_lump > avg_lump * 3:  # If max is more than 3x average
        print(f"\n⚠️  Note: Large outliers detected. Median may be more representative than average.")
    
    print("="*60)

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
            pass
    if len(args) > 1:
        amt_str = args[1].replace('$', '').replace(',', '')
        try:
            default_investment = float(amt_str)
        except ValueError:
            pass

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
    
    # Update the global investment amount
    DEFAULT_INVESTMENT = default_investment
    
    results = run_simulation(num_simulations, verbose)
    print_summary(results)
