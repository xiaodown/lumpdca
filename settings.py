# settings for running stock simulation
CACHE_DB = "data_cache.db"
DEFAULT_START = "2000-01-01"

# Available stocks for simulation
# Format: (ticker, name, start_year, sector) - start_year is when good data begins
AVAILABLE_STOCKS = [
    # ETFs
    ("SPY", "SPDR S&P 500 ETF", 2000, "ETF"),
    ("QQQ", "Invesco QQQ ETF", 2000, "ETF"),
    ("IWM", "iShares Russell 2000 ETF", 2000, "ETF"),
    ("VTI", "Vanguard Total Stock Market ETF", 2001, "ETF"),
    ("EFA", "iShares MSCI EAFE ETF", 2001, "ETF"),
    ("VEA", "Vanguard FTSE Developed Markets ETF", 2007, "ETF"),
    
    # Technology
    ("AAPL", "Apple Inc.", 2000, "Technology"),
    ("MSFT", "Microsoft Corporation", 1990, "Technology"),
    ("GOOGL", "Alphabet Inc.", 2004, "Technology"),
    ("AMZN", "Amazon.com Inc.", 2000, "Technology"),
    ("TSLA", "Tesla Inc.", 2010, "Technology"),
    ("META", "Meta Platforms Inc.", 2012, "Technology"),
    ("IBM", "International Business Machines", 1990, "Technology"),
    ("ORCL", "Oracle Corporation", 1990, "Technology"),
    ("INTC", "Intel Corporation", 1990, "Technology"),
    ("CSCO", "Cisco Systems Inc.", 1990, "Technology"),
    
    # Consumer Goods
    ("KO", "The Coca-Cola Company", 1990, "Consumer Goods"),
    ("PG", "Procter & Gamble Co.", 1990, "Consumer Goods"),
    ("WMT", "Walmart Inc.", 1990, "Consumer Goods"),
    ("MCD", "McDonald's Corporation", 1990, "Consumer Goods"),
    ("DIS", "The Walt Disney Company", 1990, "Consumer Goods"),
    ("NKE", "NIKE Inc.", 1990, "Consumer Goods"),
    ("PEP", "PepsiCo Inc.", 1990, "Consumer Goods"),
    ("HD", "The Home Depot Inc.", 1990, "Consumer Goods"),
    ("TGT", "Target Corporation", 1990, "Consumer Goods"),
    ("SBUX", "Starbucks Corporation", 1992, "Consumer Goods"),
    
    # Healthcare
    ("JNJ", "Johnson & Johnson", 1990, "Healthcare"),
    ("PFE", "Pfizer Inc.", 1990, "Healthcare"),
    ("UNH", "UnitedHealth Group Inc.", 1990, "Healthcare"),
    ("ABT", "Abbott Laboratories", 1990, "Healthcare"),
    ("MRK", "Merck & Co. Inc.", 1990, "Healthcare"),
    
    # Financial
    ("JPM", "JPMorgan Chase & Co.", 1990, "Financial"),
    ("BRK-B", "Berkshire Hathaway Inc.", 2000, "Financial"),
    ("BAC", "Bank of America Corp.", 1990, "Financial"),
    ("WFC", "Wells Fargo & Company", 1990, "Financial"),
    ("GS", "The Goldman Sachs Group Inc.", 1999, "Financial"),
    ("MS", "Morgan Stanley", 1990, "Financial"),
    
    # Energy
    ("XOM", "Exxon Mobil Corporation", 1990, "Energy"),
    ("CVX", "Chevron Corporation", 1990, "Energy"),
    ("COP", "ConocoPhillips", 1990, "Energy"),
    
    # Industrial
    ("GE", "General Electric Company", 1990, "Industrial"),
    ("F", "Ford Motor Company", 1990, "Industrial"),
    ("CAT", "Caterpillar Inc.", 1990, "Industrial"),
    ("BA", "The Boeing Company", 1990, "Industrial"),
    ("MMM", "3M Company", 1990, "Industrial"),
    ("HON", "Honeywell International Inc.", 1990, "Industrial"),
    
    # Telecommunications
    ("T", "AT&T Inc.", 1990, "Telecommunications"),
    ("VZ", "Verizon Communications Inc.", 1990, "Telecommunications"),
    ("TMUS", "T-Mobile US Inc.", 2007, "Telecommunications"),
    ("CMCSA", "Comcast Corporation", 1990, "Telecommunications"),
]

NUM_SIMULATIONS = 10
TRADE_FEE = 20
DEFAULT_INVESTMENT = 10000