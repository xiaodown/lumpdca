# lumpdca
A simulator for DCA vs Lump sum stock investing.  

Tells you what percentage of the time it would have been better to dollar cost average vs. buying stocks in one lump purchase, based on historical data.

## What a simulation is

For a given flat amount of money:

 * Pick a stock from the list.
 * Pick a date between the earliest date that we have data for and 2020. Note: data only goes back to 1990.
 * For the Lump Sum, subtract $20 from the starting capital for a trading fee, then buy the maximum number of whole shares possible with the money on the next available trading day.
 * For the DCA, pick a random choice between 2, 5, and 10 years, then on the first trading day of each month, buy an equal dollar amount worth of whole shares of the same stock as the lump sum simulation, such that you spend roughly the same amount each month over the course of your 2, 5, or 10 year DCA period. Each transaction also incurs a $20 fee. Any money left over from one month rolls into the next.
 * See what the value of your investment is "today" (technically yesterday or the most recent full trading day) - prices available up through whatever the latest the yfinance (yahoo finance) library has.

That constitutes one simulation.

On a modern processor, you can expect it to take about ~5ish minutes per 100,000 simulations~.  It runs (2x num_cores) threads, so the more and faster cores your processor has the faster it'll run.

**Update:** I swapped from Threadpool to Processpool and got about a 10x speedup on Windows + WSL2 (vs. mac m1 hardware) due to GILs and process contention.  On an m1 mac it'll take ~5m for 100,000 simulations.  ~On my 9950x3d it's more like 22 sec now (used to be 8min).~

**Update 2:** Oops, found another optimization - now takes less than 5 secs to run 1,000,000 simulations.  Yowza.

## Caveats

This is NOT an accurate or scientific simulation, it's just for fun.  There are multiple points at which it doesn't simulate actual investment with full fidelity.

Caveats include:

 * This /should/ account for splits (prices in yfinance are split-adjusted).
 * This does not account for dividends. However, since it's a comparison of DCAing one stock vs. buying a lump sum of the same stock, reinvesting the dividends would mostly equal out in the wash, with a bias towards lump sum.
 * The list of stocks was mostly just chosen by me - it's a bunch of blue chips plus a bunch of zeitgeist regular suspects. It may not be representative.
 * This was built for speed, not accuracy, and shouldn't be taken as anything useful for actual investing advice. Also the code is pretty sloppy.
 * People probably don't DCA into the same company for 10 years. I know that. It was just useful for the simulation.
 * I don't know anything about investment software outside of the etrade app on my phone. There are probably very large, very accurate, very expensive software suits that exist out there for doing exactly this. There's no way this is novel.
 * This was done more for the learning experience with the available python libraries than for the investment advice (such as it is).

## Installation
Use your favorite python package manager; I'm partial to Astral uv.
```
curl -LsSf https://astral.sh/uv/install.sh | sh
```
Then, check out the repo and install the dependencies
```
git clone https://github.com/xiaodown/lumpdca.git
cd lumpdca
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

## Usage
To run a simulation, with your venv active:
```
python simulate.py <num_of_simulations> <starting_capital>
```
If you want to force it to update its stock list with more up-to-date data:
```
python simulate.py --update-cache
```
To clear out the cache:
```
python simulate.py --clear-cache
```
and to list the stocks:
```
python simulate.py --list-stocks
```

All of this can be seen in the help as well:
```
python simulate.py --help
```

### Adding stocks
The stocks are configured in the settings.py and the format is fairly obvious, so you can just add or delete them from there.    
Their format is basically:
```
("TICKER", "Name of stock", <year_of_earliest_data>, "Sector"),
```
where TICKER is the stock symbol, name is just human readable and I don't think is really used, `<year_of_earliest_data>` is the first year where there's solid
data available about the company, and Sector isn't used.  I originally planned to be able to run simulations specifically by sector, but never coded it.

Note: for the year_of_earliest_data, if the company is old I just put 1990 (I think this may be as far back as the library that I'm using to pull data will go?), or
if the company is fairly new, I just put the year after their founding - i.e. company founded in 1997, I put 1998 just to make sure the program doesn't get confused
if it picks a date in 1997 prior to when the company went public.

If you do add/remove stocks from this list, you should probably clear and then update the cache.

## List of stocks

By default, the list of stocks is:

 *  SPDR S&P 500 ETF
 *  Invesco QQQ ETF
 *  iShares Russell 2000 ETF
 *  Vanguard Total Stock Market ETF
 *  iShares MSCI EAFE ETF
 *  Vanguard FTSE Developed Markets ETF
 *  Apple Inc.
 *  Microsoft Corporation
 *  Alphabet Inc.
 *  Amazon.com Inc.
 *  Tesla Inc.
 *  Meta Platforms Inc.
 *  International Business Machines
 *  Oracle Corporation
 *  Intel Corporation
 *  Cisco Systems Inc.
 *  The Coca-Cola Company
 *  Procter & Gamble Co.
 *  Walmart Inc.
 *  McDonald's Corporation
 *  The Walt Disney Company
 *  NIKE Inc.
 *  PepsiCo Inc.
 *  The Home Depot Inc.
 *  Target Corporation
 *  Starbucks Corporation
 *  Johnson & Johnson
 *  Pfizer Inc.
 *  UnitedHealth Group Inc.
 *  Abbott Laboratories
 *  Merck & Co. Inc.
 *  JPMorgan Chase & Co.
 *  Berkshire Hathaway Inc.
 *  Bank of America Corp.
 *  Wells Fargo & Company
 *  The Goldman Sachs Group Inc.
 *  Morgan Stanley
 *  Exxon Mobil Corporation
 *  Chevron Corporation
 *  ConocoPhillips
 *  General Electric Company
 *  Ford Motor Company
 *  Caterpillar Inc.
 *  The Boeing Company
 *  3M Company
 *  Honeywell International Inc.
 *  AT&T Inc.
 *  Verizon Communications Inc.
 *  T-Mobile US Inc.
 *  Comcast Corporation
